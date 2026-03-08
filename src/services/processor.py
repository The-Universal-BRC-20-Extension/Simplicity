import json
import structlog
from datetime import datetime, timezone
from typing import Optional, List, Dict, Tuple, Any
from decimal import Decimal
from sqlalchemy.orm import Session
from sqlalchemy.orm.decl_api import DeclarativeMeta
from .bitcoin_rpc import BitcoinRPCService
from .parser import BRC20Parser
from .validator import BRC20Validator
from .utxo_service import UTXOResolutionService
from .wrap_validator_service import WrapValidatorService
from src.models.balance import Balance
from src.models.deploy import Deploy
from src.models.transaction import BRC20Operation
from src.utils.exceptions import (
    BRC20ErrorCodes,
    ValidationResult,
    TransferType,
    ProcessingResult,
)
from src.utils.bitcoin import (
    extract_signature_from_input,
    is_sighash_single_anyonecanpay,
    extract_address_from_script,
    is_op_return_script,
    is_standard_output,
)
from src.config import settings
from src.utils.taproot_unified import (
    TapscriptTemplates,
    compute_tapleaf_hash,
    compute_merkle_root,
    compute_tweak,
    derive_output_key,
    get_internal_pubkey_from_witness,
)
from src.utils.taproot import validate_taproot_contract
from src.utils.crypto import taproot_output_key_to_address
from src.models.extended import Extended
from src.opi.contracts import (
    IntermediateState,
    Context,
)
from src.opi.registry import OPIRegistry


