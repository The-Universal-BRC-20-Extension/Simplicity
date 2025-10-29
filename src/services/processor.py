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
        self.logger = structlog.get_logger()
        self.current_block_timestamp = None
        self._pending_balance_updates = {}
        self.opi_registry: Optional[OPIRegistry] = None

    def set_opi_registry(self, opi_registry):
        self.opi_registry = opi_registry
        self.parser = BRC20Parser(opi_registry=opi_registry)

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
        intermediate_balances=None,
        intermediate_total_minted=None,
        intermediate_deploys=None,
        intermediate_state=None,
    ) -> Tuple[ProcessingResult, List[DeclarativeMeta], List[Any]]:
        if intermediate_state is None:
            intermediate_state = IntermediateState()

        multi_transfer_ops = self.parser.extract_multi_transfer_op_returns(tx)
        if len(multi_transfer_ops) > 1:
            result = self.process_multi_transfer(
                tx,
                block_height,
                tx_index,
                block_timestamp,
                block_hash,
                multi_transfer_ops,
                intermediate_state.balances,
            )
            return result, [], []

        result = ProcessingResult()
        result.txid = tx.get("txid", "unknown")
        hex_data, vout_index = self.parser.extract_op_return_data(tx)
        if not hex_data:
            return result, [], []
        if vout_index is None:
            vout_index = 0
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
                self.log_operation(
                    op_data={"op": "invalid"},
                    val_res=ValidationResult(
                        False,
                        parse_result.get("error_code"),
                        parse_result.get("error_message"),
                    ),
                    tx_info=tx,
                    raw_op=hex_data,
                )
            return result, [], []
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
                operation_data["tick"] = operation_data["tick"].upper()
            op_type = operation_data.get("op")
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
            }

            # Check for OPI processors first, before standard BRC20 validation
            if self.opi_registry and self.opi_registry.has_processor(op_type):
                context = Context(intermediate_state, self.validator)
                processor = self.opi_registry.get_processor(op_type, context)

                try:
                    result, state = processor.process_op(operation_data, tx_info)

                    # Apply state mutations from OPI
                    for mutation in state.state_mutations:
                        mutation(intermediate_state)

                    for obj in state.orm_objects:
                        self.db.add(obj)

                    return result, state.orm_objects, []
                except Exception as e:
                    self.logger.error("OPI processing failed", op_type=op_type, txid=tx_info.get("txid"), error=str(e))
                    return (
                        ProcessingResult(
                            operation_found=True, is_valid=False, error_message=f"OPI processing failed: {str(e)}"
                        ),
                        [],
                        [],
                    )

            elif op_type in ["deploy", "mint", "transfer"]:
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
                        self.process_mint(
                            operation_data,
                            tx,
                            intermediate_balances=intermediate_state.balances,
                            intermediate_total_minted=intermediate_state.total_minted,
                            intermediate_deploys=intermediate_state.deploys,
                        )
                    elif op_type == "transfer":
                        if self.classify_transfer_type(tx, block_height) == TransferType.MARKETPLACE:
                            is_marketplace = True
                        validation_result = self.process_transfer(
                            operation_data,
                            tx,
                            validation_result,
                            hex_data,
                            block_height,
                            intermediate_balances=intermediate_state.balances,
                        )

                result.is_valid = validation_result.is_valid
                result.error_code = validation_result.error_code
                result.error_message = validation_result.error_message
                result.operation_type = op_type
                result.ticker = operation_data.get("tick")
                result.amount = operation_data.get("amt")

                self.log_operation(
                    op_data=operation_data,
                    val_res=validation_result,
                    tx_info=tx,
                    raw_op=hex_data,
                    json_op=json.dumps(operation_data),
                    is_mkt=op_type == "transfer"
                    and self.classify_transfer_type(tx, block_height) == TransferType.MARKETPLACE,
                )

                return result, [], []

            else:
                self.logger.warning("Unknown operation type", op_type=op_type, txid=tx_info.get("txid"))
                return (
                    ProcessingResult(
                        operation_found=True, is_valid=False, error_message=f"Unknown operation: {op_type}"
                    ),
                    [],
                    [],
                )
        except Exception as e:
            self.logger.error(
                "Unhandled exception in BRC20Processor",
                txid=result.txid,
                error=str(e),
                exc_info=True,
            )
            result.is_valid = False
            result.error_code = "UNHANDLED_EXCEPTION"
            result.error_message = str(e)
            return result, [], []

    def process_deploy(
        self,
        operation: dict,
        tx_info: dict,
        intermediate_deploys: Optional[Dict] = None,
    ):
        deploy = Deploy(
            ticker=operation["tick"].upper(),
            max_supply=operation["m"],
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
        intermediate_balances: Optional[Dict] = None,
        intermediate_total_minted: Optional[Dict] = None,
        intermediate_deploys: Optional[Dict] = None,
    ):
        ticker = operation["tick"].upper()
        amount = operation["amt"]
        recipient = self.validator.get_output_after_op_return_address(tx_info.get("vout", []))

        deploy = self.validator.get_deploy_record(ticker, intermediate_deploys=intermediate_deploys)
        validation_result = self.validator.validate_mint(
            operation, deploy, intermediate_total_minted=intermediate_total_minted
        )

        if validation_result.is_valid:
            from src.utils.amounts import add_amounts

            if intermediate_total_minted is not None:
                current_minted = self.validator.get_total_minted(ticker, intermediate_total_minted)
                intermediate_total_minted[ticker] = add_amounts(current_minted, amount)

            if recipient:
                mint_success = self.update_balance(
                    address=recipient,
                    ticker=ticker,
                    amount_delta=amount,
                    op_type="mint",
                    txid=tx_info["txid"],
                    intermediate_balances=intermediate_balances,
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

    def process_transfer(
        self,
        operation: dict,
        tx_info: dict,
        validation_result: ValidationResult,
        hex_data: str,
        block_height: int,
        intermediate_balances: Optional[Dict] = None,
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

        if validation_result.is_valid:
            sender_address = self.get_first_input_address(tx_info)
            recipient_address = self.validator.get_output_after_op_return_address(tx_info.get("vout", []))
            if sender_address and recipient_address:
                sender_success = self.update_balance(
                    address=sender_address,
                    ticker=operation["tick"],
                    amount_delta=f"-{operation['amt']}",
                    op_type="transfer_out",
                    txid=tx_info["txid"],
                    intermediate_balances=intermediate_balances,
                )

                if sender_success:
                    recipient_success = self.update_balance(
                        address=recipient_address,
                        ticker=operation["tick"],
                        amount_delta=operation["amt"],
                        op_type="transfer_in",
                        txid=tx_info["txid"],
                        intermediate_balances=intermediate_balances,
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
    ):
        timestamp = self._convert_block_timestamp(self.current_block_timestamp)
        op_type = op_data.get("op", "invalid")
        from_addr, to_addr = None, None
        if op_type == "deploy":
            from_addr = self.get_first_input_address(tx_info)
        elif op_type == "mint":
            to_addr = self.validator.get_output_after_op_return_address(tx_info.get("vout", []))
        elif op_type == "transfer":
            if "explicit_recipient" in tx_info:
                from_addr = self.get_first_input_address(tx_info)
                to_addr = tx_info.get("explicit_recipient")
            else:
                addrs = self.resolve_transfer_addresses(tx_info)
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

    def update_balance(
        self,
        address,
        ticker,
        amount_delta,
        op_type,
        txid,
        intermediate_balances: Optional[Dict] = None,
    ) -> bool:
        """Update balance and return True if successful, False if insufficient balance."""
        normalized_ticker = ticker.upper()
        start_balance = self.validator.get_balance(address, normalized_ticker, intermediate_balances)
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

        self._pending_balance_updates[(address, normalized_ticker)] = new_balance

        if intermediate_balances is not None:
            intermediate_balances[(address, normalized_ticker)] = new_balance

        return True

    def flush_pending_balances(self, intermediate_state: IntermediateState) -> None:
        """Apply all pending balance updates from intermediate state to the database."""
        if not intermediate_state.balances:
            return

        updates_count = len(intermediate_state.balances)
        addresses = list(set(addr for addr, _ in intermediate_state.balances.keys()))

        try:
            for (address, ticker), new_balance in intermediate_state.balances.items():
                db_balance_obj = Balance.get_or_create(self.db, address, ticker)
                db_balance_obj.balance = new_balance

            self.logger.debug("Flushed pending balance updates", updates_count=updates_count, addresses=addresses)

        except Exception as e:
            self.logger.error(
                "Failed to flush pending balance updates", error=str(e), pending_updates_count=updates_count
            )
            raise

    def clear_pending_balances(self) -> None:
        """Clear all pending balance updates without applying them."""
        if self._pending_balance_updates:
            self.logger.debug(
                "Clearing pending balance updates due to rollback", updates_count=len(self._pending_balance_updates)
            )
            self._pending_balance_updates.clear()

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

    def get_multi_transfer_recipient(self, tx: dict, vout_index: int) -> Optional[str]:
        """Extract recipient address for a specific OP_RETURN in a multi-transfer"""
        recipient_index = vout_index + 1
        if recipient_index < len(tx.get("vout", [])):
            recipient_vout = tx.get("vout", [])[recipient_index]
            return self.extract_address_from_output(recipient_vout)
        return None

    def resolve_transfer_addresses(self, tx_info: dict) -> Dict[str, Optional[str]]:
        return {
            "sender": self.get_first_input_address(tx_info),
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

    def _validate_new_marketplace_template(self, tx_info: dict) -> ValidationResult:
        inputs = tx_info.get("vin", [])
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

    def validate_marketplace_transfer(self, tx_info: dict, block_height: int) -> ValidationResult:
        if block_height < 901350:
            return self._validate_early_marketplace_template(tx_info)
        else:
            return self._validate_new_marketplace_template(tx_info)

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
        intermediate_balances,
    ) -> Tuple[ProcessingResult, List[DeclarativeMeta], List[Any]]:
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
            self.log_operation(
                op_data,
                structure_validation,
                tx_info,
                transfer_ops,
                is_multi_transfer=True,
            )
            return (
                self._create_processing_result(tx_info["txid"], structure_validation, is_multi=True, _op_data=op_data),
                [],
                [],
            )

        parsed_ops = []
        for hex_data, vout_index in transfer_ops:
            parse_result = self.parser.parse_brc20_operation(hex_data)
            parsed_ops.append((parse_result, vout_index))

        meta_validation, ticker, total_amount = self.parser.validate_multi_transfer_meta_rules(parsed_ops)
        if not meta_validation.is_valid:
            op_data = {"op": "transfer", "tick": "multiple"}
            self.log_operation(op_data, meta_validation, tx_info, transfer_ops, is_multi_transfer=True)
            return (
                self._create_processing_result(tx_info["txid"], meta_validation, is_multi=True, _op_data=op_data),
                [],
                [],
            )

        sender_address = self.get_first_input_address(tx_info)
        deploy_record = self.validator.get_deploy_record(ticker)
        simulated_balances = intermediate_balances.copy() if intermediate_balances is not None else {}
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
                intermediate_balances=simulated_balances,
            )

            self.update_balance(
                address=recipient_address,
                ticker=ticker,
                amount_delta=op_data["amt"],
                op_type="transfer_in",
                txid=tx_info["txid"],
                intermediate_balances=simulated_balances,
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

                self.log_operation(
                    op_data,
                    ValidationResult(is_valid),
                    tx_info_step,
                    raw_op,
                    parsed_json,
                    is_mkt=False,
                    is_multi_transfer=True,
                    multi_transfer_step=i,
                )
            except Exception as e:
                self.logger.error(f"Error logging operation {i}: {str(e)}", txid=tx_info["txid"])

        if valid_ops and intermediate_balances is not None:
            intermediate_balances.update(simulated_balances)
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
            [],
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
        return self.validator.get_balance(address, ticker)

    def _get_current_total_minted(self, ticker: str, intermediate_state: IntermediateState) -> Decimal:
        normalized_ticker = ticker.upper()
        if normalized_ticker in intermediate_state.total_minted:
            return intermediate_state.total_minted[normalized_ticker]
        return self.validator.get_total_minted(ticker)
