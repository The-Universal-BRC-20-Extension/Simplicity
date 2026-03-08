"""
BRC-20 consensus rule validation service
"""

from typing import Dict, Any, Optional, List
from sqlalchemy.orm import Session
from sqlalchemy import func
from decimal import Decimal
from src.utils.exceptions import BRC20ErrorCodes, ValidationResult
from src.utils.amounts import (
    is_valid_amount,
    is_amount_greater_than,
    is_amount_greater_equal,
    add_amounts,
    subtract_amounts,
)
from src.utils.bitcoin import (
    extract_address_from_script,
    is_op_return_script,
    is_standard_output,
)
from src.models.deploy import Deploy
from src.models.balance import Balance
from src.utils.taproot_unified import (
    TapscriptTemplates,
    compute_tapleaf_hash,
    compute_merkle_root,
    compute_tweak,
    derive_output_key,
)
from src.utils.crypto import taproot_output_key_to_address


class BRC20Validator:
    """Validate operations according to consensus rules"""

    def __init__(self, db_session: Session):
        self.db = db_session

    def validate_deploy(
        self, operation: Dict[str, Any], intermediate_deploys: Optional[Dict] = None
    ) -> ValidationResult:
        ticker = operation.get("tick").upper()
        max_supply = operation.get("m")
        limit_per_op = operation.get("l")

        if intermediate_deploys is not None and ticker in intermediate_deploys:
            return ValidationResult(
                False,
                BRC20ErrorCodes.TICKER_ALREADY_EXISTS,
                f"Ticker '{ticker}' already deployed in this block",
            )

        existing_deploy = self.db.query(Deploy).filter(Deploy.ticker.ilike(ticker)).first()
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

        return ValidationResult(True)

    def validate_mint(
        self,
        operation: Dict[str, Any],
        deploy: Optional[Deploy],
        intermediate_total_minted: Optional[Dict] = None,
    ) -> ValidationResult:
        ticker = operation.get("tick")
        amount = operation.get("amt")

        if deploy is None:
            return ValidationResult(
                False,
                BRC20ErrorCodes.TICKER_NOT_DEPLOYED,
                f"Ticker '{ticker}' not deployed",
            )

        if not is_valid_amount(amount):
            return ValidationResult(False, BRC20ErrorCodes.INVALID_AMOUNT, f"Invalid mint amount: {amount}")

        if deploy.limit_per_op is not None:
            if is_amount_greater_than(amount, deploy.limit_per_op):
                return ValidationResult(
                    False,
                    BRC20ErrorCodes.EXCEEDS_MINT_LIMIT,
                    f"Mint amount {amount} exceeds limit {deploy.limit_per_op}",
                )

        overflow_result = self.validate_mint_overflow(
            ticker, amount, deploy, intermediate_total_minted=intermediate_total_minted
        )
        if not overflow_result.is_valid:
            return overflow_result

        return ValidationResult(True)

    def validate_transfer(
        self,
        operation: Dict[str, Any],
        sender_balance: str,
        deploy: Optional[Deploy] = None,
        intermediate_balances=None,
    ) -> ValidationResult:
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
        if not isinstance(tx_outputs, list) or not tx_outputs:
            return ValidationResult(
                False,
                BRC20ErrorCodes.NO_STANDARD_OUTPUT,
                "Invalid or empty transaction outputs",
            )

        if operation_type == "deploy":
            return ValidationResult(True)

        has_standard_output = any(
            out is not None
            and out.get("scriptPubKey", {}).get("type") != "nulldata"
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

    def get_output_after_op_return_address(self, tx_outputs: List[Dict[str, Any]]) -> Optional[str]:
        op_return_index = None
        for i, vout in enumerate(tx_outputs):
            if not isinstance(vout, dict):
                continue

            script_pub_key = vout.get("scriptPubKey", {})
            if not isinstance(script_pub_key, dict):
                continue

            if script_pub_key.get("type") == "nulldata" or (
                script_pub_key.get("hex", "") and script_pub_key.get("hex", "").startswith("6a")
            ):
                op_return_index = i
                break

        if op_return_index is None or op_return_index + 1 >= len(tx_outputs):
            return None

        next_output = tx_outputs[op_return_index + 1]
        if next_output is None or not isinstance(next_output, dict):
            return None

        script_pub_key = next_output.get("scriptPubKey", {})

        if script_pub_key.get("type") == "nulldata" or (
            script_pub_key.get("hex", "") and script_pub_key.get("hex", "").startswith("6a")
        ):
            return None

        addresses = script_pub_key.get("addresses", [])
        if addresses and len(addresses) > 0:
            return addresses[0]
        elif script_pub_key.get("address", None):
            return script_pub_key.get("address")
        else:
            script_hex = script_pub_key.get("hex", "")
            if script_hex and not is_op_return_script(script_hex) and is_standard_output(script_hex):
                address = extract_address_from_script(script_hex)
                if address:
                    return address

        return None

    def get_current_supply(self, ticker: str) -> Decimal:
        total = self.db.query(func.coalesce(func.sum(Balance.balance), 0)).filter(Balance.ticker.ilike(ticker)).scalar()

        return Decimal(total or 0)

    def get_total_minted(self, ticker: str, intermediate_total_minted: Optional[Dict] = None) -> Decimal:
        from src.models.transaction import BRC20Operation

        normalized_ticker = ticker.upper()

        if intermediate_total_minted is not None and normalized_ticker in intermediate_total_minted:
            return Decimal(intermediate_total_minted[normalized_ticker])

        db_total = (
            self.db.query(func.coalesce(func.sum(BRC20Operation.amount), 0))
            .filter(
                BRC20Operation.ticker.ilike(normalized_ticker),
                BRC20Operation.operation == "mint",
                BRC20Operation.is_valid.is_(True),
            )
            .scalar()
        )

        return Decimal(db_total or 0)

    def validate_mint_overflow(
        self,
        ticker: str,
        mint_amount: str,
        deploy: Deploy,
        intermediate_total_minted=None,
    ) -> ValidationResult:
        current_total_minted = self.get_total_minted(ticker, intermediate_total_minted=intermediate_total_minted)

        try:
            proposed_total_after_mint = add_amounts(current_total_minted, mint_amount)
        except ValueError as e:
            return ValidationResult(
                False,
                BRC20ErrorCodes.INVALID_AMOUNT,
                f"Amount calculation error: {str(e)}",
            )

        if is_amount_greater_than(proposed_total_after_mint, deploy.max_supply):
            excess_amount = subtract_amounts(proposed_total_after_mint, deploy.max_supply)

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

        return ValidationResult(True)

    def get_first_standard_output_address(self, tx_outputs: list) -> str | None:
        return self.get_output_after_op_return_address(tx_outputs)

    def get_balance(self, address: str, ticker: str, intermediate_balances: Optional[Dict] = None) -> Decimal:
        # CURVE: Only accept lowercase 'y' prefix for yTokens (yTOKEN, ytoken)
        if ticker and len(ticker) > 0 and ticker[0] == "y":  # Accept 'y' lowercase only
            normalized_ticker = "y" + ticker[1:].upper()
            key = (address, normalized_ticker)

            # PRIORITY 1: Check intermediate_balances first (for mutations in same block)
            if intermediate_balances is not None and key in intermediate_balances:
                return intermediate_balances[key]

            # PRIORITY 2: If pool address, calculate from active positions with rebasing
            if address.startswith("POOL::"):
                pool_id = address.replace("POOL::", "")
                result = self._calculate_pool_ytoken_balance_rebasing(pool_id, normalized_ticker)
                return result

            # PRIORITY 3: Calculate dynamically from CurveUserInfo for Curve yTokens
            staking_ticker = ticker[1:].upper()  # Extract staking_ticker (e.g., 'WTF' from 'yWTF')
            from src.models.curve import CurveConstitution, CurveUserInfo

            constitutions = self.db.query(CurveConstitution).filter_by(staking_ticker=staking_ticker).all()

            if len(constitutions) > 0:
                # Use the first constitution (or sort by start_block if multiple)
                constitution = sorted(constitutions, key=lambda c: c.start_block)[0]
                # CurveUserInfo.ticker is the reward token ticker (e.g., 'CRV'), not staking_ticker
                user_info = (
                    self.db.query(CurveUserInfo)
                    .filter_by(ticker=constitution.ticker, user_address=address)  # Use reward ticker (e.g., 'CRV')
                    .first()
                )

                if user_info:
                    RAY = Decimal("10") ** 27
                    scaled_balance = Decimal(str(user_info.scaled_balance))

                    # Just refresh to get the latest liquidity_index from the database.
                    self.db.refresh(constitution)
                    liquidity_index = Decimal(str(constitution.liquidity_index))

                    # scaled_balance and liquidity_index use RAY precision (scale=27)
                    # Formula AAVE: real_balance = (scaled_balance * liquidity_index) / RAY
                    real_balance = (scaled_balance * liquidity_index) / RAY if liquidity_index != 0 else scaled_balance

                    # Round to 8 decimals (BRC-20 precision)
                    from decimal import ROUND_DOWN

                    real_balance = real_balance.quantize(Decimal("0.00000001"), rounding=ROUND_DOWN)

                    return real_balance

            # Fallback to Balance table (shouldn't happen for valid Curve yTokens)
            balance_record = (
                self.db.query(Balance)
                .filter(Balance.address == address, Balance.ticker.ilike(normalized_ticker))
                .first()
            )
            return balance_record.balance if balance_record else Decimal("0")
        else:
            # Normal token (including YTOKEN which is rejected as yToken)
            normalized_ticker = ticker.upper() if ticker else ticker
            key = (address, normalized_ticker)

            if intermediate_balances is not None and key in intermediate_balances:
                return intermediate_balances[key]

            balance_record = (
                self.db.query(Balance)
                .filter(Balance.address == address, Balance.ticker.ilike(normalized_ticker))
                .first()
            )

            return balance_record.balance if balance_record else Decimal("0")

    def _calculate_pool_ytoken_balance_rebasing(self, pool_id: str, ytoken_ticker: str) -> Decimal:
        """
        Calculate pool balance for yToken with rebasing from active positions.

        Formula: pool_balance = SUM(amount_locked × (current_liquidity_index / liquidity_index_at_lock))

        This allows yTokens in pools to continue rebasing automatically.

        Args:
            pool_id: Pool ID (e.g., "LOL-yWTF")
            ytoken_ticker: yToken ticker (e.g., "yWTF")

        Returns:
            Total pool balance for yToken (with rebasing applied)
        """
        import structlog

        logger = structlog.get_logger()

        from src.models.swap_position import SwapPosition, SwapPositionStatus
        from src.models.curve import CurveConstitution

        # DEBUG: Log input parameters (INFO level for visibility)
        logger.info(
            "_calculate_pool_ytoken_balance_rebasing called",
            pool_id=pool_id,
            pool_id_repr=repr(pool_id),
            ytoken_ticker=ytoken_ticker,
            ytoken_ticker_repr=repr(ytoken_ticker),
            ytoken_ticker_len=len(ytoken_ticker) if ytoken_ticker else 0,
        )

        # Extract staking_ticker from yToken (e.g., "WTF" from "yWTF")
        staking_ticker = ytoken_ticker[1:]  # Remove 'y' prefix

        # Get CurveConstitution for this staking_ticker
        constitutions = self.db.query(CurveConstitution).filter_by(staking_ticker=staking_ticker).all()
        if not constitutions:
            logger.debug(
                "No CurveConstitution found",
                staking_ticker=staking_ticker,
                pool_id=pool_id,
                ytoken_ticker=ytoken_ticker,
            )
            # Not a Curve yToken, fallback to Balance table
            balance_record = (
                self.db.query(Balance)
                .filter(Balance.address == f"POOL::{pool_id}", Balance.ticker.ilike(ytoken_ticker))
                .first()
            )
            result = balance_record.balance if balance_record else Decimal("0")
            logger.debug(
                "Fallback to Balance table",
                pool_id=pool_id,
                ytoken_ticker=ytoken_ticker,
                balance_found=balance_record is not None,
                result=result,
            )
            return result

        # Use first constitution
        constitution = sorted(constitutions, key=lambda c: c.start_block)[0]

        # Get current liquidity_index
        self.db.refresh(constitution)
        current_liquidity_index = Decimal(str(constitution.liquidity_index))

        logger.info(
            "CurveConstitution found",
            staking_ticker=staking_ticker,
            constitution_ticker=constitution.ticker,
            current_liquidity_index=str(current_liquidity_index),
            pool_id=pool_id,
        )

        # DEBUG: Check all active positions in pool first (for comparison)
        all_active_positions = (
            self.db.query(SwapPosition)
            .filter(SwapPosition.pool_id == pool_id, SwapPosition.status == SwapPositionStatus.active)
            .all()
        )

        logger.info(
            "All active positions in pool",
            pool_id=pool_id,
            total_active_positions=len(all_active_positions),
            position_details=[
                {
                    "id": p.id,
                    "src_ticker": p.src_ticker,
                    "src_ticker_repr": repr(p.src_ticker),
                    "dst_ticker": p.dst_ticker,
                    "amount_locked": str(p.amount_locked),
                }
                for p in all_active_positions
            ],
        )

        # Get all active positions with src_ticker=yToken in this pool
        positions = (
            self.db.query(SwapPosition)
            .filter(
                SwapPosition.pool_id == pool_id,
                SwapPosition.src_ticker == ytoken_ticker,
                SwapPosition.status == SwapPositionStatus.active,
            )
            .all()
        )

        logger.info(
            "Positions matching yToken filter",
            pool_id=pool_id,
            ytoken_ticker=ytoken_ticker,
            ytoken_ticker_repr=repr(ytoken_ticker),
            positions_found=len(positions),
            position_ids=[p.id for p in positions],
            position_src_tickers=[p.src_ticker for p in positions],
            position_src_tickers_repr=[repr(p.src_ticker) for p in positions],
        )

        total_pool_balance = Decimal("0")

        for position in positions:
            amount_locked = Decimal(str(position.amount_locked))
            rebasing_ratio = None

            # If position has liquidity_index_at_lock, apply rebasing
            if position.liquidity_index_at_lock:
                liquidity_index_at_lock = Decimal(str(position.liquidity_index_at_lock))

                # Calculate rebasing ratio
                if liquidity_index_at_lock > 0:
                    rebasing_ratio = current_liquidity_index / liquidity_index_at_lock
                    # Apply rebasing to amount_locked
                    real_locked_balance = amount_locked * rebasing_ratio
                else:
                    # Fallback if liquidity_index_at_lock is 0 (shouldn't happen)
                    real_locked_balance = amount_locked
                    logger.warning(
                        "Position has liquidity_index_at_lock = 0",
                        position_id=position.id,
                        pool_id=pool_id,
                    )
            else:
                # Position created before OPI-002, use amount_locked as-is
                real_locked_balance = amount_locked
                logger.debug(
                    "Position without liquidity_index_at_lock (old position)",
                    position_id=position.id,
                    pool_id=pool_id,
                    amount_locked=str(amount_locked),
                )

            # Round to 8 decimals (BRC-20 precision)
            from decimal import ROUND_DOWN

            real_locked_balance = real_locked_balance.quantize(Decimal("0.00000001"), rounding=ROUND_DOWN)

            logger.debug(
                "Processing position for pool balance",
                position_id=position.id,
                amount_locked=str(amount_locked),
                liquidity_index_at_lock=(
                    str(position.liquidity_index_at_lock) if position.liquidity_index_at_lock else None
                ),
                rebasing_ratio=str(rebasing_ratio) if rebasing_ratio is not None else None,
                real_locked_balance=str(real_locked_balance),
            )

            total_pool_balance += real_locked_balance

        logger.info(
            "_calculate_pool_ytoken_balance_rebasing result",
            pool_id=pool_id,
            ytoken_ticker=ytoken_ticker,
            total_pool_balance=str(total_pool_balance),
            positions_processed=len(positions),
        )

        return total_pool_balance

    def get_deploy_record(self, ticker: str, intermediate_deploys: Optional[Dict] = None) -> Optional[Deploy]:
        """
        Retrieves deployment record. Creates a VIRTUAL DEPLOY for valid yTokens.

        This enables yTokens (rebasing derivatives) to be used in standard swap operations
        (swap.init, swap.exe) without requiring a physical Deploy record in the database.
        """
        # Preserve lowercase 'y' prefix for yTokens in normalization
        # This ensures consistency with Context.get_deploy_record() which preserves 'y' minuscule
        if ticker and len(ticker) > 0 and ticker[0].lower() == "y":
            normalized_ticker = "y" + ticker[1:].upper()  # "yWTF" → "yWTF", "YWTF" → "yWTF"
        else:
            normalized_ticker = ticker.upper()

        if intermediate_deploys is not None and normalized_ticker in intermediate_deploys:
            return intermediate_deploys[normalized_ticker]

        # Use case-insensitive search for standard tokens
        deploy = self.db.query(Deploy).filter(Deploy.ticker.ilike(normalized_ticker)).first()
        if deploy:
            return deploy

        # Convention: Starts with 'y' (lowercase) and has length > 1
        if len(normalized_ticker) > 1 and normalized_ticker.startswith("y"):
            staking_ticker = normalized_ticker[1:]  # e.g., 'yWTF' -> 'WTF'

            from src.models.curve import CurveConstitution
            from datetime import datetime, timezone

            constitution = self.db.query(CurveConstitution).filter_by(staking_ticker=staking_ticker).first()

            if constitution:
                # Create Virtual Deploy Object (Ephemeral)
                # This ensures the Deploy virtuel uses the same ticker format as Context cache
                virtual_deploy = Deploy(
                    ticker=normalized_ticker,  # "yWTF" (case preserved)
                    max_supply=Decimal("1e27"),  # Effectively Infinite
                    remaining_supply=Decimal("1e27"),
                    limit_per_op=None,
                    deploy_txid=f"VIRTUAL_YTOKEN_{staking_ticker}",  # Marker ID
                    deploy_height=constitution.start_block,
                    deploy_timestamp=datetime.now(timezone.utc),
                    deployer_address=constitution.genesis_address,
                )

                if intermediate_deploys is not None:
                    intermediate_deploys[normalized_ticker] = virtual_deploy

                return virtual_deploy

        return None

    def validate_complete_operation(
        self,
        operation: Dict[str, Any],
        tx_outputs: List[Dict[str, Any]],
        sender_address: Optional[str] = None,
        intermediate_balances: Optional[Dict] = None,
        intermediate_total_minted: Optional[Dict] = None,
        intermediate_deploys: Optional[Dict] = None,
    ) -> ValidationResult:
        op_type = operation.get("op")
        ticker = operation.get("tick")

        output_validation = self.validate_output_addresses(tx_outputs, op_type)
        if not output_validation.is_valid:
            return output_validation

        if op_type in ["mint", "transfer"]:
            recipient_address = self.get_output_after_op_return_address(tx_outputs)
            if not recipient_address:
                return ValidationResult(
                    False,
                    BRC20ErrorCodes.NO_STANDARD_OUTPUT,
                    f"No valid recipient found after OP_RETURN for {op_type} operation",
                )

        deploy = self.get_deploy_record(ticker, intermediate_deploys=intermediate_deploys)

        if op_type == "deploy":
            return self.validate_deploy(operation, intermediate_deploys=intermediate_deploys)

        elif op_type == "mint":
            return self.validate_mint(operation, deploy, intermediate_total_minted=intermediate_total_minted)

        elif op_type == "transfer":
            if sender_address is None:
                return ValidationResult(
                    False,
                    BRC20ErrorCodes.NO_STANDARD_OUTPUT,
                    "Sender address required for transfer validation",
                )

            sender_balance = self.get_balance(sender_address, ticker, intermediate_balances=intermediate_balances)
            return self.validate_transfer(
                operation,
                sender_balance,
                deploy,
                intermediate_balances=intermediate_balances,
            )

        elif op_type == "burn":
            # Standard burn validation (if needed for non-Wrap tokens)
            # Note: Wrap burns are handled separately in processor
            return ValidationResult(True)

        else:
            return ValidationResult(
                False,
                BRC20ErrorCodes.INVALID_OPERATION,
                f"Unknown operation type: {op_type}",
            )

    def validate_taproot_contract_creation(
        self,
        internal_pubkey_from_commit: bytes,
        control_blocks: List[bytes],
        contract_address: str,
        crypto_data: dict = None,
    ) -> ValidationResult:
        """Validate Taproot contract creation (8-step cryptographic validation, atomic control_blocks)."""
        try:
            # Step 0: Validate control blocks
            if len(control_blocks) != 2:
                return ValidationResult(False, BRC20ErrorCodes.INVALID_CONTROL_BLOCK, "Expected 2 control blocks")

            control_block_multisig = control_blocks[0]
            control_block_csv = control_blocks[1]

            # 0a. Validate internal key of each control block
            if len(control_block_multisig) < 33 or len(control_block_csv) < 33:
                return ValidationResult(False, BRC20ErrorCodes.INVALID_CONTROL_BLOCK, "Control blocks too short")

            internal_pubkey_from_cb_multi = control_block_multisig[1:33]
            internal_pubkey_from_cb_csv = control_block_csv[1:33]

            if (
                internal_pubkey_from_cb_multi != internal_pubkey_from_commit
                or internal_pubkey_from_cb_csv != internal_pubkey_from_commit
            ):
                return ValidationResult(
                    False, BRC20ErrorCodes.INVALID_CONTROL_BLOCK, "Internal pubkey mismatch in control blocks"
                )

            # Step 1: Rebuild script templates
            # Use validated internal key
            multisig_script = TapscriptTemplates.create_multisig_script(internal_pubkey_from_commit)
            csv_script = TapscriptTemplates.create_csv_script()

            print(f"  🔍 Debug Scripts:")
            print(f"    Multisig script: {multisig_script.hex()}")
            print(f"    CSV script: {csv_script.hex()}")
            print(f"    Expected CSV script: {crypto_data['leafs']['csv']['script']}")

            # Step 2: Compute leaf hashes
            multisig_leaf_hash = compute_tapleaf_hash(multisig_script)
            csv_leaf_hash = compute_tapleaf_hash(csv_script)

            # Step 3: Rebuild Merkle root
            # Use original order (multisig, csv) as in data
            reconstructed_merkle_root = compute_merkle_root([multisig_leaf_hash, csv_leaf_hash])

            # Step 4: Validate Merkle paths
            merkle_path_for_multisig = control_block_multisig[33:]
            print(f"  🔍 Debug Merkle validation:")
            print(f"    Multisig leaf hash: {multisig_leaf_hash.hex()}")
            print(f"    CSV leaf hash: {csv_leaf_hash.hex()}")
            print(f"    Merkle path for multisig: {merkle_path_for_multisig.hex()}")
            print(f"    Merkle path for CSV: {control_block_csv[33:].hex()}")
            print(f"    Reconstructed merkle root: {reconstructed_merkle_root.hex()}")

            if merkle_path_for_multisig != csv_leaf_hash:
                return ValidationResult(
                    False, BRC20ErrorCodes.INVALID_CONTROL_BLOCK, "Merkle path for multisig is incorrect"
                )

            merkle_path_for_csv = control_block_csv[33:]
            if merkle_path_for_csv != multisig_leaf_hash:
                return ValidationResult(
                    False, BRC20ErrorCodes.INVALID_CONTROL_BLOCK, "Merkle path for CSV is incorrect"
                )

            # Step 5: Compute tweak
            tweak = compute_tweak(internal_pubkey_from_commit, reconstructed_merkle_root)

            # Step 6: Derive output key
            result = derive_output_key(internal_pubkey_from_commit, tweak)
            if not result:
                return ValidationResult(False, BRC20ErrorCodes.INVALID_WRAP_STRUCTURE, "Failed to derive output key")

            output_key, parity = result

            # Step 7: Derive Bech32m address
            recalculated_address = taproot_output_key_to_address(output_key, parity=parity)

            # Step 8: Final check
            if recalculated_address != contract_address:
                return ValidationResult(
                    False,
                    BRC20ErrorCodes.INVALID_WRAP_STRUCTURE,
                    f"Address mismatch: expected {recalculated_address}, got {contract_address}",
                )

            # Success!
            return ValidationResult(
                True,
                additional_data={
                    "tapscript_hex": multisig_script.hex(),
                    "merkle_root": reconstructed_merkle_root.hex(),
                },
            )

        except Exception as e:
            return ValidationResult(
                False, BRC20ErrorCodes.UNKNOWN_PROCESSING_ERROR, f"Cryptographic validation failed: {e}"
            )