class BRC20Processor:
    def __init__(self, db_session: Session, bitcoin_rpc: BitcoinRPCService):
        self.db = db_session
        self.rpc = bitcoin_rpc
        self.parser = BRC20Parser()
        self.validator = BRC20Validator(db_session)
        self.utxo_service = UTXOResolutionService(bitcoin_rpc)
        self.wrap_validator = WrapValidatorService(bitcoin_rpc)
        self.logger = structlog.get_logger()
        self.current_block_timestamp = None
        self.opi_registry: Optional[OPIRegistry] = None

    def extract_address_from_output(self, vout: Dict[str, Any]) -> Optional[str]:
        """Extract address from a transaction output"""
        if not isinstance(vout, dict):
            return None

        script_pub_key = vout.get("scriptPubKey", {})
        if not isinstance(script_pub_key, dict):
            return None

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

    def _convert_block_timestamp(self, block_timestamp: int) -> datetime:
        if not isinstance(block_timestamp, int) or block_timestamp <= 0:
            raise ValueError(f"Invalid block timestamp: {block_timestamp}")
        return datetime.fromtimestamp(block_timestamp, tz=timezone.utc)

    def process_transaction(
        self,
        tx: dict,
        block_height: int,
        tx_index: int,
        block_timestamp: int,
        block_hash: str,
        intermediate_state=None,
    ) -> Tuple[ProcessingResult, List[DeclarativeMeta], List[Any]]:
        if intermediate_state is None:
            intermediate_state = IntermediateState()

        # Initialize operations_to_persist to collect all operations
        # This ensures operations are persisted even if errors occur later
        operations_to_persist = []

        multi_transfer_ops = self.parser.extract_multi_transfer_op_returns(tx)
        if len(multi_transfer_ops) > 1:
            result, objects_to_persist, state_commands = self.process_multi_transfer(
                tx,
                block_height,
                tx_index,
                block_timestamp,
                block_hash,
                multi_transfer_ops,
                intermediate_state,
            )
            return result, objects_to_persist, state_commands

        result = ProcessingResult()
        result.txid = tx.get("txid", "unknown")
        hex_data, vout_index = self.parser.extract_op_return_data(tx)
        if not hex_data:
            return result, operations_to_persist, []
        if vout_index is None:
            vout_index = 0

        # Parse as BRC-20 operation (includes wmint and wrap_burn)
        parse_result = self.parser.parse_brc20_operation(hex_data)

        if not parse_result["success"]:
            if parse_result.get("error_code") != BRC20ErrorCodes.INVALID_JSON:
                tx.update(
                    {
                        "block_height": block_height,
                        "tx_index": tx_index,
                        "block_hash": block_hash,
                        "vout_index": vout_index,
                    }
                )
                self.current_block_timestamp = block_timestamp
                op = self.log_operation(
                    op_data={"op": "invalid"},
                    val_res=ValidationResult(
                        False,
                        parse_result.get("error_code"),
                        parse_result.get("error_message"),
                    ),
                    tx_info=tx,
                    raw_op=hex_data,
                )
                operations_to_persist.append(op)
            return result, operations_to_persist, []
        try:
            tx.update(
                {
                    "block_height": block_height,
                    "tx_index": tx_index,
                    "block_hash": block_hash,
                    "vout_index": vout_index,
                }
            )
            self.current_block_timestamp = block_timestamp
            result.operation_found = True
            operation_data = parse_result["data"]
            if operation_data.get("tick"):
                tick = operation_data["tick"]
                # Preserve lowercase 'y' prefix for yTokens
                # Only Curve staking can create tokens with 'y' prefix
                if tick and len(tick) > 0 and tick[0].lower() == "y":
                    # Preserve 'y' lowercase, uppercase the rest
                    operation_data["tick"] = "y" + tick[1:].upper()
                else:
                    operation_data["tick"] = tick.upper()
            op_type = operation_data.get("op")
            is_marketplace = False
            is_stones_mint = False

            if op_type == "transfer":
                # Check emergency range first (fast check)
                start_block = settings.EMERGENCY_MARKETPLACE_SENDER_START_BLOCK
                end_block = settings.EMERGENCY_MARKETPLACE_SENDER_END_BLOCK
                is_in_emergency_range = (
                    start_block is not None and end_block is not None and start_block <= block_height <= end_block
                )

                if is_in_emergency_range:
                    transfer_type_check = self.classify_transfer_type(tx, block_height)
                    is_marketplace_for_sender = (
                        transfer_type_check == TransferType.MARKETPLACE
                        or transfer_type_check == TransferType.INVALID_MARKETPLACE
                    )
                    is_marketplace = transfer_type_check == TransferType.MARKETPLACE

                    if is_marketplace_for_sender:
                        sender_address = self.get_second_input_address(tx)
                        if not sender_address:
                            sender_address = self.get_first_input_address(tx)
                    else:
                        sender_address = self.get_first_input_address(tx)
                else:
                    sender_address = self.get_first_input_address(tx)
            else:
                sender_address = self.get_first_input_address(tx)

            tx_info = {
                "txid": tx.get("txid"),
                "block_height": block_height,
                "block_hash": block_hash,
                "tx_index": tx_index,
                "vout_index": vout_index,
                "block_timestamp": block_timestamp,
                "sender_address": sender_address,
                "raw_op_return": hex_data,
                "vout": tx.get(
                    "vout", []
                ),  # Include vout for OPI processors (e.g., Curve staking needs Genesis Fee validation)
            }

            # OPI dispatch for non-core operations (e.g., swap)
            if self.opi_registry and op_type not in ["deploy", "mint", "transfer", "burn"]:
                try:
                    context = Context(intermediate_state, self.validator)
                    processor = self.opi_registry.get_processor(op_type, context)
                    if processor is not None:
                        processing_result, state = processor.process_op(operation_data, tx_info)

                        # Apply state mutations
                        # If an exception occurs, we need to mark any existing operation as invalid
                        # to avoid duplicate key violations
                        try:
                            for mutate in state.state_mutations:
                                try:
                                    mutate(intermediate_state)
                                except Exception as e:
                                    self.logger.error("State mutation failed in OPI", op=op_type, error=str(e))
                                    # Mark any existing operation as invalid before re-raising
                                    txid = tx_info.get("txid", "unknown")
                                    vout_index = tx_info.get("vout_index", 0)
                                    for obj in state.orm_objects:
                                        if (
                                            isinstance(obj, BRC20Operation)
                                            and obj.txid == txid
                                            and obj.vout_index == vout_index
                                        ):
                                            obj.is_valid = False
                                            obj.error_code = BRC20ErrorCodes.UNKNOWN_PROCESSING_ERROR
                                            obj.error_message = f"State mutation failed: {str(e)}"
                                            # Return the modified state to avoid duplicate
                                            return (
                                                ProcessingResult(
                                                    operation_found=True,
                                                    is_valid=False,
                                                    error_code=BRC20ErrorCodes.UNKNOWN_PROCESSING_ERROR,
                                                    error_message=f"State mutation failed: {str(e)}",
                                                ),
                                                state.orm_objects,
                                                [],
                                            )
                                    raise
                        except Exception as e:
                            # If exception wasn't handled above, re-raise it
                            raise

                        # Persist ORM objects via caller's buffer (return in tuple)
                        return processing_result, state.orm_objects, state.state_mutations
                    else:
                        # Processor not found - log invalid operation
                        self.logger.warning("OPI processor not found", op=op_type)
                        operation_record = BRC20Operation(
                            txid=tx_info.get("txid", "unknown"),
                            vout_index=tx_info.get("vout_index", 0),
                            operation=op_type,
                            ticker=None,
                            amount=None,
                            from_address=tx_info.get("sender_address"),
                            to_address=None,
                            block_height=tx_info.get("block_height", 0),
                            block_hash=tx_info.get("block_hash", ""),
                            tx_index=tx_info.get("tx_index", 0),
                            timestamp=(
                                datetime.fromtimestamp(tx_info.get("block_timestamp", 0), tz=timezone.utc)
                                if tx_info.get("block_timestamp")
                                else None
                            ),
                            is_valid=False,
                            error_code=BRC20ErrorCodes.INVALID_OPERATION,
                            error_message=f"OPI processor not found for operation: {op_type}",
                            raw_op_return=tx_info.get("raw_op_return", ""),
                            parsed_json=json.dumps(operation_data) if operation_data else None,
                            is_marketplace=False,
                            is_multi_transfer=False,
                        )
                        return (
                            ProcessingResult(
                                operation_found=True,
                                is_valid=False,
                                error_code=BRC20ErrorCodes.INVALID_OPERATION,
                                error_message=f"OPI processor not found for operation: {op_type}",
                            ),
                            [operation_record],
                            [],
                        )
                except Exception as e:
                    self.logger.error("OPI processing failed", op=op_type, error=str(e), exc_info=True)
                    # Create invalid operation record for logging
                    operation_record = BRC20Operation(
                        txid=tx_info.get("txid", "unknown"),
                        vout_index=tx_info.get("vout_index", 0),
                        operation=op_type,
                        ticker=None,
                        amount=None,
                        from_address=tx_info.get("sender_address"),
                        to_address=None,
                        block_height=tx_info.get("block_height", 0),
                        block_hash=tx_info.get("block_hash", ""),
                        tx_index=tx_info.get("tx_index", 0),
                        timestamp=(
                            datetime.fromtimestamp(tx_info.get("block_timestamp", 0), tz=timezone.utc)
                            if tx_info.get("block_timestamp")
                            else None
                        ),
                        is_valid=False,
                        error_code=BRC20ErrorCodes.UNKNOWN_PROCESSING_ERROR,
                        error_message=f"OPI processing failed: {str(e)}",
                        raw_op_return=tx_info.get("raw_op_return", ""),
                        parsed_json=json.dumps(operation_data) if operation_data else None,
                        is_marketplace=False,
                        is_multi_transfer=False,
                    )
                    return (
                        ProcessingResult(
                            operation_found=True,
                            is_valid=False,
                            error_code=BRC20ErrorCodes.UNKNOWN_PROCESSING_ERROR,
                            error_message=f"OPI processing failed: {str(e)}",
                        ),
                        [operation_record],
                        [],
                    )

            # Initialize validation_result to avoid UnboundLocalError
            # Default to invalid operation if op_type is not in standard operations
            validation_result = ValidationResult(
                False, BRC20ErrorCodes.INVALID_OPERATION, f"Unknown operation type: {op_type}"
            )

            if op_type in ["deploy", "mint", "transfer", "burn"]:
                # Check if this is a STONES mint (detected by hex starting with "5d")
                # Payload is unreadable, so we identify by hex prefix only
                is_stones_mint = hex_data.lower().startswith("5d") if hex_data else False

                # Check if this is a Wrap Token operation (max_supply=0 AND limit_per_op=0)
                is_wrap_token = False
                if op_type in ["mint", "burn"] and not is_stones_mint:
                    ticker = operation_data.get("tick")
                    # Use get_deploy_record to check both intermediate_state and database
                    deploy = self.validator.get_deploy_record(ticker, intermediate_deploys=intermediate_state.deploys)
                    if deploy and (deploy.max_supply == 0 and deploy.limit_per_op == 0):
                        is_wrap_token = True

                # Bypass validation for STONES mint
                if is_stones_mint:
                    # Check activation height BEFORE processing
                    if block_height < settings.STONES_ACTIVATION_HEIGHT:
                        # Silently ignore STONES mints before activation - return early without logging
                        # result.operation_found is False by default, so operation won't be logged
                        return result, [], []
                    # Use dedicated process_stones_mint
                    validation_result = ValidationResult(True)
                elif is_wrap_token:
                    # Use dedicated Wrap services
                    if op_type == "mint":
                        validation_result = self._process_wrap_mint(
                            operation_data,
                            tx,
                            intermediate_state=intermediate_state,
                        )
                    elif op_type == "burn":
                        validation_result = self._process_wrap_burn(
                            operation_data,
                            tx,
                            intermediate_state=intermediate_state,
                        )
                    # If is_wrap_token is True but op_type is neither "mint" nor "burn",
                    # validation_result remains as invalid (initialized above)
                else:
                    # Use traditional validation for all other operations
                    validation_result = self.validator.validate_complete_operation(
                        operation_data,
                        tx.get("vout", []),
                        sender_address,
                        intermediate_balances=intermediate_state.balances,
                        intermediate_total_minted=intermediate_state.total_minted,
                        intermediate_deploys=intermediate_state.deploys,
                    )

                if validation_result.is_valid:
                    if op_type == "deploy":
                        self.process_deploy(operation_data, tx, intermediate_deploys=intermediate_state.deploys)
                    elif op_type == "mint":
                        # Check STONES mint
                        if is_stones_mint:
                            validation_result = self.process_stones_mint(
                                operation_data,
                                tx,
                                vout_index,
                                intermediate_state=intermediate_state,
                            )
                        # Regular mint processing (non-Wrap tokens)
                        elif not is_wrap_token:
                            self.process_mint(
                                operation_data,
                                tx,
                                intermediate_state=intermediate_state,
                            )
                    elif op_type == "transfer":
                        transfer_type_check = self.classify_transfer_type(tx, block_height)
                        if transfer_type_check == TransferType.MARKETPLACE:
                            is_marketplace = True
                        validation_result = self.process_transfer(
                            operation_data,
                            tx,
                            validation_result,
                            hex_data,
                            block_height,
                            intermediate_state=intermediate_state,
                        )
                    elif op_type == "burn":
                        # Check if this is a wrap burn (tick="W")
                        if operation_data.get("tick") == "W":
                            validation_result = self._process_wrap_burn(
                                operation_data,
                                tx,
                                intermediate_state=intermediate_state,
                            )
                        else:
                            # Standard burn processing (if implemented)
                            pass

                # Handle wrap operations result
                if (op_type == "mint" and operation_data.get("tick") == "W") or (
                    op_type == "burn" and operation_data.get("tick") == "W"
                ):
                    result.is_valid = validation_result.is_valid
                    result.error_code = validation_result.error_code
                    result.error_message = validation_result.error_message
                    result.operation_type = op_type
                    result.ticker = operation_data.get("tick")
                    result.amount = operation_data.get("amt")

                    # Enhanced logging for wrap operations
                    if op_type == "mint" and operation_data.get("tick") == "W":
                        # For wrap mint: from_address = null, to_address = OUTPUT[1] (receiver)
                        from_addr = None  # No from_address for mint
                        to_addr = self.validator.get_output_after_op_return_address(
                            tx.get("vout", [])
                        )  # OUTPUT[1] receives tokens
                    elif op_type == "burn" and operation_data.get("tick") == "W":
                        # For wrap burn: from_address = burner, to_address = None (burn)
                        from_addr = self.get_first_input_address(tx)
                        to_addr = None
                    else:
                        from_addr = None
                        to_addr = None

                    # Create enhanced operation data for logging
                    enhanced_op_data = operation_data.copy()
                    if op_type == "mint" and operation_data.get("tick") == "W":
                        script_addr = None
                        if len(tx.get("vout", [])) > 2:
                            script_addr = self.extract_address_from_output(tx.get("vout", [])[2])
                        initiator_addr = self.get_first_input_address(tx)
                        enhanced_op_data["script_address"] = script_addr
                        enhanced_op_data["initiator_address"] = initiator_addr
                    elif op_type == "burn" and operation_data.get("tick") == "W":
                        enhanced_op_data["burner_address"] = from_addr

                    op = self.log_operation(
                        op_data=enhanced_op_data,
                        val_res=validation_result,
                        tx_info=tx,
                        raw_op=hex_data,
                        json_op=json.dumps(enhanced_op_data),
                        is_mkt=False,
                        from_address=from_addr,
                        to_address=to_addr,
                    )
                    operations_to_persist.append(op)

                    return result, operations_to_persist, []

            result.is_valid = validation_result.is_valid
            result.error_code = validation_result.error_code
            result.error_message = validation_result.error_message
            result.operation_type = op_type
            result.ticker = operation_data.get("tick")
            result.amount = operation_data.get("amt")

            # Standard logging for regular operations
            if hex_data.lower().startswith("5d"):
                from_addr = None
                vouts = tx.get("vout", [])
                if len(vouts) > 0:
                    to_addr = self.extract_address_from_output(vouts[0])
                if not to_addr and vout_index is not None:
                    next_index = vout_index + 1
                    if next_index < len(vouts):
                        to_addr = self.extract_address_from_output(vouts[next_index])
            else:
                is_marketplace_for_sender = False
                if op_type == "transfer":
                    transfer_type_check = self.classify_transfer_type(tx, block_height)
                    is_marketplace_for_sender = (
                        transfer_type_check == TransferType.MARKETPLACE
                        or transfer_type_check == TransferType.INVALID_MARKETPLACE
                    )

                if op_type == "transfer" and is_marketplace_for_sender:
                    start_block = settings.EMERGENCY_MARKETPLACE_SENDER_START_BLOCK
                    end_block = settings.EMERGENCY_MARKETPLACE_SENDER_END_BLOCK
                    if start_block is not None and end_block is not None:
                        is_in_emergency_range = start_block <= block_height <= end_block
                        if is_in_emergency_range:
                            from_addr = self.get_second_input_address(tx)
                            if not from_addr:
                                self.logger.warning(
                                    "Emergency range marketplace transfer: INPUT[1] address not found, falling back to INPUT[0]",
                                    txid=tx.get("txid"),
                                    block_height=block_height,
                                )
                                from_addr = self.get_first_input_address(tx)
                        else:
                            from_addr = self.get_first_input_address(tx)
                    else:
                        from_addr = self.get_first_input_address(tx)
                else:
                    from_addr = self.get_first_input_address(tx)
                to_addr = self.validator.get_output_after_op_return_address(tx.get("vout", []))

            # Initialize is_marketplace for non-transfer operations
            if op_type != "transfer":
                is_marketplace = False

            op = self.log_operation(
                op_data=operation_data,
                val_res=validation_result,
                tx_info=tx,
                raw_op=hex_data,
                json_op=json.dumps(operation_data),
                is_mkt=is_marketplace,
                from_address=from_addr,
                to_address=to_addr,
            )
            operations_to_persist.append(op)

            return result, operations_to_persist, []

        except Exception as e:
            error_str = str(e)

            from sqlalchemy.exc import OperationalError, DisconnectionError

            is_session_invalid = (
                isinstance(e, (OperationalError, DisconnectionError))
                or "Can't reconnect until invalid transaction is rolled back" in error_str
                or "SSL connection has been closed" in error_str
                or "connection was closed" in error_str
                or "server closed the connection" in error_str
                or "connection timeout" in error_str
                or "OperationalError" in error_str
                or "DisconnectionError" in error_str
                or "connection was aborted" in error_str
                or "connection reset by peer" in error_str
            )

            if is_session_invalid:
                self.logger.warning(
                    "Session invalidated in BRC20Processor - re-raising for retry",
                    txid=result.txid,
                    error=error_str[:200],
                )
                raise

            self.logger.error(
                "Unhandled exception in BRC20Processor",
                txid=result.txid,
                error=error_str,
                exc_info=True,
            )
            result.is_valid = False
            result.error_code = "UNHANDLED_EXCEPTION"
            result.error_message = error_str
            return result, [], []

    def process_deploy(
        self,
        operation: dict,
        tx_info: dict,
        intermediate_deploys: Optional[Dict] = None,
    ):
        from decimal import Decimal
        from src.models.curve import CurveConstitution
        from src.utils.exceptions import BRC20ErrorCodes

        # Block deploys with 'y' prefix (reserved for Curve yTokens)
        ticker_raw = operation.get("tick", "")
        if ticker_raw and len(ticker_raw) > 0 and ticker_raw[0].lower() == "y":
            self.logger.error(
                "Deploy with 'y' prefix is reserved for Curve yTokens - REJECTING",
                ticker=ticker_raw,
                txid=tx_info["txid"],
            )
            return  # Reject before Deploy creation

        curve_data = operation.get("curve")
        is_curve_deploy = bool(curve_data)

        # If Curve deploy, validate BEFORE creating Deploy
        if is_curve_deploy:
            # Validate curve structure
            curve_type = curve_data.get("type")
            if curve_type not in ["linear", "exponential"]:
                self.logger.error(
                    "Invalid curve type for Curve deploy - REJECTING",
                    ticker=operation["tick"].upper(),
                    curve_type=curve_type,
                    txid=tx_info["txid"],
                )
                return  # Reject before Deploy creation

            lock_duration = int(curve_data.get("lock", 0))
            if lock_duration <= 0:
                self.logger.error(
                    "Invalid lock duration for Curve deploy - REJECTING",
                    ticker=operation["tick"].upper(),
                    lock_duration=lock_duration,
                    txid=tx_info["txid"],
                )
                return  # Reject before Deploy creation

            stakes = curve_data.get("stakes", [])
            if not stakes or not isinstance(stakes, list) or len(stakes) == 0:
                self.logger.error(
                    "Invalid stakes whitelist for Curve deploy - REJECTING",
                    ticker=operation["tick"].upper(),
                    stakes=stakes,
                    txid=tx_info["txid"],
                )
                return  # Reject before Deploy creation

            staking_ticker = stakes[0].upper()  # V1: Only first ticker supported

            # Extract Genesis Address (same as deployer_address)
            genesis_address = self.get_first_input_address(tx_info)
            if not genesis_address:
                self.logger.error(
                    "Missing deployer_address (Genesis Address) - REJECTING",
                    ticker=operation["tick"].upper(),
                    txid=tx_info["txid"],
                )
                return

            # Find OP_RETURN output first
            vouts = tx_info.get("vout", [])
            op_return_index = self._find_op_return_index(vouts)

            if op_return_index is None:
                self.logger.error(
                    "OP_RETURN output not found - REJECTING",
                    ticker=operation["tick"].upper(),
                    vout_count=len(vouts),
                    txid=tx_info["txid"],
                )
                return

            genesis_fee_init_index = op_return_index + 1
            genesis_fee_exe_index = op_return_index + 2

            if len(vouts) < genesis_fee_exe_index + 1:
                self.logger.error(
                    "Missing Genesis Fee outputs - REJECTING",
                    ticker=operation["tick"].upper(),
                    vout_count=len(vouts),
                    required=genesis_fee_exe_index + 1,
                    txid=tx_info["txid"],
                )
                return

            # Extract Genesis Fees (with validation)
            try:
                genesis_fee_init_output = vouts[genesis_fee_init_index]
                output1_value_btc = Decimal(str(genesis_fee_init_output.get("value", 0)))
                genesis_fee_init_sats = int(output1_value_btc * Decimal("100000000"))
                output1_address = self.extract_address_from_output(genesis_fee_init_output)

                if output1_address != genesis_address:
                    self.logger.error(
                        "Genesis Fee Init output does not go to Genesis Address - REJECTING",
                        ticker=operation["tick"].upper(),
                        expected=genesis_address,
                        found=output1_address,
                        txid=tx_info["txid"],
                    )
                    return

                genesis_fee_exe_output = vouts[genesis_fee_exe_index]
                output2_value_btc = Decimal(str(genesis_fee_exe_output.get("value", 0)))
                genesis_fee_exe_sats = int(output2_value_btc * Decimal("100000000"))
                output2_address = self.extract_address_from_output(genesis_fee_exe_output)

                if output2_address != genesis_address:
                    self.logger.error(
                        "Genesis Fee Exe output does not go to Genesis Address - REJECTING",
                        ticker=operation["tick"].upper(),
                        expected=genesis_address,
                        found=output2_address,
                        txid=tx_info["txid"],
                    )
                    return
            except (IndexError, KeyError, ValueError, TypeError) as e:
                self.logger.error(
                    "Error extracting Genesis Fees - REJECTING",
                    ticker=operation["tick"].upper(),
                    error=str(e),
                    txid=tx_info["txid"],
                    exc_info=True,
                )
                return

            operation_max_supply = Decimal(str(operation["m"]))
            if operation_max_supply <= 0:
                self.logger.error(
                    "Invalid max_supply for Curve deploy - REJECTING",
                    ticker=operation["tick"].upper(),
                    max_supply=operation_max_supply,
                    txid=tx_info["txid"],
                )
                return  # Reject before Deploy creation

            # All Curve validations passed, create Deploy + CurveConstitution atomically
            deploy = Deploy(
                ticker=operation["tick"].upper(),
                max_supply=operation["m"],
                remaining_supply=operation["m"],
                limit_per_op=operation.get("l"),
                deploy_txid=tx_info["txid"],
                deploy_height=tx_info["block_height"],
                deploy_timestamp=self._convert_block_timestamp(self.current_block_timestamp),
                deployer_address=genesis_address,
            )

            staking_deploy = self.db.query(Deploy).filter_by(ticker=staking_ticker).first()
            max_stake_supply = None
            rho_g = None
            if staking_deploy:
                max_stake_supply = Decimal(str(staking_deploy.max_supply))
                rho_g = operation_max_supply / max_stake_supply if max_stake_supply > 0 else None

            # Initialize liquidity_index to 1e27 (RAY precision, represents 1.0)
            RAY = Decimal("10") ** 27

            constitution = CurveConstitution(
                ticker=deploy.ticker,
                deploy_txid=tx_info["txid"],
                curve_type=curve_type,
                lock_duration=lock_duration,
                staking_ticker=staking_ticker,
                max_supply=operation_max_supply,
                max_stake_supply=max_stake_supply,
                rho_g=rho_g,
                genesis_fee_init_sats=genesis_fee_init_sats,
                genesis_fee_exe_sats=genesis_fee_exe_sats,
                genesis_address=genesis_address,
                start_block=tx_info["block_height"],
                last_reward_block=tx_info["block_height"],
                liquidity_index=RAY,  # Initialize to 1e27 (1.0 in RAY precision)
                total_staked=Decimal("0"),
                total_scaled_staked=Decimal("0"),
            )

            # Sanity check: ensure consistency (both come from operation["m"], should always match)
            deploy_max_supply = Decimal(str(deploy.max_supply))
            constitution_max_supply = Decimal(str(constitution.max_supply))
            assert deploy_max_supply == constitution_max_supply, (
                f"Internal consistency error: deploy.max_supply={deploy_max_supply} != "
                f"constitution.max_supply={constitution_max_supply} for ticker={deploy.ticker}"
            )

            self.db.add(deploy)
            self.db.add(constitution)
            if intermediate_deploys is not None:
                intermediate_deploys[deploy.ticker] = deploy

            self.logger.info(
                "Curve Constitution deployed",
                ticker=deploy.ticker,
                curve_type=curve_type,
                lock_duration=lock_duration,
                staking_ticker=staking_ticker,
                genesis_fee_init=genesis_fee_init_sats,
                genesis_fee_exe=genesis_fee_exe_sats,
                txid=tx_info["txid"],
            )
        else:
            # Standard BRC-20 deploy (no Curve)
            deploy = Deploy(
                ticker=operation["tick"].upper(),
                max_supply=operation["m"],
                remaining_supply=operation["m"],
                limit_per_op=operation.get("l"),
                deploy_txid=tx_info["txid"],
                deploy_height=tx_info["block_height"],
                deploy_timestamp=self._convert_block_timestamp(self.current_block_timestamp),
                deployer_address=self.get_first_input_address(tx_info),
            )
            self.db.add(deploy)
            if intermediate_deploys is not None:
                intermediate_deploys[deploy.ticker] = deploy

    def process_mint(
        self,
        operation: dict,
        tx_info: dict,
        intermediate_state: IntermediateState,
    ):
        ticker = operation["tick"].upper()

        # Block mints for Curve reward tokens
        # Curve reward tokens can only be minted via Curve claiming (swap.exe), not via standard BRC-20 mint operations
        from src.models.curve import CurveConstitution

        curve_constitution = self.db.query(CurveConstitution).filter_by(ticker=ticker).first()
        if curve_constitution:
            self.logger.error(
                "Mint operation rejected for Curve reward token - CRV tokens can only be minted via Curve claiming",
                ticker=ticker,
                txid=tx_info["txid"],
                block_height=tx_info.get("block_height"),
            )
            return ValidationResult(
                False,
                BRC20ErrorCodes.INVALID_OPERATION,
                f"Mint operation not allowed for Curve reward token: {ticker}. CRV tokens can only be minted via Curve claiming (swap.exe)",
            )

        amount = operation["amt"]
        recipient = self.validator.get_output_after_op_return_address(tx_info.get("vout", []))

        deploy = self.validator.get_deploy_record(ticker, intermediate_deploys=intermediate_state.deploys)
        validation_result = self.validator.validate_mint(
            operation, deploy, intermediate_total_minted=intermediate_state.total_minted
        )

        if validation_result.is_valid:
            from src.utils.amounts import add_amounts

            current_minted = self.validator.get_total_minted(ticker, intermediate_state.total_minted)
            intermediate_state.total_minted[ticker] = add_amounts(current_minted, amount)

            if recipient:
                mint_success = self.update_balance(
                    address=recipient,
                    ticker=ticker,
                    amount_delta=amount,
                    op_type="mint",
                    txid=tx_info["txid"],
                    intermediate_state=intermediate_state,
                )

                if not mint_success:
                    self.logger.error(
                        f"Failed to credit recipient balance for mint",
                        recipient=recipient,
                        ticker=ticker,
                        amount=amount,
                        txid=tx_info["txid"],
                    )
                    return ValidationResult(
                        False,
                        BRC20ErrorCodes.INSUFFICIENT_BALANCE,
                        f"Failed to process mint operation",
                    )
        return validation_result

    def process_stones_mint(
        self,
        operation: dict,
        tx_info: dict,
        vout_index: int,
        intermediate_state: IntermediateState,
    ) -> ValidationResult:
        """
        Process STONES mint operation with special rules:
        - from_address = null
        - to_address = vout[0] si possible, sinon vout[op_return_index + 1]
        - tick = 'STONES'
        - amt = 1
        - operation = 'mint'
        """
        # Check activation height (EARLY CHECK - before any other processing)
        block_height = tx_info.get("block_height", 0)
        if block_height < settings.STONES_ACTIVATION_HEIGHT:
            # Ignore silently and continue processing (no logging)
            return ValidationResult(True)

        ticker = "STONES"
        amount = "1"  # Always 1 for STONES mint

        # Determine recipient address: vout[op_return_index + 1] if exists, else vout[0] (OUTPUT 0)
        vouts = tx_info.get("vout", [])
        recipient = None

        # Try vout[op_return_index + 1] first (output after OP_RETURN)
        if vout_index is not None:
            next_index = vout_index + 1
            if next_index < len(vouts):
                recipient = self.extract_address_from_output(vouts[next_index])

        # If no output after OP_RETURN or not valid, use vout[0] (OUTPUT 0) as fallback
        if not recipient and len(vouts) > 0:
            recipient = self.extract_address_from_output(vouts[0])

        if not recipient:
            self.logger.warning(
                "STONES mint: No valid recipient found, using OUTPUT 0 as fallback",
                txid=tx_info.get("txid"),
                vout_index=vout_index,
                vout_count=len(vouts),
            )
            # Use OUTPUT 0 even if extract_address_from_output failed
            if len(vouts) > 0:
                # Try to extract address from vout[0] even if it's OP_RETURN
                vout0 = vouts[0]
                script_pubkey = vout0.get("scriptPubKey", {}) if isinstance(vout0, dict) else {}
                addresses = script_pubkey.get("addresses", [])
                if addresses and len(addresses) > 0:
                    recipient = addresses[0]
                elif script_pubkey.get("address"):
                    recipient = script_pubkey.get("address")

        if not recipient:
            self.logger.warning(
                "STONES mint: No valid recipient found - operation will be logged but STONES not allocated",
                txid=tx_info.get("txid"),
                vout_index=vout_index,
                vout_count=len(vouts),
            )
            return ValidationResult(
                False,
                BRC20ErrorCodes.NO_STANDARD_OUTPUT,
                "STONES mint: No valid recipient address found - STONES not allocated",
            )

        from src.utils.amounts import add_amounts

        # Update total minted
        current_minted = self.validator.get_total_minted(ticker, intermediate_state.total_minted)
        intermediate_state.total_minted[ticker] = add_amounts(current_minted, amount)

        # Update balance
        mint_success = self.update_balance(
            address=recipient,
            ticker=ticker,
            amount_delta=amount,
            op_type="mint_stones",
            txid=tx_info["txid"],
            intermediate_state=intermediate_state,
        )

        if not mint_success:
            self.logger.error(
                "Failed to credit recipient balance for STONES mint",
                recipient=recipient,
                ticker=ticker,
                amount=amount,
                txid=tx_info["txid"],
            )
            return ValidationResult(
                False,
                BRC20ErrorCodes.INSUFFICIENT_BALANCE,
                "Failed to process STONES mint operation",
            )

        self.logger.info(
            "STONES mint processed",
            recipient=recipient,
            amount=amount,
            txid=tx_info["txid"],
        )

        return ValidationResult(True)

    def process_transfer(
        self,
        operation: dict,
        tx_info: dict,
        validation_result: ValidationResult,
        hex_data: str,
        block_height: int,
        intermediate_state: IntermediateState,
    ) -> ValidationResult:
        transfer_type = self.classify_transfer_type(tx_info, block_height)

        if transfer_type == TransferType.INVALID_MARKETPLACE:
            return ValidationResult(
                False,
                BRC20ErrorCodes.INVALID_MARKETPLACE_TRANSACTION,
                "Transaction has a marketplace SIGHASH but does not conform to a valid template.",
            )

        if not validation_result.is_valid:
            return validation_result

        ticker = operation["tick"].upper()

        # OPI-2 Curve Extension imports
        # NOTE: Decimal is already imported at file level (line 5)
        from src.services.curve_service import CurveService

        # OPI-2 Curve Extension: Intercept yToken transfers
        # Detect yToken (case-insensitive: 'y' or 'Y' prefix)
        if ticker and len(ticker) > 0 and ticker[0].upper() == "Y":
            # Import CurveConstitution for query
            from src.models.curve import CurveConstitution

            staking_ticker = ticker[1:].upper()  # Remove 'y'/'Y' prefix (e.g., "yWTF" -> "WTF", "YWTF" -> "WTF")

            # Find CurveConstitution(s) that use this staking_ticker
            constitutions = self.db.query(CurveConstitution).filter_by(staking_ticker=staking_ticker).all()

            # Apply FIRST IS FIRST rule
            if len(constitutions) == 0:
                # Not a Curve yToken, continue with standard transfer
                self.logger.debug(
                    "yToken not associated with any Curve program",
                    ytoken_ticker=ticker,
                    staking_ticker=staking_ticker,
                    txid=tx_info.get("txid"),
                )
                # Continue with standard transfer
            else:
                if len(constitutions) > 1:
                    constitutions_sorted = sorted(
                        constitutions, key=lambda c: (c.start_block, c.deploy_txid)  # Sort by block, then txid
                    )
                    constitution = constitutions_sorted[0]  # FIRST deployed

                    self.logger.warning(
                        "Multiple Curve programs use same staking_ticker - using FIRST IS FIRST",
                        ytoken_ticker=ticker,
                        staking_ticker=staking_ticker,
                        constitution_count=len(constitutions),
                        selected_reward_ticker=constitution.ticker,
                        all_reward_tickers=[c.ticker for c in constitutions],
                        selected_deploy_txid=constitution.deploy_txid,
                        selected_start_block=constitution.start_block,
                        txid=tx_info.get("txid"),
                    )

                    reward_ticker = constitution.ticker
                else:
                    # Exactly one Curve program found
                    constitution = constitutions[0]
                    reward_ticker = constitution.ticker

                # Extract addresses
                sender_address = self.get_first_input_address(tx_info)
                recipient_address = self.validator.get_output_after_op_return_address(tx_info.get("vout", []))

                if not sender_address or not recipient_address:
                    self.logger.error(
                        "CRITICAL: Missing addresses for Curve yToken transfer - REJECTING",
                        ytoken_ticker=ticker,
                        reward_ticker=reward_ticker,
                        sender=sender_address,
                        recipient=recipient_address,
                        txid=tx_info.get("txid"),
                    )
                    return ValidationResult(
                        False,
                        BRC20ErrorCodes.INVALID_OPERATION,
                        f"Missing addresses for Curve yToken transfer: sender={sender_address}, recipient={recipient_address}",
                    )

                amount = Decimal(str(operation.get("amt", 0)))

                if amount <= 0:
                    self.logger.error(
                        "CRITICAL: Invalid amount for Curve yToken transfer - REJECTING",
                        ytoken_ticker=ticker,
                        reward_ticker=reward_ticker,
                        amount=amount,
                        txid=tx_info.get("txid"),
                    )
                    return ValidationResult(
                        False,
                        BRC20ErrorCodes.INVALID_OPERATION,
                        f"Invalid amount for Curve yToken transfer: amount={amount} must be > 0",
                    )

                try:
                    curve_service = CurveService(self.db)
                    curve_service.process_transfer(
                        from_address=sender_address,
                        to_address=recipient_address,
                        ticker=reward_ticker,
                        amount=amount,
                        current_block=block_height,
                    )
                except Exception as e:
                    self.logger.error(
                        "CRITICAL: Error processing Curve yToken transfer - REJECTING",
                        error=str(e),
                        ticker=ticker,
                        reward_ticker=reward_ticker,
                        from_addr=sender_address,
                        to_addr=recipient_address,
                        amount=amount,
                        txid=tx_info.get("txid"),
                        exc_info=True,
                    )
                    return ValidationResult(
                        False,
                        BRC20ErrorCodes.UNKNOWN_PROCESSING_ERROR,
                        f"Failed to process Curve yToken transfer: {str(e)}",
                    )

        if validation_result.is_valid:
            is_marketplace = transfer_type == TransferType.MARKETPLACE
            is_marketplace_for_sender = (
                transfer_type == TransferType.MARKETPLACE or transfer_type == TransferType.INVALID_MARKETPLACE
            )
            is_in_emergency_range = False

            start_block = settings.EMERGENCY_MARKETPLACE_SENDER_START_BLOCK
            end_block = settings.EMERGENCY_MARKETPLACE_SENDER_END_BLOCK
            is_in_emergency_range = (
                start_block is not None and end_block is not None and start_block <= block_height <= end_block
            )

            if is_marketplace_for_sender and is_in_emergency_range:
                sender_address = self.get_second_input_address(tx_info)
                if not sender_address:
                    sender_address = self.get_first_input_address(tx_info)
            else:
                sender_address = self.get_first_input_address(tx_info)

            recipient_address = self.validator.get_output_after_op_return_address(tx_info.get("vout", []))

            if sender_address and recipient_address:
                sender_success = self.update_balance(
                    address=sender_address,
                    ticker=operation["tick"],
                    amount_delta=f"-{operation['amt']}",
                    op_type="transfer_out",
                    txid=tx_info["txid"],
                    intermediate_state=intermediate_state,
                )

                if sender_success:
                    recipient_success = self.update_balance(
                        address=recipient_address,
                        ticker=operation["tick"],
                        amount_delta=operation["amt"],
                        op_type="transfer_in",
                        txid=tx_info["txid"],
                        intermediate_state=intermediate_state,
                    )

                    if not recipient_success:
                        self.logger.error(
                            f"Failed to credit recipient balance for transfer",
                            recipient=recipient_address,
                            ticker=operation["tick"],
                            amount=operation["amt"],
                            txid=tx_info["txid"],
                        )
                        return ValidationResult(
                            False,
                            BRC20ErrorCodes.INSUFFICIENT_BALANCE,
                            f"Failed to process transfer: insufficient balance for sender",
                        )
                else:
                    return ValidationResult(
                        False,
                        BRC20ErrorCodes.INSUFFICIENT_BALANCE,
                        f"Insufficient balance for transfer: {sender_address}",
                    )
            else:
                return ValidationResult(
                    False,
                    BRC20ErrorCodes.INVALID_ADDRESS,
                    "Unable to resolve sender or recipient.",
                )
        return validation_result

    def log_operation(
        self,
        op_data,
        val_res,
        tx_info,
        raw_op,
        json_op=None,
        is_mkt=False,
        is_multi_transfer=False,
        multi_transfer_step=None,
        from_address=None,
        to_address=None,
    ) -> BRC20Operation:
        """
        Create and return a BRC20Operation object for persistence.

        Operations are collected and committed before
        critical validations.

        Returns:
            BRC20Operation: The operation object to be persisted
        """
        timestamp = self._convert_block_timestamp(self.current_block_timestamp)
        op_type = op_data.get("op", "invalid")

        # Special handling for STONES mint: use "mint_stones" as operation type
        if op_type == "mint" and raw_op and raw_op.lower().startswith("5d"):
            op_type = "mint_stones"

        from_addr, to_addr = None, None

        if from_address is not None:
            from_addr = from_address
        if to_address is not None:
            to_addr = to_address

        # Fallback to standard logic for other operations
        if from_addr is None and to_addr is None:
            if op_type == "deploy" or op_type == "mint_stones":
                if op_type == "deploy":
                    from_addr = self.get_first_input_address(tx_info)
            elif op_type == "mint":
                to_addr = self.validator.get_output_after_op_return_address(tx_info.get("vout", []))
            elif op_type == "transfer":
                if "explicit_recipient" in tx_info:
                    block_height = tx_info.get("block_height")
                    is_marketplace = is_mkt
                    is_in_emergency_range = False

                    if is_marketplace and block_height is not None:
                        start_block = settings.EMERGENCY_MARKETPLACE_SENDER_START_BLOCK
                        end_block = settings.EMERGENCY_MARKETPLACE_SENDER_END_BLOCK
                        if start_block is not None and end_block is not None:
                            is_in_emergency_range = start_block <= block_height <= end_block

                    if is_marketplace and is_in_emergency_range:
                        from_addr = self.get_second_input_address(tx_info)
                    else:
                        from_addr = self.get_first_input_address(tx_info)
                    to_addr = tx_info.get("explicit_recipient")
                else:
                    block_height = tx_info.get("block_height")
                    addrs = self.resolve_transfer_addresses(tx_info, block_height)
                    from_addr, to_addr = addrs.get("sender"), addrs.get("recipient")
        op = BRC20Operation(
            txid=tx_info["txid"],
            vout_index=tx_info.get("vout_index", 0),
            operation=op_type,
            ticker=op_data.get("tick"),
            amount=op_data.get("amt"),
            from_address=from_addr,
            to_address=to_addr,
            block_height=tx_info["block_height"],
            block_hash=tx_info["block_hash"],
            tx_index=tx_info["tx_index"],
            timestamp=timestamp,
            is_valid=val_res.is_valid,
            error_code=val_res.error_code,
            error_message=val_res.error_message,
            raw_op_return=raw_op,
            parsed_json=json_op,
            is_marketplace=is_mkt,
            is_multi_transfer=is_multi_transfer,
            multi_transfer_step=multi_transfer_step,
        )
        self.db.add(op)
        return op

    def update_balance(
        self,
        address: str,
        ticker: str,
        amount_delta: str,
        op_type: str,
        txid: str,
        intermediate_state: IntermediateState,
    ) -> bool:
        """Update balance in intermediate_state - Single Source of Truth"""

        if ticker and len(ticker) > 0 and ticker[0].lower() == "y":
            normalized_ticker = "y" + ticker[1:].upper()
        else:
            normalized_ticker = ticker.upper()
        start_balance = self.validator.get_balance(address, normalized_ticker, intermediate_state.balances)
        from src.utils.amounts import add_amounts, subtract_amounts, compare_amounts

        amount_delta_str = str(amount_delta)

        if amount_delta_str.startswith("-"):
            amount_to_subtract = amount_delta_str[1:]
            if compare_amounts(start_balance, amount_to_subtract) < 0:
                self.logger.warning(
                    f"Insufficient balance for {op_type} for address {address}: {start_balance} < {amount_to_subtract}",
                    address=address,
                    ticker=normalized_ticker,
                    current_balance=start_balance,
                    required_amount=amount_to_subtract,
                    op_type=op_type,
                    txid=txid,
                )
                return False
            new_balance = subtract_amounts(start_balance, amount_to_subtract)
        else:
            new_balance = add_amounts(start_balance, amount_delta)

        intermediate_state.balances[(address, normalized_ticker)] = new_balance

        self.logger.info(
            "Intermediate balance updated",
            address=address,
            ticker=ticker,
            old_balance=start_balance,
            delta=amount_delta,
            new_balance=new_balance,
            operation_type=op_type,
            txid=txid,
            block_height=intermediate_state.block_height,
        )

        return True

    def flush_balances_from_state(self, intermediate_state: IntermediateState) -> None:
        """Persist all balance updates from intermediate_state to database."""
        # Initialize variables at the very start to ensure they're always defined
        updates_count = 0
        addresses = []

        try:
            from src.models.curve import CurveConstitution, CurveUserInfo
            from src.models.block import ProcessedBlock
            from src.services.curve_service import CurveService
            from decimal import ROUND_DOWN

            RAY = Decimal("10") ** 27

            # Get current block for liquidity_index update
            latest_block = self.db.query(ProcessedBlock).order_by(ProcessedBlock.height.desc()).first()
            current_block = latest_block.height if latest_block else None

            if current_block:
                curve_service = CurveService(self.db)
                active_constitutions = (
                    self.db.query(CurveConstitution).filter(CurveConstitution.last_reward_block < current_block).all()
                )

                for const in active_constitutions:
                    # Check if there are stakers using DB query (before any process_stake() modifications)
                    total_staked_check = (
                        self.db.query(CurveConstitution.total_staked).filter_by(ticker=const.ticker).scalar()
                    )
                    if total_staked_check and total_staked_check > 0:
                        try:
                            curve_service.update_index(const.ticker, current_block)
                        except Exception as e:
                            self.logger.warning(
                                "Failed to update liquidity_index for CurveConstitution",
                                ticker=const.ticker,
                                current_block=current_block,
                                error=str(e),
                            )

            liquidity_index_cache = {}

            if intermediate_state.balances:
                updates_count = len(intermediate_state.balances)
                addresses = list(set(addr for addr, _ in intermediate_state.balances.keys()))

            if not intermediate_state.balances:
                self.logger.debug("No balance updates to flush")
                return

            for (address, ticker), new_balance in intermediate_state.balances.items():
                if ticker and len(ticker) > 0 and ticker[0] == "y":
                    # Pool balances are calculated dynamically from active positions, not stored in CurveUserInfo
                    if address.startswith("POOL::"):
                        self.logger.debug(
                            "Skipping pool address balance flush (calculated dynamically)",
                            address=address,
                            ticker=ticker,
                            balance=str(new_balance),
                            block_height=getattr(intermediate_state, "block_height", "unknown"),
                        )
                        continue

                    staking_ticker = ticker[1:].upper()

                    constitutions = self.db.query(CurveConstitution).filter_by(staking_ticker=staking_ticker).all()

                    if len(constitutions) > 0:
                        # Use the first constitution (or sort by start_block if multiple)
                        constitution = sorted(constitutions, key=lambda c: c.start_block)[0]
                        reward_ticker = constitution.ticker

                        cache_key = f"{reward_ticker}_{current_block}"

                        if cache_key in liquidity_index_cache:
                            # Use cached liquidity_index (already calculated for this reward_ticker in this block)
                            liquidity_index = liquidity_index_cache[cache_key]
                        else:
                            self.db.refresh(constitution)
                            liquidity_index = Decimal(str(constitution.liquidity_index))

                            # Cache the liquidity_index for this reward_ticker and block
                            liquidity_index_cache[cache_key] = liquidity_index

                        # Get user info
                        user_info = (
                            self.db.query(CurveUserInfo)
                            .filter_by(
                                ticker=constitution.ticker, user_address=address  # Use reward ticker (e.g., 'CRV')
                            )
                            .first()
                        )

                        if user_info:
                            # Convert real_balance to scaled_balance
                            # Formula: scaled_balance = (real_balance * RAY) / liquidity_index
                            if liquidity_index > 0:
                                scaled_balance = (new_balance * RAY) / liquidity_index
                                # Round to match database precision
                                scaled_balance = scaled_balance.quantize(
                                    Decimal("0.000000000000000000000000001"), rounding=ROUND_DOWN
                                )
                                user_info.scaled_balance = scaled_balance

                                self.logger.debug(
                                    "Updated CurveUserInfo.scaled_balance for yToken",
                                    address=address,
                                    ticker=ticker,
                                    real_balance=str(new_balance),
                                    scaled_balance=str(scaled_balance),
                                    liquidity_index=str(liquidity_index),
                                    block_height=getattr(intermediate_state, "block_height", "unknown"),
                                )
                            else:
                                self.logger.warning(
                                    "Cannot update yToken balance: liquidity_index is zero",
                                    address=address,
                                    ticker=ticker,
                                    block_height=getattr(intermediate_state, "block_height", "unknown"),
                                )
                        else:
                            # Only log as debug, not warning, to reduce noise
                            self.logger.debug(
                                "Skipping yToken balance update: CurveUserInfo not found (address may not have staked)",
                                address=address,
                                ticker=ticker,
                                reward_ticker=constitution.ticker,
                                block_height=getattr(intermediate_state, "block_height", "unknown"),
                            )
                    else:
                        self.logger.warning(
                            "Cannot update yToken balance: CurveConstitution not found",
                            address=address,
                            ticker=ticker,
                            staking_ticker=staking_ticker,
                            block_height=getattr(intermediate_state, "block_height", "unknown"),
                        )
                        db_balance_obj = Balance.get_or_create(self.db, address, ticker)
                        db_balance_obj.balance = new_balance
                else:
                    # Normal token: update Balance table
                    # ticker is already normalized (with 'y' prefix preserved) from update_balance
                    db_balance_obj = Balance.get_or_create(self.db, address, ticker)
                    db_balance_obj.balance = new_balance

            self.logger.info(
                "Flushed intermediate balances to DB session",
                updates_count=updates_count,
                addresses=addresses,
                block_height=getattr(intermediate_state, "block_height", "unknown"),
            )

        except Exception as e:
            error_str = str(e)

            # Detect SSL or invalid transaction error
            is_ssl_error = (
                "SSL connection has been closed" in error_str
                or "Can't reconnect until invalid transaction is rolled back" in error_str
                or ("connection" in error_str.lower() and "closed" in error_str.lower())
            )

            if is_ssl_error:
                self.logger.error(
                    "CRITICAL: Balance flush failed - SSL connection lost",
                    error=error_str[:200],
                    updates_count=updates_count,
                    addresses=addresses,
                )
                try:
                    self.db.rollback()
                except Exception:
                    pass
                try:
                    self.db.close()
                    self.logger.info("Invalid DB session closed after SSL error")
                except Exception as close_error:
                    self.logger.warning("Error closing invalid session", error=str(close_error))
                from src.utils.exceptions import SSLConnectionError

                raise SSLConnectionError(
                    "SSL connection lost during balance flush - session recreated, retry required", original_error=e
                )
            else:
                self.logger.error(
                    "CRITICAL: Balance flush failed - INDEXER STOPPING",
                    error=error_str[:200],
                    updates_count=updates_count,
                    addresses=addresses,
                )
                try:
                    self.db.rollback()
                except Exception as rollback_error:
                    # If rollback fails, log but don't mask the original error
                    self.logger.error(
                        "Rollback failed during balance flush",
                        rollback_error=str(rollback_error),
                        original_error=error_str[:200],
                    )
                raise  # Re-raise to stop block processing

    def get_first_input_address(self, tx_info: dict) -> Optional[str]:
        try:
            vin = tx_info.get("vin", [])
            if not vin:
                return None

            first_input = vin[0]
            if "coinbase" in first_input:
                return None

            txid = first_input.get("txid")
            vout = first_input.get("vout")

            if not txid or vout is None:
                return None

            return self.utxo_service.get_input_address(txid, vout)
        except Exception as e:
            self.logger.error(f"Error getting first input address: {e}")
            return None

    def get_second_input_address(self, tx_info: dict) -> Optional[str]:
        try:
            vin = tx_info.get("vin", [])
            if len(vin) < 2:
                return None

            second_input = vin[1]
            if "coinbase" in second_input:
                return None

            txid = second_input.get("txid")
            vout = second_input.get("vout")

            if not txid or vout is None:
                return None

            return self.utxo_service.get_input_address(txid, vout)
        except Exception as e:
            self.logger.error(f"Error getting second input address: {e}")
            return None

    def get_multi_transfer_recipient(self, tx: dict, vout_index: int) -> Optional[str]:
        """Extract recipient address for a specific OP_RETURN in a multi-transfer"""
        recipient_index = vout_index + 1
        if recipient_index < len(tx.get("vout", [])):
            recipient_vout = tx.get("vout", [])[recipient_index]
            return self.extract_address_from_output(recipient_vout)
        return None

    def resolve_transfer_addresses(self, tx_info: dict, block_height: Optional[int] = None) -> Dict[str, Optional[str]]:
        is_marketplace = False
        is_in_emergency_range = False

        if block_height is not None:
            transfer_type = self.classify_transfer_type(tx_info, block_height)
            is_marketplace = transfer_type == TransferType.MARKETPLACE

            if is_marketplace:
                start_block = settings.EMERGENCY_MARKETPLACE_SENDER_START_BLOCK
                end_block = settings.EMERGENCY_MARKETPLACE_SENDER_END_BLOCK
                if start_block is not None and end_block is not None:
                    is_in_emergency_range = start_block <= block_height <= end_block

        if is_marketplace and is_in_emergency_range:
            sender_address = self.get_second_input_address(tx_info)
        else:
            sender_address = self.get_first_input_address(tx_info)

        return {
            "sender": sender_address,
            "recipient": self.validator.get_output_after_op_return_address(tx_info.get("vout", [])),
        }

    def _validate_early_marketplace_template(self, tx_info: dict) -> ValidationResult:
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
                "Early marketplace transaction must involve at least 3 different addresses.",
            )
        return ValidationResult(True)

    def _validate_new_marketplace_template(self, tx_info: dict, block_height: int = None) -> ValidationResult:
        inputs = tx_info.get("vin", [])
        txid = tx_info.get("txid", "unknown")

        # Check if we're in emergency range - if so, skip the "same address" validation
        is_in_emergency_range = False
        if block_height is not None:
            start_block = settings.EMERGENCY_MARKETPLACE_SENDER_START_BLOCK
            end_block = settings.EMERGENCY_MARKETPLACE_SENDER_END_BLOCK
            if start_block is not None and end_block is not None:
                is_in_emergency_range = start_block <= block_height <= end_block

        if len(inputs) < 3:
            return ValidationResult(
                False,
                BRC20ErrorCodes.INVALID_MARKETPLACE_TRANSACTION,
                "Marketplace transaction must have at least 3 inputs.",
            )
        if len(inputs) < 2:
            return ValidationResult(
                False,
                BRC20ErrorCodes.INVALID_MARKETPLACE_TRANSACTION,
                "Marketplace transaction must have at least 2 inputs for template validation.",
            )

        input0_addr = self.utxo_service.get_input_address(inputs[0]["txid"], inputs[0]["vout"])
        input1_addr = self.utxo_service.get_input_address(inputs[1]["txid"], inputs[1]["vout"])

        # Skip "same address" validation if in emergency range
        if not is_in_emergency_range:
            if not input0_addr or input0_addr != input1_addr:
                return ValidationResult(
                    False,
                    BRC20ErrorCodes.INVALID_MARKETPLACE_TRANSACTION,
                    "First two inputs must be from the same address.",
                )

        sig0_hex = extract_signature_from_input(inputs[0])
        sig1_hex = extract_signature_from_input(inputs[1])

        sig0_valid = sig0_hex and is_sighash_single_anyonecanpay(sig0_hex)
        sig1_valid = sig1_hex and is_sighash_single_anyonecanpay(sig1_hex)

        if not (sig0_valid and sig1_valid):
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

    def validate_marketplace_transfer(self, tx_info: dict, block_height: int) -> ValidationResult:
        if block_height < 901350:
            return self._validate_early_marketplace_template(tx_info)
        else:
            return self._validate_new_marketplace_template(tx_info, block_height)

    def _has_marketplace_sighash(self, tx_info: dict) -> bool:
        if not tx_info.get("vin"):
            return False
        for vin in tx_info["vin"]:
            signature_hex = extract_signature_from_input(vin)
            if signature_hex and is_sighash_single_anyonecanpay(signature_hex):
                return True
        return False

    def classify_transfer_type(self, tx_info: dict, block_height: int) -> "TransferType":
        if not self._has_marketplace_sighash(tx_info):
            return TransferType.SIMPLE
        marketplace_validation = self.validate_marketplace_transfer(tx_info, block_height)
        if marketplace_validation.is_valid:
            return TransferType.MARKETPLACE
        else:
            return TransferType.INVALID_MARKETPLACE

    def process_multi_transfer(
        self,
        tx: dict,
        block_height: int,
        tx_index: int,
        block_timestamp: int,
        block_hash: str,
        transfer_ops: List[Tuple[str, int]],
        intermediate_state: IntermediateState,
    ) -> Tuple[ProcessingResult, List[DeclarativeMeta], List[Any]]:
        # CRITICAL FIX: Initialize operations_to_persist to collect all operations
        operations_to_persist = []

        tx_info = tx.copy()
        tx_info.update(
            {
                "block_height": block_height,
                "tx_index": tx_index,
                "block_hash": block_hash,
            }
        )
        self.current_block_timestamp = block_timestamp

        structure_validation = self.parser.validate_multi_transfer_structure(tx, transfer_ops)
        if not structure_validation.is_valid:
            op_data = {"op": "transfer"}
            op = self.log_operation(
                op_data,
                structure_validation,
                tx_info,
                transfer_ops,
                is_multi_transfer=True,
            )
            operations_to_persist.append(op)
            return (
                self._create_processing_result(tx_info["txid"], structure_validation, is_multi=True, _op_data=op_data),
                operations_to_persist,
                [],
            )

        parsed_ops = []
        for hex_data, vout_index in transfer_ops:
            parse_result = self.parser.parse_brc20_operation(hex_data)
            parsed_ops.append((parse_result, vout_index))

        meta_validation, ticker, total_amount = self.parser.validate_multi_transfer_meta_rules(parsed_ops)
        if not meta_validation.is_valid:
            op_data = {"op": "transfer", "tick": "multiple"}
            op = self.log_operation(op_data, meta_validation, tx_info, transfer_ops, is_multi_transfer=True)
            operations_to_persist.append(op)
            return (
                self._create_processing_result(tx_info["txid"], meta_validation, is_multi=True, _op_data=op_data),
                operations_to_persist,
                [],
            )

        sender_address = self.get_first_input_address(tx_info)
        deploy_record = self.validator.get_deploy_record(ticker)
        simulated_balances = intermediate_state.balances.copy()
        valid_ops = []
        invalid_ops = []

        for i, (parse_result, vout_index) in enumerate(parsed_ops):
            if not parse_result["success"]:
                invalid_ops.append((i, parse_result["error_code"], parse_result["error_message"]))
                continue

            op_data = parse_result["data"]
            recipient_address = self.get_multi_transfer_recipient(tx_info, vout_index)

            if not recipient_address:
                invalid_ops.append((i, BRC20ErrorCodes.NO_RECEIVER_OUTPUT, f"Missing recipient at step {i}"))
                continue

            current_sender_balance = self.validator.get_balance(sender_address, op_data["tick"], simulated_balances)
            step_validation = self.validator.validate_transfer(op_data, current_sender_balance, deploy_record)

            if not step_validation.is_valid:
                if step_validation.error_code == BRC20ErrorCodes.INSUFFICIENT_BALANCE:
                    self.logger.error("Insufficient balance, stopping multi-transfer", step=i, txid=tx_info["txid"])
                    break

                invalid_ops.append((i, step_validation.error_code, step_validation.error_message))
                continue

            self.update_balance(
                address=sender_address,
                ticker=ticker,
                amount_delta=f"-{op_data['amt']}",
                op_type="transfer_out",
                txid=tx_info["txid"],
                intermediate_state=intermediate_state,
            )

            self.update_balance(
                address=recipient_address,
                ticker=ticker,
                amount_delta=op_data["amt"],
                op_type="transfer_in",
                txid=tx_info["txid"],
                intermediate_state=intermediate_state,
            )

            self.logger.info(
                "Balance updated for transfer step",
                txid=tx_info["txid"],
                sender=sender_address,
                recipient=recipient_address,
                amount=op_data["amt"],
                ticker=ticker,
            )

            valid_ops.append((i, op_data, recipient_address, vout_index, hex_data))

            self.logger.debug(
                "Multi-transfer step processed",
                txid=tx_info["txid"],
                step=i,
                ticker=ticker,
                amount=op_data["amt"],
                sender=sender_address,
                recipient=recipient_address,
            )

        final_result = ValidationResult(len(valid_ops) > 0)

        for i, (parse_result, vout_index) in enumerate(parsed_ops):
            try:
                op_data = parse_result["data"] if parse_result["success"] else {"op": "transfer"}
                is_valid = any(valid[0] == i for valid in valid_ops)
                tx_info_step = tx_info.copy()
                tx_info_step["vout_index"] = vout_index
                tx_info_step["explicit_recipient"] = self.get_multi_transfer_recipient(tx_info, vout_index)

                raw_op = ""
                parsed_json = None
                if parse_result["success"]:
                    hex_data = next((op[4] for op in valid_ops if op[0] == i), None)
                    if hex_data:
                        raw_op = hex_data
                        parsed_json = json.dumps(op_data)

                op = self.log_operation(
                    op_data,
                    ValidationResult(is_valid),
                    tx_info_step,
                    raw_op,
                    parsed_json,
                    is_mkt=False,
                    is_multi_transfer=True,
                    multi_transfer_step=i,
                )
                operations_to_persist.append(op)
            except Exception as e:
                self.logger.error(f"Error logging operation {i}: {str(e)}", txid=tx_info["txid"])

        if valid_ops:
            intermediate_state.balances.update(simulated_balances)
            self.logger.info(
                "Multi-transfer partially processed",
                txid=tx_info["txid"],
                ticker=ticker,
                valid_count=len(valid_ops),
                invalid_count=len(invalid_ops),
            )
        else:
            self.logger.error(
                "Multi-transfer validation failed",
                txid=tx_info["txid"],
                ticker=ticker if ticker else "unknown",
                valid_count=0,
                invalid_count=len(invalid_ops),
            )

        return (
            self._create_processing_result(
                tx_info["txid"], final_result, is_multi=True, _op_data={"tick": ticker, "amt": total_amount}
            ),
            operations_to_persist,
            [],
        )

    def _create_processing_result(self, txid, validation_result, is_multi=False, _op_data=None) -> ProcessingResult:
        result = ProcessingResult()
        result.txid = txid
        result.operation_found = True
        result.is_valid = validation_result.is_valid
        result.error_code = validation_result.error_code
        result.error_message = validation_result.error_message
        if _op_data:
            result.operation_type = "multi_transfer" if is_multi else _op_data.get("op")
            result.ticker = _op_data.get("tick")
            result.amount = _op_data.get("amt")
        return result

    def _get_current_balance(self, address: str, ticker: str, intermediate_state: IntermediateState) -> Decimal:
        key = (address, ticker.upper())
        if key in intermediate_state.balances:
            return intermediate_state.balances[key]
        # CRITICAL: Always pass intermediate_state.balances to ensure consistency
        return self.validator.get_balance(address, ticker, intermediate_state.balances)

    def _get_current_total_minted(self, ticker: str, intermediate_state: IntermediateState) -> Decimal:
        normalized_ticker = ticker.upper()
        if normalized_ticker in intermediate_state.total_minted:
            return intermediate_state.total_minted[normalized_ticker]
        return self.validator.get_total_minted(ticker, intermediate_state.total_minted)

    def _process_wrap_mint(
        self, operation_data: dict, tx_info: dict, intermediate_state: IntermediateState, crypto_data: dict = None
    ) -> ValidationResult:
        """
        Process wrap mint operation (mint with tick="W") using the new WrapValidatorService.

        This method delegates the complex cryptographic validation to the dedicated service
        and handles the state mutation based on the validation result.
        """
        try:
            self.logger.info("Processing wrap mint operation", txid=tx_info.get("txid"))

            # Use the new WrapValidatorService for validation
            validation_result = self.wrap_validator.validate_from_tx_obj(tx_info, operation_data)

            if not validation_result.is_valid:
                self.logger.warning(
                    "Wrap mint validation failed", reason=validation_result.error_message, txid=tx_info.get("txid")
                )
                return validation_result

            amt_str = operation_data.get("amt")
            if not amt_str:
                return ValidationResult(
                    False, BRC20ErrorCodes.INVALID_WRAP_STRUCTURE, "Missing amount in mint operation"
                )

            try:
                amt = Decimal(amt_str)
            except Exception:
                return ValidationResult(False, BRC20ErrorCodes.INVALID_WRAP_STRUCTURE, "Invalid amount format")

            # Extract initiator address from witness data
            vins = tx_info.get("vin", [])
            if not vins:
                return ValidationResult(
                    False, BRC20ErrorCodes.INVALID_WRAP_STRUCTURE, "Transaction must have at least one input"
                )

            # Get initiator address from first input
            initiator_address = self.get_first_input_address(tx_info)
            if not initiator_address:
                return ValidationResult(
                    False, BRC20ErrorCodes.INVALID_WRAP_STRUCTURE, "Could not determine initiator address"
                )

            # Extract contract address from P2TR output (OUTPUT[2])
            if len(tx_info.get("vout", [])) < 3:
                return ValidationResult(
                    False,
                    BRC20ErrorCodes.INVALID_WRAP_STRUCTURE,
                    "Transaction must have at least 3 outputs (OP_RETURN, receiver, script)",
                )

            p2tr_output = tx_info.get("vout", [{}])[2]  # OUTPUT[2] for script address
            contract_address = p2tr_output.get("scriptPubKey", {}).get("addresses", [None])[0]
            if not contract_address:
                contract_address = p2tr_output.get("scriptPubKey", {}).get("address")

            if not contract_address:
                return ValidationResult(
                    False, BRC20ErrorCodes.INVALID_WRAP_STRUCTURE, "Could not extract contract address"
                )

            # Extract cryptographic data from validation result
            crypto_data = (
                validation_result.additional_data.get("crypto_data", {}) if validation_result.additional_data else {}
            )

            # Get csv_blocks directly from additional_data (not nested in crypto_data)
            csv_blocks = (
                validation_result.additional_data.get("csv_blocks", 256) if validation_result.additional_data else 256
            )

            # Create contract record with cryptographic data
            contract = Extended(
                script_address=contract_address,
                initiator_address=initiator_address,
                initial_amount=amt,
                status="active",
                timelock_delay=csv_blocks,  # Use the extracted csv_blocks
                creation_txid=tx_info.get("txid"),
                creation_timestamp=datetime.fromtimestamp(tx_info.get("block_timestamp", 0), tz=timezone.utc),
                creation_height=tx_info.get("block_height", 0),
                internal_pubkey=validation_result.additional_data.get("crypto_proof", {}).get("internal_key", ""),
                tapscript_hex=validation_result.additional_data.get("crypto_proof", {}).get("multisig_script", ""),
                merkle_root=validation_result.additional_data.get("crypto_proof", {}).get("w_proof_commitment", ""),
            )
            self.db.add(contract)

            # For Wrap Mint, tokens are credited to first output after OP_RETURN
            receiver_address = self.validator.get_output_after_op_return_address(tx_info.get("vout", []))
            if not receiver_address:
                return ValidationResult(
                    False,
                    BRC20ErrorCodes.INVALID_WRAP_STRUCTURE,
                    "Invalid Wrap Mint: could not extract receiver address from first output after OP_RETURN",
                )

            mint_success = self.update_balance(
                address=receiver_address,
                ticker="W",
                amount_delta=str(amt),
                op_type="wmint",
                txid=tx_info["txid"],
                intermediate_state=intermediate_state,
            )

            if not mint_success:
                return ValidationResult(False, BRC20ErrorCodes.INSUFFICIENT_WRAP_BALANCE, "Failed to mint W tokens")

            current_minted = self.validator.get_total_minted("W", intermediate_state.total_minted)
            from src.utils.amounts import add_amounts

            intermediate_state.total_minted["W"] = add_amounts(current_minted, str(amt))

            deploy = self.validator.get_deploy_record("W", intermediate_deploys=intermediate_state.deploys)
            if not deploy:
                self.logger.error("W token not deployed", txid=tx_info.get("txid"))
                return ValidationResult(False, BRC20ErrorCodes.INVALID_WRAP_STRUCTURE, "W token not deployed")
            # Update remaining_supply instead of max_supply for Wrap tokens
            current_remaining_supply = deploy.remaining_supply
            new_remaining_supply = add_amounts(str(current_remaining_supply), str(amt))
            deploy.remaining_supply = Decimal(new_remaining_supply)
            self.logger.info(
                "Updated W token remaining_supply",
                old_remaining_supply=str(current_remaining_supply),
                new_remaining_supply=new_remaining_supply,
                mint_amount=str(amt),
                max_supply_unchanged=str(deploy.max_supply),
                txid=tx_info.get("txid"),
            )

            self.logger.info("Wrap mint operation completed successfully", txid=tx_info.get("txid"))
            return ValidationResult(True)

        except Exception as e:
            self.logger.error("Wrap mint processing failed", error=str(e), txid=tx_info.get("txid"), exc_info=True)
            return ValidationResult(
                False, BRC20ErrorCodes.UNKNOWN_PROCESSING_ERROR, f"Wrap mint processing failed: {str(e)}"
            )

    def _process_wrap_burn(
        self, operation_data: dict, tx_info: dict, intermediate_state: IntermediateState
    ) -> ValidationResult:
        """Process wrap burn (tick=W); validate essential amounts."""
        try:
            # 1. Validate essential structure

            vouts = tx_info.get("vout", [])
            if len(vouts) < 2:
                return ValidationResult(
                    False, BRC20ErrorCodes.INVALID_WRAP_STRUCTURE, "Transaction must have at least 2 outputs"
                )

            # Check output 0 (OP_RETURN)
            op_return_output = vouts[0]
            if not self._is_op_return_output(op_return_output):
                return ValidationResult(False, BRC20ErrorCodes.INVALID_WRAP_STRUCTURE, "Output 0 must be OP_RETURN")

            # Check output 1 (BURNER_ADDRESS)
            burner_output = vouts[1]
            burner_address = self.extract_address_from_output(burner_output)
            if not burner_address:
                return ValidationResult(
                    False, BRC20ErrorCodes.INVALID_WRAP_STRUCTURE, "Could not extract burner address from output 1"
                )

            amt_str = operation_data.get("amt")
            if not amt_str:
                return ValidationResult(
                    False, BRC20ErrorCodes.INVALID_WRAP_STRUCTURE, "Missing amount in burn operation"
                )

            try:
                amt = Decimal(amt_str)
            except Exception:
                return ValidationResult(False, BRC20ErrorCodes.INVALID_WRAP_STRUCTURE, "Invalid amount format")

            # Check that amt matches value of output 1
            output_value_btc = Decimal(str(burner_output.get("value", 0)))
            output_value_sats = int(output_value_btc * 10**8)

            if amt != output_value_sats:
                return ValidationResult(
                    False,
                    BRC20ErrorCodes.INVALID_WRAP_STRUCTURE,
                    f"Amount {amt} does not match output value {output_value_sats} (in sats)",
                )

            # 2. Validate burner balance

            # Check that burner address matches
            burner_address_from_input = self.get_first_input_address(tx_info)
            if burner_address_from_input != burner_address:
                return ValidationResult(
                    False, BRC20ErrorCodes.INVALID_WRAP_STRUCTURE, "Burner address mismatch between input and output"
                )

            # Check balance
            current_balance = self.validator.get_balance(burner_address, "W", intermediate_state.balances)
            if current_balance < amt:
                return ValidationResult(
                    False, BRC20ErrorCodes.INSUFFICIENT_WRAP_BALANCE, f"Insufficient balance: {current_balance} < {amt}"
                )

            # Burn W tokens (always done, even if no contract found)
            burn_success = self.update_balance(
                address=burner_address,
                ticker="W",
                amount_delta=f"-{amt}",
                op_type="burn",
                txid=tx_info["txid"],
                intermediate_state=intermediate_state,
            )

            if not burn_success:
                return ValidationResult(False, BRC20ErrorCodes.INSUFFICIENT_WRAP_BALANCE, "Failed to burn W tokens")

            # Decrement total supply
            current_minted = self.validator.get_total_minted("W", intermediate_state.total_minted)
            from src.utils.amounts import subtract_amounts

            intermediate_state.total_minted["W"] = subtract_amounts(current_minted, str(amt))

            deploy = self.validator.get_deploy_record("W", intermediate_deploys=intermediate_state.deploys)
            if not deploy:
                return ValidationResult(False, BRC20ErrorCodes.TICKER_NOT_DEPLOYED, "W token not deployed")

            current_remaining_supply = deploy.remaining_supply
            new_remaining_supply = subtract_amounts(str(current_remaining_supply), str(amt))
            deploy.remaining_supply = Decimal(new_remaining_supply)

            if intermediate_state.deploys is not None:
                intermediate_state.deploys["W"] = deploy

            self.logger.info(
                "Updated W token remaining_supply after burn",
                old_remaining_supply=str(current_remaining_supply),
                new_remaining_supply=new_remaining_supply,
                burn_amount=str(amt),
                max_supply_unchanged=str(deploy.max_supply),
                txid=tx_info.get("txid"),
            )

            # 4. Identify and close contract (if found)

            # Find spent contract (multiple mints may target same contract)
            # For burn, close only contracts matching burned amount, oldest first (FIFO)
            vins = tx_info.get("vin", [])
            if len(vins) >= 2:
                # Last input spends the contract
                contract_input = vins[-1]
                spent_address = self.utxo_service.get_input_address(
                    contract_input.get("txid"), contract_input.get("vout")
                )

                if spent_address:
                    contracts = Extended.get_all_by_script_address(self.db, spent_address)
                    active_contracts = [c for c in contracts if c.is_active()]

                    self.logger.info(
                        "Contract lookup for burn",
                        spent_address=spent_address,
                        total_contracts_found=len(contracts),
                        active_contracts_count=len(active_contracts),
                        contract_statuses=[c.status for c in contracts] if contracts else [],
                        burn_amount=str(amt),
                        txid=tx_info.get("txid"),
                    )

                    if active_contracts:
                        # Convert burned amount to Decimal for comparison
                        burn_amount_decimal = Decimal(str(amt))

                        # Filter contracts matching burned amount
                        matching_contracts = [
                            c
                            for c in active_contracts
                            if c.initial_amount is not None and Decimal(str(c.initial_amount)) == burn_amount_decimal
                        ]

                        # Sort by creation (oldest first): creation_height ASC, creation_timestamp ASC
                        matching_contracts.sort(key=lambda c: (c.creation_height, c.creation_timestamp))

                        if matching_contracts:
                            contract_to_close = matching_contracts[0]
                            contract_to_close.close_contract(
                                closure_txid=tx_info.get("txid"),
                                closure_timestamp=datetime.fromtimestamp(
                                    tx_info.get("block_timestamp", 0), tz=timezone.utc
                                ),
                                closure_height=tx_info.get("block_height", 0),
                            )
                            self.logger.info(
                                "Closed contract after burn",
                                contract_id=contract_to_close.id,
                                contract_amount=str(contract_to_close.initial_amount),
                                burn_amount=str(amt),
                                creation_height=contract_to_close.creation_height,
                                total_matching_contracts=len(matching_contracts),
                                txid=tx_info.get("txid"),
                            )
                        else:
                            self.logger.info(
                                "No contract matching burn amount found (burn processed anyway)",
                                spent_address=spent_address,
                                burn_amount=str(amt),
                                available_amounts=[
                                    str(c.initial_amount) for c in active_contracts if c.initial_amount is not None
                                ],
                                txid=tx_info.get("txid"),
                            )
                    else:
                        self.logger.info(
                            "No active contract found for burn (burn processed anyway)",
                            spent_address=spent_address,
                            txid=tx_info.get("txid"),
                        )

            return ValidationResult(True)

        except Exception as e:
            self.logger.error("Wrap burn processing failed", error=str(e), txid=tx_info.get("txid"))
            return ValidationResult(
                False, BRC20ErrorCodes.UNKNOWN_PROCESSING_ERROR, f"Wrap burn processing failed: {str(e)}"
            )

    def _extract_p2tr_address(self, vout: dict) -> str:
        """Extract P2TR address from output"""
        script_pubkey = vout.get("scriptPubKey", {})
        if script_pubkey.get("type") == "witness_v1_taproot":
            addresses = script_pubkey.get("addresses", [])
            if addresses:
                return addresses[0]
        return None

    def _is_op_return_output(self, vout: dict) -> bool:
        """Check if output is OP_RETURN"""
        script_pubkey = vout.get("scriptPubKey", {})
        return script_pubkey.get("type") == "nulldata" or (
            script_pubkey.get("hex", "") and script_pubkey.get("hex", "").startswith("6a")
        )

    def _find_op_return_index(self, vouts: List[Dict[str, Any]]) -> Optional[int]:
        """
        Find the index of the OP_RETURN output in vouts.

        Uses existing _is_op_return_output() method for consistency.

        Args:
            vouts: List of transaction outputs (from tx_info["vout"])

        Returns:
            Index of OP_RETURN output (0-based), or None if not found

        Example:
            vouts = [{"scriptPubKey": {"type": "nulldata"}}, {"scriptPubKey": {"address": "..."}}]
            _find_op_return_index(vouts) -> 0
        """
        for i, vout in enumerate(vouts):
            if not isinstance(vout, dict):
                continue
            if self._is_op_return_output(vout):
                return i
        return None
