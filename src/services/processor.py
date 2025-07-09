import json
from datetime import datetime, timezone
from typing import Dict, Optional

import structlog
from sqlalchemy.orm import Session

from src.config import settings
from src.models.balance import Balance
from src.models.deploy import Deploy
from src.models.transaction import BRC20Operation
from src.utils.bitcoin import (
    extract_address_from_script,
    extract_signature_from_input,
    is_op_return_script,
    is_sighash_single_anyonecanpay,
    is_standard_output,
)
from src.utils.exceptions import (
    BRC20ErrorCodes,
    BRC20Exception,
    TransferType,
    ValidationResult,
)

from .bitcoin_rpc import BitcoinRPCService
from .parser import BRC20Parser
from .utxo_service import UTXOResolutionService
from .validator import BRC20Validator


class ProcessingResult:
    def __init__(self):
        self.operation_found = False
        self.is_valid = False
        self.error_message = None
        self.operation_type = None
        self.ticker = None
        self.amount = None
        self.txid = None


class BRC20Processor:
    """Process validated operations and update state"""

    def __init__(self, db_session: Session, bitcoin_rpc: BitcoinRPCService):
        self.db = db_session
        self.rpc = bitcoin_rpc
        self.parser = BRC20Parser()
        self.validator = BRC20Validator(db_session)
        self.utxo_service = UTXOResolutionService(bitcoin_rpc)
        self.logger = structlog.get_logger()
        self.current_block_timestamp = None  # ✅ NEW: Store current block timestamp

    def _convert_block_timestamp(self, block_timestamp: int) -> datetime:
        """
        Convert Bitcoin block timestamp to UTC datetime with
        enterprise-grade validation.

        Args:
            block_timestamp: Unix timestamp from Bitcoin block

        Returns:
            UTC datetime object

        Raises:
            ValueError: If timestamp is invalid or out of range
        """
        # Validate timestamp type and range
        if not isinstance(block_timestamp, int):
            raise ValueError(
                f"Block timestamp must be integer, got " f"{type(block_timestamp)}"
            )

        if block_timestamp <= 0:
            raise ValueError(f"Block timestamp must be positive, got {block_timestamp}")

        # Bitcoin genesis block timestamp (2009-01-03 18:15:05 UTC)
        BITCOIN_GENESIS_TIMESTAMP = 1231006505
        if block_timestamp < BITCOIN_GENESIS_TIMESTAMP:
            raise ValueError(
                f"Block timestamp {block_timestamp} is before Bitcoin genesis"
            )

        # Future timestamp check (allow up to 2 hours in future for clock skew)
        import time

        max_future_timestamp = int(time.time()) + 7200  # 2 hours
        if block_timestamp > max_future_timestamp:
            raise ValueError(f"Block timestamp {block_timestamp} is too far in future")

        try:
            return datetime.fromtimestamp(block_timestamp, tz=timezone.utc)
        except (ValueError, OSError) as e:
            self.logger.error(
                "Failed to convert block timestamp",
                timestamp=block_timestamp,
                error=str(e),
            )
            raise ValueError(f"Invalid block timestamp {block_timestamp}: {e}")

    def process_transaction(
        self,
        tx: dict,
        block_height: int,
        tx_index: int,
        block_timestamp: int,
        block_hash: str,
    ) -> ProcessingResult:
        """
        Process a complete transaction

        REFACTORED WORKFLOW:
        1. Extract OP_RETURN (if present)
        2. Parse BRC-20 payload
        3. Delegate to specific operation processors
        4. Return aggregated result

        Args:
            tx: Transaction data from Bitcoin RPC
            block_height: Height of the block containing this transaction
            tx_index: Index of transaction within the block
            block_timestamp: Unix timestamp of the block from Bitcoin RPC
            block_hash: Hash of the block containing this transaction

        Returns: ProcessingResult with processing details

        Raises:
            ValueError: If block_timestamp is invalid
        """
        result = ProcessingResult()

        try:
            # Validate and store block timestamp
            if not isinstance(block_timestamp, int) or block_timestamp <= 0:
                raise ValueError(f"Invalid block timestamp: {block_timestamp}")

            # ✅ CRITICAL: Validate block_hash is not empty
            if not block_hash or not isinstance(block_hash, str):
                raise ValueError(
                    f"Invalid or empty block_hash: '{block_hash}' for block "
                    f"{block_height}"
                )

            self.current_block_timestamp = block_timestamp

            # Add block info to transaction for delegation
            tx["block_height"] = block_height
            tx["tx_index"] = tx_index
            tx["block_hash"] = block_hash

            # Set txid in result for error logging
            result.txid = tx.get("txid", "unknown")

            # Extract OP_RETURN data
            hex_data, vout_index = self.parser.extract_op_return_data(tx)
            if not hex_data:
                return result  # No OP_RETURN found

            # Add vout_index to tx_info for logging
            tx["vout_index"] = vout_index

            # Parse BRC-20 payload
            parse_result = self.parser.parse_brc20_operation(hex_data)

            # Not a valid BRC20 JSON payload
            if not parse_result["success"]:
                if settings.LOG_NON_BRC20_OPERATIONS:
                    self.logger.debug(
                        "Non-BRC20 OP_RETURN detected",
                        txid=tx.get("txid", "unknown"),
                        block_height=block_height,
                        error=parse_result["error_message"],
                    )
                return result  # operation_found remains False

            # Valid BRC-20 operation
            result.operation_found = True
            parsed_operation = parse_result["data"]

            # Normalize ticker to uppercase
            if parsed_operation.get("tick"):
                parsed_operation["tick"] = parsed_operation["tick"].upper()

            result.operation_type = parsed_operation.get("op")
            result.ticker = parsed_operation.get("tick")
            result.amount = parsed_operation.get("amt")

            # ✅ REFACTORED: Pure delegation to specific processors
            # NO operation-specific logic here - processors handle validation
            operation_type = parsed_operation.get("op")
            if operation_type == "deploy":
                validation_result = self.process_deploy(parsed_operation, tx, hex_data)
            elif operation_type == "mint":
                validation_result = self.process_mint(
                    parsed_operation, tx, hex_data, block_height
                )
            elif operation_type == "transfer":
                validation_result = self.process_transfer(
                    parsed_operation, tx, hex_data, block_height
                )
            else:
                validation_result = ValidationResult(
                    False, BRC20ErrorCodes.INVALID_OPERATION, "Unknown operation type"
                )

            result.is_valid = validation_result.is_valid
            if not validation_result.is_valid:
                result.error_message = (
                    f"{validation_result.error_code}: {validation_result.error_message}"
                )

        except Exception as e:
            result.error_message = f"Processing error: {str(e)}"

        return result

    def process_deploy(
        self, operation: dict, tx_info: dict, hex_data: str
    ) -> ValidationResult:
        """
        Process validated deploy with complete ownership of deploy logic

        REFACTORED: All deploy-specific logic consolidated here

        Args:
            operation: Parsed BRC-20 operation
            tx_info: Transaction information
            hex_data: Raw OP_RETURN data

        Returns:
            ValidationResult with success/failure status
        """
        # Deploy-specific validation
        validation_result = self.validator.validate_complete_operation(
            operation,
            tx_info.get("vout", []),
            None,  # No input address required for deploy
        )

        if validation_result.is_valid:
            # Get deployer address (ONLY from first input address)
            deployer_address = self.get_first_input_address(tx_info)

            # Convert block timestamp safely
            try:
                deploy_timestamp = self._convert_block_timestamp(
                    self.current_block_timestamp
                )
            except ValueError as e:
                self.logger.error(
                    "Failed to process deploy due to timestamp error",
                    ticker=operation["tick"],
                    txid=tx_info["txid"],
                    block_height=tx_info.get("block_height", 0),
                    error=str(e),
                )
                validation_result = ValidationResult(
                    False,
                    BRC20ErrorCodes.INVALID_TIMESTAMP,
                    f"Invalid timestamp: {str(e)}",
                )
            else:
                # Create deploy record
                deploy = Deploy(
                    ticker=operation["tick"],
                    max_supply=operation["m"],
                    limit_per_op=operation.get("l"),
                    deploy_txid=tx_info["txid"],
                    deploy_height=tx_info.get("block_height", 0),
                    deploy_timestamp=deploy_timestamp,
                    deployer_address=deployer_address,
                )

                self.logger.info(
                    "Processing deploy with Bitcoin timestamp",
                    ticker=operation["tick"],
                    txid=tx_info["txid"],
                    block_timestamp=self.current_block_timestamp,
                    deploy_timestamp=deploy_timestamp.isoformat(),
                )
                self.db.add(deploy)
                self.db.flush()

        # Log operation
        self.log_operation(
            operation_data=operation,
            validation_result=validation_result,
            tx_info=tx_info,
            raw_op_return=hex_data,
            parsed_json=json.dumps(operation),
            is_marketplace=False,
        )

        return validation_result

    def process_mint(
        self, operation: dict, tx_info: dict, hex_data: str, block_height: int
    ) -> ValidationResult:
        """
        Process validated mint with complete ownership of mint logic

        REFACTORED: All mint-specific logic consolidated here
        INCLUDES: Block height-based OP_RETURN position validation

        Args:
            operation: Parsed BRC-20 operation
            tx_info: Transaction information
            hex_data: Raw OP_RETURN data
            block_height: Block height for position validation

        Returns:
            ValidationResult with success/failure status
        """
        validation_result = self.validate_mint_op_return_position(tx_info, block_height)
        if not validation_result.is_valid:
            self.log_operation(
                operation_data=operation,
                validation_result=validation_result,
                tx_info=tx_info,
                raw_op_return=hex_data,
                parsed_json=json.dumps(operation),
                is_marketplace=False,
            )
            return validation_result

        validation_result = self.validator.validate_complete_operation(
            operation,
            tx_info.get("vout", []),
            None,  # No input address required for mint
        )

        if validation_result.is_valid:
            recipient_address = self.validator.get_output_after_op_return_address(
                tx_info.get("vout", [])
            )
            if not recipient_address:
                validation_result = ValidationResult(
                    False,
                    BRC20ErrorCodes.INVALID_OUTPUT_ADDRESS,
                    "No valid output address found after OP_RETURN",
                )
            else:
                self.update_balance(
                    address=recipient_address,
                    ticker=operation["tick"],
                    amount_delta=operation["amt"],
                    operation_type="mint",
                )

        self.log_operation(
            operation_data=operation,
            validation_result=validation_result,
            tx_info=tx_info,
            raw_op_return=hex_data,
            parsed_json=json.dumps(operation),
            is_marketplace=False,
        )

        return validation_result

    def _validate_early_marketplace_template(self, tx_info: dict) -> ValidationResult:
        """
        Validate marketplace transfers before block 901350.
        - 1 input with SIGHASH_SINGLE | ACP.
        - At least 3 inputs from different addresses.
        """
        inputs = tx_info.get("vin", [])
        if len(inputs) < 3:
            return ValidationResult(
                False,
                BRC20ErrorCodes.INVALID_MARKETPLACE_TRANSACTION,
                "Early marketplace transaction must have at least 3 inputs.",
            )

        sighash_found = False
        for vin in inputs:
            signature_hex = extract_signature_from_input(vin)
            if signature_hex and is_sighash_single_anyonecanpay(signature_hex):
                sighash_found = True
                break

        if not sighash_found:
            return ValidationResult(
                False,
                BRC20ErrorCodes.INVALID_SIGHASH_TYPE,
                "No input with SIGHASH_SINGLE | ANYONECANPAY found.",
            )

        input_addresses = {
            self.utxo_service.get_input_address(vin["txid"], vin["vout"])
            for vin in inputs
            if "txid" in vin and "vout" in vin
        }
        input_addresses.discard(None)

        if len(input_addresses) < 3:
            return ValidationResult(
                False,
                BRC20ErrorCodes.INVALID_MARKETPLACE_TRANSACTION,
                "Early marketplace transaction must involve at least 3 "
                "different addresses.",
            )

        return ValidationResult(True)

    def _validate_new_marketplace_template(self, tx_info: dict) -> ValidationResult:
        """
        Validate marketplace transfers from block 901350 onwards.
        - First two inputs from the same address with SIGHASH_SINGLE | ACP.
        - At least 3 different addresses involved in inputs.
        """
        inputs = tx_info.get("vin", [])
        if len(inputs) < 3:
            return ValidationResult(
                False,
                BRC20ErrorCodes.INVALID_MARKETPLACE_TRANSACTION,
                "Marketplace transaction must have at least 3 inputs.",
            )

        # Check first two inputs
        if len(inputs) < 2:
            return ValidationResult(
                False,
                BRC20ErrorCodes.INVALID_MARKETPLACE_TRANSACTION,
                "Marketplace transaction must have at least 2 inputs for "
                "template validation.",
            )

        input0_addr = self.utxo_service.get_input_address(
            inputs[0]["txid"], inputs[0]["vout"]
        )
        input1_addr = self.utxo_service.get_input_address(
            inputs[1]["txid"], inputs[1]["vout"]
        )

        if not input0_addr or input0_addr != input1_addr:
            return ValidationResult(
                False,
                BRC20ErrorCodes.INVALID_MARKETPLACE_TRANSACTION,
                "First two inputs must be from the same address.",
            )

        sig0_hex = extract_signature_from_input(inputs[0])
        sig1_hex = extract_signature_from_input(inputs[1])

        if not (
            sig0_hex
            and is_sighash_single_anyonecanpay(sig0_hex)
            and sig1_hex
            and is_sighash_single_anyonecanpay(sig1_hex)
        ):
            return ValidationResult(
                False,
                BRC20ErrorCodes.INVALID_SIGHASH_TYPE,
                "First two inputs must use SIGHASH_SINGLE | ANYONECANPAY.",
            )

        input_addresses = {
            self.utxo_service.get_input_address(vin["txid"], vin["vout"])
            for vin in inputs
            if "txid" in vin and "vout" in vin
        }
        input_addresses.discard(None)

        if len(input_addresses) < 3:
            return ValidationResult(
                False,
                BRC20ErrorCodes.INVALID_MARKETPLACE_TRANSACTION,
                "Marketplace transaction must involve at least 3 different addresses.",
            )

        return ValidationResult(True)

    def validate_marketplace_transfer(
        self, tx_info: dict, block_height: int
    ) -> ValidationResult:
        """
        Validate if a transfer is a valid marketplace transfer based on block height.
        """
        if block_height < 901350:
            return self._validate_early_marketplace_template(tx_info)
        else:
            return self._validate_new_marketplace_template(tx_info)

    def _has_marketplace_sighash(self, tx_info: dict) -> bool:
        """
        Check if a transaction has at least one SIGHASH_SINGLE | ANYONECANPAY input.
        """
        if not tx_info.get("vin"):
            return False
        for vin in tx_info["vin"]:
            signature_hex = extract_signature_from_input(vin)
            if signature_hex and is_sighash_single_anyonecanpay(signature_hex):
                return True
        return False

    def classify_transfer_type(
        self, tx_info: dict, block_height: int
    ) -> "TransferType":
        """
        Classify transfer type before validation for optimization

        OPTIMIZATION: Avoids redundant marketplace validation for simple transfers
        Returns: TransferType enum value
        """
        # Quick check - if no marketplace sighash, it's definitely simple
        if not self._has_marketplace_sighash(tx_info):
            return TransferType.SIMPLE

        # Has marketplace sighash - validate templates
        marketplace_validation = self.validate_marketplace_transfer(
            tx_info, block_height
        )

        if marketplace_validation.is_valid:
            return TransferType.MARKETPLACE
        else:
            return TransferType.INVALID_MARKETPLACE

    def process_transfer(
        self, operation: dict, tx_info: dict, hex_data: str, block_height: int
    ) -> ValidationResult:
        """
        Process validated transfer with complete ownership of transfer logic

        REFACTORED: All transfer-specific logic consolidated here

        Args:
            operation: Parsed BRC-20 operation
            tx_info: Transaction information
            hex_data: Raw OP_RETURN data
            block_height: Block height for transfer type classification

        Returns:
            ValidationResult with success/failure status
        """
        transfer_type = self.classify_transfer_type(tx_info, block_height)

        if transfer_type == TransferType.INVALID_MARKETPLACE:
            validation_result = ValidationResult(
                False,
                BRC20ErrorCodes.INVALID_MARKETPLACE_TRANSACTION,
                "Invalid marketplace transaction structure",
            )
            self.log_operation(
                operation_data=operation,
                validation_result=validation_result,
                tx_info=tx_info,
                raw_op_return=hex_data,
                parsed_json=json.dumps(operation),
                is_marketplace=False,
            )
            return validation_result

        validation_result = self.validate_transfer_specific(
            operation, tx_info, transfer_type
        )

        if not validation_result.is_valid:
            self.log_operation(
                operation_data=operation,
                validation_result=validation_result,
                tx_info=tx_info,
                raw_op_return=hex_data,
                parsed_json=json.dumps(operation),
                is_marketplace=(transfer_type == TransferType.MARKETPLACE),
            )
            return validation_result

        addresses = self.resolve_transfer_addresses(tx_info)
        sender_address = addresses["sender"]
        recipient_address = addresses["recipient"]

        if not sender_address or not recipient_address:
            validation_result = ValidationResult(
                False,
                BRC20ErrorCodes.INVALID_ADDRESS,
                "Unable to resolve sender or recipient address",
            )
        else:
            validation_result = self.validator.validate_complete_operation(
                operation, tx_info.get("vout", []), sender_address
            )

        if validation_result.is_valid:
            self.logger.info(
                "Processing transfer",
                ticker=operation["tick"],
                type=transfer_type.value,
                txid=tx_info["txid"],
            )

            self.update_balance(
                address=sender_address,
                ticker=operation["tick"],
                amount_delta=f"-{operation['amt']}",  # Negative for debit
                operation_type="transfer_out",
            )

            self.update_balance(
                address=recipient_address,
                ticker=operation["tick"],
                amount_delta=operation["amt"],
                operation_type="transfer_in",
            )

        self.log_operation(
            operation_data=operation,
            validation_result=validation_result,
            tx_info=tx_info,
            raw_op_return=hex_data,
            parsed_json=json.dumps(operation),
            is_marketplace=(transfer_type == TransferType.MARKETPLACE),
        )

        return validation_result

    def get_first_input_address(self, tx_info: dict) -> str | None:
        """Extract first input address from transaction"""
        try:
            if not tx_info.get("vin"):
                return None

            first_input = tx_info["vin"][0]

            # Skip coinbase
            if "coinbase" in first_input:
                return None

            # Resolve UTXO
            txid = first_input.get("txid")
            vout = first_input.get("vout")

            if txid is None or vout is None:
                return None

            # Appel avec gestion des erreurs
            try:
                return self.utxo_service.get_input_address(txid, vout)
            except Exception as e:
                self.logger.warning(
                    "Erreur lors de la résolution de l'adresse d'entrée",
                    txid=txid,
                    vout=vout,
                    error=str(e),
                )
                return None

        except Exception as e:
            self.logger.warning(
                "Erreur dans get_first_input_address",
                tx_id=tx_info.get("txid", "unknown"),
                error=str(e),
            )
            return None

    def get_first_standard_output_address(self, tx_outputs: list) -> str | None:
        """
        Get the first standard (non-OP_RETURN) output address from transaction outputs.

        Args:
            tx_outputs: List of transaction outputs

        Returns:
            The first standard output address or None if no standard output found
        """
        if not tx_outputs:
            return None

        for output in tx_outputs:
            script_pub_key = output.get("scriptPubKey", {})

            # First try to get address directly from output
            addresses = script_pub_key.get("addresses", None)
            if addresses and isinstance(addresses, list) and addresses:
                return addresses[0]
            elif script_pub_key.get("address", None):
                return script_pub_key.get("address")

            # If no direct address, try extract from script
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

    def get_input_addresses(self, tx_inputs: list) -> list[str]:
        """
        Extract addresses from transaction inputs

        RULES:
        - Fetch UTXOs via RPC if needed
        - Extract addresses from scripts
        - For transfer, use first address
        """
        addresses = []
        for tx_input in tx_inputs:
            if "address" in tx_input:
                addresses.append(tx_input["address"])
            # Additional logic for extracting from scriptSig would go here
        return addresses

    def update_balance(
        self, address: str, ticker: str, amount_delta: str, operation_type: str
    ) -> None:
        """
        Update address balance atomically

        RULES:
        - Create entry if doesn't exist (balance=0)
        - For mint: balance += amount
        - For transfer: sender -= amount, recipient += amount
        - Use string utilities to avoid overflow
        """
        balance = Balance.get_or_create(self.db, address, ticker)

        if amount_delta.startswith("-"):
            # Debit operation
            amount = amount_delta[1:]  # Remove minus sign
            if not balance.subtract_amount(amount):
                raise BRC20Exception(
                    BRC20ErrorCodes.INSUFFICIENT_BALANCE,
                    f"Insufficient balance for {operation_type}",
                )
        else:
            # Credit operation
            balance.add_amount(amount_delta)

        # Update timestamp is handled by the model

    def log_operation(
        self,
        operation_data: dict,
        validation_result: ValidationResult,
        tx_info: dict,
        raw_op_return: str,
        parsed_json: str = None,
        is_marketplace: bool = False,
    ) -> None:
        """
        Record operation with Bitcoin block timestamp

        RULES:
        - Log ALL operations (valid AND invalid)
        - ticker=NULL if parsing failed
        - Fill all fields according to operation type
        - Use standardized error codes
        """
        # is_marketplace is passed as parameter from the validation phase

        # Convert block timestamp safely
        try:
            operation_timestamp = self._convert_block_timestamp(
                self.current_block_timestamp
            )
        except ValueError as e:
            self.logger.error(
                "Failed to log operation due to timestamp error",
                txid=tx_info["txid"],
                block_height=tx_info.get("block_height", 0),
                error=str(e),
            )
            # Use current time as fallback for logging purposes only
            operation_timestamp = datetime.utcnow()

        # Get recipient address and determine from_address based on operation type
        recipient_address = None
        from_address = None
        op_type = operation_data.get("op")

        # For deploy operations, recipient is ONLY the first input address
        if op_type == "deploy":
            recipient_address = self.get_first_input_address(tx_info)
            # DEPLOY: from_address = None (tokens created from nowhere)
            from_address = None
        elif op_type == "mint":
            # For mint operations, recipient is output after OP_RETURN
            recipient_address = self.validator.get_output_after_op_return_address(
                tx_info.get("vout", [])
            )
            # MINT: from_address = None (tokens created from nowhere)
            from_address = None
        else:
            # For all other operations (TRANSFER), recipient is output after OP_RETURN
            recipient_address = self.validator.get_output_after_op_return_address(
                tx_info.get("vout", [])
            )
            # TRANSFER: apply regular rules (get actual sender address)
            from_address = self.get_first_input_address(tx_info)

        # ✅ CRITICAL: Ensure block_hash is NEVER empty - authoritative source
        operation_block_hash = tx_info.get("block_hash", "")
        if not operation_block_hash:
            # This should NEVER happen - log error but don't fail processing
            self.logger.error(
                "❌ CRITICAL: block_hash is empty during operation logging",
                txid=tx_info.get("txid", "unknown"),
                block_height=tx_info.get("block_height", 0),
                operation=operation_data.get("op", "unknown"),
            )
            # Use a placeholder to avoid empty column, this indicates a serious issue
            operation_block_hash = (
                f"MISSING_HASH_HEIGHT_{tx_info.get('block_height', 0)}"
            )

        operation = BRC20Operation(
            txid=tx_info["txid"],
            vout_index=tx_info.get("vout_index", 0),
            block_height=tx_info.get("block_height", 0),
            block_hash=operation_block_hash,  # ✅ GUARANTEED: Never empty
            tx_index=tx_info.get("tx_index", 0),
            timestamp=operation_timestamp,  # ✅ FIXED: Use Bitcoin block timestamp
            operation=operation_data.get(
                "op", "invalid"
            ),  # Default to 'invalid' for failed parsing
            ticker=operation_data.get("tick"),
            amount=operation_data.get("amt"),
            from_address=from_address,
            to_address=recipient_address,
            is_valid=validation_result.is_valid,
            error_code=(
                validation_result.error_code if not validation_result.is_valid else None
            ),
            error_message=(
                validation_result.error_message
                if not validation_result.is_valid
                else None
            ),
            raw_op_return=raw_op_return,
            parsed_json=parsed_json,
            is_marketplace=is_marketplace,
        )

        # ✅ LOG: Confirm block_hash is properly stored during DB rebuild
        self.logger.debug(
            "Operation logged with block_hash",
            txid=operation.txid,
            operation=operation.operation,
            ticker=operation.ticker,
            block_height=operation.block_height,
            block_hash=(
                operation.block_hash[:16] + "..."
                if len(operation.block_hash) > 16
                else operation.block_hash
            ),
            is_valid=operation.is_valid,
        )

        self.db.add(operation)
        self.db.flush()  # Get ID without committing

    def resolve_transfer_addresses(self, tx_info: dict) -> Dict[str, Optional[str]]:
        """
        Resolve addresses once for transfer operations
        OPTIMIZATION: Eliminates duplicate UTXO lookups

        Args:
            tx_info: Transaction information dictionary

        Returns:
            Dictionary with sender and recipient addresses
        """
        return {
            "sender": self.get_first_input_address(tx_info),
            "recipient": self.validator.get_output_after_op_return_address(
                tx_info.get("vout", [])
            ),
        }

    def validate_transfer_specific(
        self, operation: dict, tx_info: dict, transfer_type: "TransferType"
    ) -> ValidationResult:
        """
        Transfer-specific validation logic consolidated
        Includes: OP_RETURN position, marketplace rules, etc.

        Args:
            operation: Parsed BRC-20 operation
            tx_info: Transaction information
            transfer_type: Type of transfer (simple/marketplace)

        Returns:
            ValidationResult with success/failure status
        """
        from src.utils.exceptions import TransferType

        # OP_RETURN position validation based on transfer type
        if transfer_type == TransferType.MARKETPLACE:
            # Marketplace transfers can have OP_RETURN in any position
            hex_data_validated, vout_index_validated = (
                self.parser.extract_op_return_data(tx_info)
            )
        else:
            # Simple transfers must have OP_RETURN in first position
            hex_data_validated, vout_index_validated = (
                self.parser.extract_op_return_data_with_position_check(
                    tx_info, "transfer"
                )
            )

        if not hex_data_validated:
            error_message = (
                "OP_RETURN must be in first output for simple transfer operations"
            )
            if transfer_type == TransferType.MARKETPLACE:
                error_message = "OP_RETURN validation failed for marketplace transfer"

            return ValidationResult(
                False, BRC20ErrorCodes.OP_RETURN_NOT_FIRST, error_message
            )

        return ValidationResult(True)

    def validate_mint_op_return_position(
        self, tx_info: dict, block_height: int
    ) -> ValidationResult:
        """
        Validate mint OP_RETURN position based on block height

        BLOCK HEIGHT RULES:
        - BEFORE block 984444: Mint OP_RETURN can be at ANY index (flexible positioning)
        - AFTER block 984444: Mint OP_RETURN must be FIRST output (strict positioning)

        Args:
            tx_info: Transaction information
            block_height: Block height for validation

        Returns:
            ValidationResult with success/failure status
        """
        from src.config import settings

        # Before enforcement block height - flexible positioning
        if block_height < settings.MINT_OP_RETURN_POSITION_BLOCK_HEIGHT:
            # Use flexible extraction - allows any position
            hex_data_validated, vout_index_validated = (
                self.parser.extract_op_return_data(tx_info)
            )
            if not hex_data_validated:
                return ValidationResult(
                    False,
                    BRC20ErrorCodes.OP_RETURN_NOT_FOUND,
                    "OP_RETURN not found in transaction",
                )
        else:
            # After enforcement block height - strict positioning (must be first)
            hex_data_validated, vout_index_validated = (
                self.parser.extract_op_return_data_with_position_check(tx_info, "mint")
            )
            if not hex_data_validated:
                return ValidationResult(
                    False,
                    BRC20ErrorCodes.OP_RETURN_NOT_FIRST,
                    f"Mint OP_RETURN must be in first output after block "
                    f"{settings.MINT_OP_RETURN_POSITION_BLOCK_HEIGHT}",
                )

        return ValidationResult(True)
