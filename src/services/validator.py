"""
BRC-20 consensus rule validation service.
"""

from typing import Any, Dict, List, Optional

from sqlalchemy import BigInteger, cast, func
from sqlalchemy.orm import Session

from src.models.balance import Balance
from src.models.deploy import Deploy
from src.utils.amounts import (
    add_amounts,
    is_amount_greater_equal,
    is_amount_greater_than,
    is_valid_amount,
    subtract_amounts,
)
from src.utils.bitcoin import (
    extract_address_from_script,
    is_op_return_script,
    is_standard_output,
)
from src.utils.exceptions import BRC20ErrorCodes, ValidationResult


def get_regex_operator(db):
    if hasattr(db.bind, 'dialect') and db.bind.dialect.name == 'postgresql':
        return '~'
    return 'regexp'

class BRC20Validator:
    """Validate operations according to consensus rules"""

    def __init__(self, db_session: Session, legacy_service=None):
        """
        Initialize validator

        Args:
            db_session: Database session for queries
            legacy_service: LegacyTokenService for legacy validation
        """
        self.db = db_session
        self.legacy_service = legacy_service

    def validate_deploy(self, operation: Dict[str, Any]) -> ValidationResult:
        """
        Validate deploy operation

        Args:
            operation: Parsed deploy operation

        Returns:
            ValidationResult: Validation result

        RULES:
        - Ticker must not already exist
        - max_supply must be valid integer
        - limit_per_op optional but if present must be valid integer
        - NEW: Token must not exist on legacy system
        """
        ticker = operation.get("tick")
        
        # Extract fields from either m/l or max/lim format
        if "m" in operation:
            max_supply = operation.get("m")
            limit_per_op = operation.get("l")
        elif "max" in operation:
            max_supply = operation.get("max")
            limit_per_op = operation.get("lim")
        else:
            return ValidationResult(
                False,
                BRC20ErrorCodes.INVALID_AMOUNT,
                "Missing max supply field (use 'm' or 'max')"
            )

        # 1. Existing validation (ticker not exists, valid amounts)
        existing_deploy = (
            self.db.query(Deploy).filter(Deploy.ticker.ilike(ticker)).first()
        )
        if existing_deploy:
            return ValidationResult(
                False,
                BRC20ErrorCodes.TICKER_ALREADY_EXISTS,
                f"Ticker '{ticker}' already deployed",
            )

        if not is_valid_amount(max_supply):
            return ValidationResult(
                False,
                BRC20ErrorCodes.INVALID_AMOUNT,
                f"Invalid max supply: {max_supply}",
            )

        if limit_per_op is not None:
            if not is_valid_amount(limit_per_op):
                return ValidationResult(
                    False,
                    BRC20ErrorCodes.INVALID_AMOUNT,
                    f"Invalid limit per operation: {limit_per_op}",
                )

        # 2. NEW: Legacy validation (not deployed on Ordinals)
        if self.legacy_service:
            block_height = operation.get("block_height")
            legacy_validation = self.legacy_service.validate_deploy_against_legacy(ticker, block_height)
            if not legacy_validation.is_valid:
                return legacy_validation

        return ValidationResult(True)

    def validate_mint(
        self, operation: Dict[str, Any], deploy: Optional[Deploy], current_supply: str
    ) -> ValidationResult:
        """
        Validate mint operation

        Args:
            operation: Parsed mint operation
            deploy: Deploy record for the ticker
            current_supply: Current total supply as string

        Returns:
            ValidationResult: Validation result

        RULES:
        - Ticker must exist (valid deploy)
        - amount must be ≤ limit_per_op IF defined
        - current_supply + amount ≤ max_supply
        """
        ticker = operation.get("tick")
        amount = operation.get("amt")

        if deploy is None:
            return ValidationResult(
                False,
                BRC20ErrorCodes.TICKER_NOT_DEPLOYED,
                f"Ticker '{ticker}' not deployed",
            )

        if not is_valid_amount(amount):
            return ValidationResult(
                False, BRC20ErrorCodes.INVALID_AMOUNT, f"Invalid mint amount: {amount}"
            )

        if deploy.limit_per_op is not None:
            if is_amount_greater_than(amount, deploy.limit_per_op):
                return ValidationResult(
                    False,
                    BRC20ErrorCodes.EXCEEDS_MINT_LIMIT,
                    f"Mint amount {amount} exceeds limit {deploy.limit_per_op}",
                )

        overflow_result = self.validate_mint_overflow(ticker, amount, deploy)
        if not overflow_result.is_valid:
            return overflow_result

        return ValidationResult(True)

    def validate_transfer(
        self,
        operation: Dict[str, Any],
        sender_balance: str,
        deploy: Optional[Deploy] = None,
    ) -> ValidationResult:
        """
        Validate transfer operation

        Args:
            operation: Parsed transfer operation
            sender_balance: Sender's current balance as string
            deploy: Deploy record (optional, for additional checks)

        Returns:
            ValidationResult: Validation result

        CRITICAL RULES:
        - Ticker must exist
        - sender_balance ≥ amount
        - NO limit_per_op verification (limit only applies to mints)
        """
        ticker = operation.get("tick")
        amount = operation.get("amt")

        if deploy is None:
            return ValidationResult(
                False,
                BRC20ErrorCodes.TICKER_NOT_DEPLOYED,
                f"Ticker '{ticker}' not deployed",
            )

        if not is_valid_amount(amount):
            return ValidationResult(
                False,
                BRC20ErrorCodes.INVALID_AMOUNT,
                f"Invalid transfer amount: {amount}",
            )

        if not is_amount_greater_equal(sender_balance, amount):
            return ValidationResult(
                False,
                BRC20ErrorCodes.INSUFFICIENT_BALANCE,
                f"Insufficient balance: {sender_balance} < {amount}",
            )

        return ValidationResult(True)

    def validate_output_addresses(
        self, tx_outputs: List[Dict[str, Any]], operation_type: str = None
    ) -> ValidationResult:
        """
        Validate transaction outputs based on operation type

        Args:
            tx_outputs: List of transaction outputs
            operation_type: Type of operation ('deploy', 'mint', 'transfer')

        Returns:
            ValidationResult: Validation result

        RULES:
        - Deploy: Output after OP_RETURN required (fallback to first input if none)
        - Mint/Transfer: Output after OP_RETURN required and must be a standard output
        - Accept P2PKH, P2SH, P2WPKH, P2WSH, P2TR
        - NO dust limit constraint
        """
        if not isinstance(tx_outputs, list) or not tx_outputs:
            return ValidationResult(
                False,
                BRC20ErrorCodes.NO_STANDARD_OUTPUT,
                "Invalid or empty transaction outputs",
            )

        if operation_type == "deploy":
            return ValidationResult(True)

        has_standard_output = any(
            out.get("scriptPubKey", {}).get("type") != "nulldata"
            and not out.get("scriptPubKey", {}).get("hex", "").startswith("6a")
            for out in tx_outputs
        )

        if not has_standard_output:
            return ValidationResult(
                False,
                BRC20ErrorCodes.NO_STANDARD_OUTPUT,
                "No standard outputs found in transaction",
            )

        return ValidationResult(True)

    def get_output_after_op_return_address(
        self, tx_outputs: List[Dict[str, Any]]
    ) -> Optional[str]:
        """
        Get the address of the output AFTER the OP_RETURN for token allocation

        Args:
            tx_outputs: List of transaction outputs

        Returns:
            Optional[str]: Address of output after OP_RETURN, None if not found

        RULE: Tokens are allocated to the output AFTER the OP_RETURN
        """
        # Find OP_RETURN index
        op_return_index = None
        for i, vout in enumerate(tx_outputs):
            if not isinstance(vout, dict):
                continue

            script_pub_key = vout.get("scriptPubKey", {})
            if not isinstance(script_pub_key, dict):
                continue

            # Identify OP_RETURN
            if script_pub_key.get("type") == "nulldata" or (
                script_pub_key.get("hex", "")
                and script_pub_key.get("hex", "").startswith("6a")
            ):
                op_return_index = i
                break

        if op_return_index is None or op_return_index + 1 >= len(tx_outputs):
            return None

        # Get the next output after OP_RETURN
        next_output = tx_outputs[op_return_index + 1]
        script_pub_key = next_output.get("scriptPubKey", {})

        # Skip if it's another OP_RETURN
        if script_pub_key.get("type") == "nulldata" or (
            script_pub_key.get("hex", "")
            and script_pub_key.get("hex", "").startswith("6a")
        ):
            return None

        # Extract address
        addresses = script_pub_key.get("addresses", [])
        if addresses and len(addresses) > 0:
            return addresses[0]
        elif script_pub_key.get("address", None):
            return script_pub_key.get("address")
        else:
            # Try to extract address from script hex
            script_hex = script_pub_key.get("hex", "")
            if (
                script_hex
                and not is_op_return_script(script_hex)
                and is_standard_output(script_hex)
            ):
                address = extract_address_from_script(script_hex)
                if address:
                    return address

        return None

    def get_current_supply(self, ticker: str) -> str:
        """
        Get current total supply for a ticker

        Args:
            ticker: Token ticker

        Returns:
            str: Current total supply as string
        """
        regex_op = get_regex_operator(self.db)
        # Sum all balances for this ticker - Use case-insensitive comparison
        total = (
            self.db.query(func.coalesce(func.sum(cast(Balance.balance, BigInteger)), 0))
            .filter(Balance.ticker.ilike(ticker))
            .filter(Balance.balance.op(regex_op)('^[0-9]+$'))  # Cross-DB regex: only numeric balances
            .scalar()
        )

        return str(total or 0)

    def get_total_minted(self, ticker: str) -> str:
        """
        Get current total minted amount for ticker from database

        CRITICAL: Only count valid mint operations

        Args:
            ticker: Token ticker

        Returns:
            str: Total minted amount as string
        """
        from src.models.transaction import BRC20Operation
        regex_op = get_regex_operator(self.db)
        # Sum all valid mint operations for this ticker
        result = (
            self.db.query(
                func.coalesce(func.sum(cast(BRC20Operation.amount, BigInteger)), 0)
            )
            .filter(
                BRC20Operation.ticker.ilike(ticker),  # Case-insensitive comparison
                BRC20Operation.operation == "mint",
                BRC20Operation.is_valid is True,  # Only count valid mints
                BRC20Operation.amount.op(regex_op)('^[0-9]+$'),  # Cross-DB regex: only numeric amounts
            )
            .scalar()
        )

        return str(result) if result else "0"

    def validate_mint_overflow(
        self, ticker: str, mint_amount: str, deploy: Deploy
    ) -> ValidationResult:
        """
        CRITICAL: Validate that mint doesn't exceed max supply

        ALGORITHM:
        1. Get current total minted for ticker (from valid mint operations)
        2. Add proposed mint amount to current total
        3. Compare new total against max supply
        4. REJECT if new total > max supply

        Args:
            ticker: Token ticker
            mint_amount: Amount to mint
            deploy: Deploy record with max_supply

        Returns:
            ValidationResult: Valid if mint doesn't exceed max supply
        """
        # Step 1: Calculate CURRENT total minted from database
        current_total_minted = self.get_total_minted(ticker)

        # Step 2: Calculate PROPOSED total after this mint
        try:
            proposed_total_after_mint = add_amounts(current_total_minted, mint_amount)
        except ValueError as e:
            return ValidationResult(
                False,
                BRC20ErrorCodes.INVALID_AMOUNT,
                f"Amount calculation error: {str(e)}",
            )

        # Step 3: Compare against max supply
        if is_amount_greater_than(proposed_total_after_mint, deploy.max_supply):
            # EXCEEDS MAX SUPPLY - REJECT!
            excess_amount = subtract_amounts(
                proposed_total_after_mint, deploy.max_supply
            )

            return ValidationResult(
                False,
                BRC20ErrorCodes.EXCEEDS_MAX_SUPPLY,
                f"Mint would exceed max supply. "
                f"Current: {current_total_minted}, "
                f"Mint: {mint_amount}, "
                f"Proposed: {proposed_total_after_mint}, "
                f"Max: {deploy.max_supply}, "
                f"Excess: {excess_amount}",
            )

        # VALID - within max supply
        return ValidationResult(True)

    def get_first_standard_output_address(self, tx_outputs: list) -> str | None:
        """
        Get the first standard (non-OP_RETURN) output address from transaction outputs.

        Args:
            tx_outputs: List of transaction outputs

        Returns:
            The first standard output address or None if no standard output found
        """
        return self.get_output_after_op_return_address(tx_outputs)

    def get_balance(self, address: str, ticker: str) -> str:
        """
        Get balance for specific address and ticker

        Args:
            address: Bitcoin address
            ticker: Token ticker

        Returns:
            str: Balance as string (0 if not found)
        """
        balance_record = (
            self.db.query(Balance)
            .filter(Balance.address == address, Balance.ticker.ilike(ticker))
            .first()
        )

        return balance_record.balance if balance_record else "0"

    def get_deploy_record(self, ticker: str) -> Optional[Deploy]:
        """
        Get deploy record for ticker

        Args:
            ticker: Token ticker

        Returns:
            Optional[Deploy]: Deploy record if exists
        """
        # BRC-20 tickers are case-insensitive
        return self.db.query(Deploy).filter(Deploy.ticker.ilike(ticker)).first()

    def validate_complete_operation(
        self,
        operation: Dict[str, Any],
        tx_outputs: List[Dict[str, Any]],
        sender_address: Optional[str] = None,
    ) -> ValidationResult:
        """
        Validate complete BRC-20 operation with all consensus rules

        Args:
            operation: Parsed BRC-20 operation
            tx_outputs: Transaction outputs
            sender_address: Sender address (for transfers)

        Returns:
            ValidationResult: Complete validation result
        """
        op_type = operation.get("op")
        ticker = operation.get("tick")

        # Validate output addresses with operation type
        output_validation = self.validate_output_addresses(tx_outputs, op_type)
        if not output_validation.is_valid:
            return output_validation

        # For mint and transfer, ensure there's a valid recipient after OP_RETURN
        if op_type in ["mint", "transfer"]:
            recipient_address = self.get_output_after_op_return_address(tx_outputs)
            if not recipient_address:
                return ValidationResult(
                    False,
                    BRC20ErrorCodes.NO_STANDARD_OUTPUT,
                    f"No valid recipient found after OP_RETURN for {op_type} operation",
                )

        # Get deploy record
        deploy = self.get_deploy_record(ticker)

        if op_type == "deploy":
            return self.validate_deploy(operation)

        elif op_type == "mint":
            # Get current supply using the proper method
            current_supply = self.get_total_minted(ticker)
            return self.validate_mint(operation, deploy, current_supply)

        elif op_type == "transfer":
            if sender_address is None:
                return ValidationResult(
                    False,
                    BRC20ErrorCodes.NO_STANDARD_OUTPUT,
                    "Sender address required for transfer validation",
                )

            sender_balance = self.get_balance(sender_address, ticker)
            return self.validate_transfer(operation, sender_balance, deploy)

        else:
            return ValidationResult(
                False,
                BRC20ErrorCodes.INVALID_OPERATION,
                f"Unknown operation type: {op_type}",
            )
