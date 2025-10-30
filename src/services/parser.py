"""
BRC-20 OP_RETURN parsing and validation service.
"""

import json
from typing import Dict, Any, Optional, Tuple, List
from src.utils.exceptions import BRC20ErrorCodes, ValidationResult
from src.utils.bitcoin import is_op_return_script, extract_op_return_data


class BRC20Parser:
    """Parse and validate BRC-20 OP_RETURN payloads"""

    def __init__(self):
        self.max_op_return_size = 80

    def extract_op_return_data(self, tx: Dict[str, Any]) -> Tuple[Optional[str], Optional[int]]:
        if not isinstance(tx, dict) or "vout" not in tx:
            return None, None

        vouts = tx.get("vout", [])
        if not vouts:
            return None, None

        op_return_outputs = []

        for i, vout in enumerate(vouts):
            if not isinstance(vout, dict):
                continue

            script_pub_key = vout.get("scriptPubKey", {})
            if not isinstance(script_pub_key, dict):
                continue

            if script_pub_key.get("type") == "nulldata":
                hex_script = script_pub_key.get("hex", "")
                if is_op_return_script(hex_script):
                    if self._is_likely_brc20_fast(hex_script) or self._is_likely_wmint_fast(hex_script):
                        op_return_outputs.append((hex_script, i))

        if len(op_return_outputs) != 1:
            return None, None

        hex_script, vout_index = op_return_outputs[0]

        op_return_data = extract_op_return_data(hex_script)
        if op_return_data is None:
            return None, None

        try:
            data_bytes = bytes.fromhex(op_return_data)
            if len(data_bytes) > self.max_op_return_size:
                return None, None
        except ValueError:
            return None, None

        return op_return_data, vout_index

    def extract_op_return_data_with_position_check(
        self, tx: Dict[str, Any], operation_type: str = None
    ) -> Tuple[Optional[str], Optional[int]]:
        if not isinstance(tx, dict) or "vout" not in tx:
            return None, None

        outputs = tx["vout"]
        if not outputs or len(outputs) == 0:
            return None, None

        if operation_type in ["mint", "transfer"]:
            return self._extract_op_return_first_position_only(tx)
        else:
            return self._extract_op_return_any_position(tx)

    def _extract_op_return_first_position_only(self, tx: Dict[str, Any]) -> Tuple[Optional[str], Optional[int]]:
        outputs = tx["vout"]

        first_output = outputs[0]
        if not isinstance(first_output, dict):
            return None, None

        script_pub_key = first_output.get("scriptPubKey", {})
        if not isinstance(script_pub_key, dict):
            return None, None

        if script_pub_key.get("type") != "nulldata":
            return None, None

        hex_script = script_pub_key.get("hex", "")
        if not is_op_return_script(hex_script):
            return None, None

        op_return_count = sum(
            1 for vout in outputs if isinstance(vout, dict) and vout.get("scriptPubKey", {}).get("type") == "nulldata"
        )

        if op_return_count != 1:
            return None, None

        op_return_data = extract_op_return_data(hex_script)
        if op_return_data is None:
            return None, None

        try:
            data_bytes = bytes.fromhex(op_return_data)
            if len(data_bytes) > self.max_op_return_size:
                return None, None
        except ValueError:
            return None, None

        return op_return_data, 0

    def _extract_op_return_any_position(self, tx: Dict[str, Any]) -> Tuple[Optional[str], Optional[int]]:
        return self.extract_op_return_data(tx)

    def parse_brc20_operation(self, hex_data: str) -> Dict[str, Any]:
        try:
            if self._is_likely_wmint_fast(hex_data):
                return self.parse_wmint_operation(hex_data)

            sanitized_hex = hex_data.replace("\x00", "")
            try:
                data_bytes = bytes.fromhex(sanitized_hex)
                json_str = data_bytes.decode("utf-8")

                if '"p":"brc-20"' not in json_str and '"p": "brc-20"' not in json_str:
                    return {
                        "success": False,
                        "data": None,
                        "error_code": BRC20ErrorCodes.INVALID_PROTOCOL,
                        "error_message": "Not a BRC-20 operation",
                    }

            except ValueError:
                return {
                    "success": False,
                    "data": None,
                    "error_code": BRC20ErrorCodes.INVALID_JSON,
                    "error_message": "Hex decoding failed: not valid hex data",
                }
            except UnicodeDecodeError:
                return {
                    "success": False,
                    "data": None,
                    "error_code": BRC20ErrorCodes.INVALID_JSON,
                    "error_message": "UTF-8 decoding failed: not valid UTF-8 data",
                }
            try:
                operation = json.loads(json_str)
            except json.JSONDecodeError:
                return {
                    "success": False,
                    "data": None,
                    "error_code": BRC20ErrorCodes.INVALID_JSON,
                    "error_message": "Parsing failed: not valid JSON",
                }
            if not isinstance(operation, dict):
                return {
                    "success": False,
                    "data": None,
                    "error_code": BRC20ErrorCodes.INVALID_JSON,
                    "error_message": "Parsed JSON is not an object",
                }
            protocol = operation.get("p")
            if protocol is None:
                return {
                    "success": False,
                    "data": None,
                    "error_code": BRC20ErrorCodes.MISSING_PROTOCOL,
                    "error_message": "Missing protocol field 'p'",
                }
            if protocol != "brc-20":
                return {
                    "success": False,
                    "data": None,
                    "error_code": BRC20ErrorCodes.INVALID_PROTOCOL,
                    "error_message": f"Invalid protocol: {protocol}, expected 'brc-20'",
                }
            op = operation.get("op")
            if op is None:
                return {
                    "success": False,
                    "data": None,
                    "error_code": BRC20ErrorCodes.MISSING_OPERATION,
                    "error_message": "Missing operation field 'op'",
                }
            valid_operations = ["deploy", "mint", "transfer", "test_opi", "burn", "swap"]

            if op not in valid_operations:
                return {
                    "success": False,
                    "data": None,
                    "error_code": BRC20ErrorCodes.INVALID_OPERATION,
                    "error_message": f"Invalid operation: {op}, expected one of {valid_operations}",
                }
            ticker = operation.get("tick")
            # For swap, ticker may be omitted (pair provided in 'init'/'exe')
            if op != "swap":
                if ticker is None:
                    return {
                        "success": False,
                        "data": None,
                        "error_code": BRC20ErrorCodes.MISSING_TICKER,
                        "error_message": "Missing ticker field 'tick'",
                    }
                if not self.validate_ticker_format(ticker):
                    return {
                        "success": False,
                        "data": None,
                        "error_code": BRC20ErrorCodes.EMPTY_TICKER,
                        "error_message": "Ticker cannot be empty",
                    }
            return {
                "success": True,
                "data": operation,
                "error_message": None,
                "error_code": None,
            }
        except Exception as e:
            return {
                "success": False,
                "data": None,
                "error_code": BRC20ErrorCodes.UNKNOWN_PROCESSING_ERROR,
                "error_message": f"Unexpected error: {str(e)}",
            }

    def validate_json_structure(self, operation: Dict[str, Any]) -> Tuple[bool, Optional[str], Optional[str]]:

        if not isinstance(operation, dict):
            return (
                False,
                BRC20ErrorCodes.INVALID_JSON,
                "Operation must be a JSON object",
            )

        protocol = operation.get("p")
        if protocol is None:
            return False, BRC20ErrorCodes.MISSING_PROTOCOL, "Missing protocol field 'p'"

        if protocol != "brc-20":
            return (
                False,
                BRC20ErrorCodes.INVALID_PROTOCOL,
                f"Invalid protocol: {protocol}, expected 'brc-20'",
            )

        op = operation.get("op")
        if op is None:
            return (
                False,
                BRC20ErrorCodes.MISSING_OPERATION,
                "Missing operation field 'op'",
            )

        valid_operations = ["deploy", "mint", "transfer", "test_opi", "burn", "swap"]
        if op not in valid_operations:
            return (
                False,
                BRC20ErrorCodes.INVALID_OPERATION,
                f"Invalid operation: {op}, expected one of {valid_operations}",
            )

        ticker = operation.get("tick")
        if op != "swap":
            if ticker is None:
                return False, BRC20ErrorCodes.MISSING_TICKER, "Missing ticker field 'tick'"

            if not self.validate_ticker_format(ticker):
                return False, BRC20ErrorCodes.EMPTY_TICKER, "Ticker cannot be empty"

        if op == "deploy":
            return self._validate_deploy_fields(operation)
        elif op == "mint":
            return self._validate_mint_fields(operation)
        elif op == "transfer":
            return self._validate_transfer_fields(operation)
        elif op == "swap":
            return self._validate_swap_fields(operation)

        return True, None, None

    def _validate_swap_fields(self, operation: Dict[str, Any]) -> Tuple[bool, Optional[str], Optional[str]]:
        """
        Validate swap operation payload. For now we support `init` flavor only.
        Required fields:
          - init: "SRC,DST" tickers string
          - amt: string amount to lock (decimal)
          - lock: string blocks (integer >= 1)
        """
        init_field = operation.get("init")
        amt_field = operation.get("amt")
        lock_field = operation.get("lock")

        if init_field is None:
            return False, BRC20ErrorCodes.INVALID_OPERATION, "Missing 'init' for swap operation"

        if not isinstance(init_field, str) or "," not in init_field:
            return False, BRC20ErrorCodes.INVALID_TICKER, "Field 'init' must be 'SRC,DST'"

        if amt_field is None or not isinstance(amt_field, str) or amt_field.strip() == "":
            return False, BRC20ErrorCodes.INVALID_AMOUNT, "Missing or invalid 'amt'"

        if lock_field is None or not isinstance(lock_field, str):
            return False, BRC20ErrorCodes.INVALID_AMOUNT, "Missing or invalid 'lock'"
        try:
            lock_int = int(lock_field)
            if lock_int < 1:
                return False, BRC20ErrorCodes.INVALID_AMOUNT, "'lock' must be >= 1"
        except Exception:
            return False, BRC20ErrorCodes.INVALID_AMOUNT, "'lock' must be integer string"

        src, dst = [t.strip() for t in init_field.split(",", 1)]
        if not self.validate_ticker_format(src) or not self.validate_ticker_format(dst):
            return False, BRC20ErrorCodes.INVALID_TICKER, "Invalid ticker(s) in 'init'"

        return True, None, None

    def validate_ticker_format(self, ticker: str) -> bool:
        """
        Validate ticker format

        Args:
            ticker: Ticker string

        Returns:
            bool: True if valid

        RULES:
        - Cannot be empty ""
        - "0" is valid
        - Any size as long as it fits in 80 bytes total
        """
        if not isinstance(ticker, str):
            return False

        if ticker == "":
            return False

        return True

    def _validate_deploy_fields(self, operation: Dict[str, Any]) -> Tuple[bool, Optional[str], Optional[str]]:
        max_supply = operation.get("m")
        if max_supply is None:
            return False, BRC20ErrorCodes.INVALID_AMOUNT, "Missing max supply field 'm'"

        if not isinstance(max_supply, str):
            return (
                False,
                BRC20ErrorCodes.INVALID_AMOUNT,
                "Max supply 'm' must be string",
            )

        limit_per_op = operation.get("l")
        if limit_per_op is not None and not isinstance(limit_per_op, str):
            return (
                False,
                BRC20ErrorCodes.INVALID_AMOUNT,
                "Limit per operation 'l' must be string",
            )

        return True, None, None

    def _validate_mint_fields(self, operation: Dict[str, Any]) -> Tuple[bool, Optional[str], Optional[str]]:
        amount = operation.get("amt")
        if amount is None:
            return False, BRC20ErrorCodes.INVALID_AMOUNT, "Missing amount field 'amt'"

        if not isinstance(amount, str):
            return False, BRC20ErrorCodes.INVALID_AMOUNT, "Amount 'amt' must be string"

        return True, None, None

    def _validate_transfer_fields(self, operation: Dict[str, Any]) -> Tuple[bool, Optional[str], Optional[str]]:
        amount = operation.get("amt")
        if amount is None:
            return False, BRC20ErrorCodes.INVALID_AMOUNT, "Missing amount field 'amt'"

        if not isinstance(amount, str):
            return False, BRC20ErrorCodes.INVALID_AMOUNT, "Amount 'amt' must be string"

        return True, None, None

    def parse_transaction(self, tx: Dict[str, Any]) -> Dict[str, Any]:
        """
        Parse complete transaction for BRC-20 operations
        """
        result = {
            "has_brc20": False,
            "op_return_data": None,
            "vout_index": None,
            "operation": None,
            "error_code": None,
            "error_message": None,
        }

        hex_data, vout_index = self.extract_op_return_data(tx)

        if hex_data is None:
            if self._has_multiple_op_returns(tx):
                multi_transfer_ops = self.extract_multi_transfer_op_returns(tx)
                if len(multi_transfer_ops) > 1:
                    result["error_code"] = None
                    result["error_message"] = "Multi-transfer transaction detected"
                    result["has_brc20"] = True
                    return result
                else:
                    result["error_code"] = BRC20ErrorCodes.MULTIPLE_OP_RETURNS
                    result["error_message"] = "Multiple OP_RETURN outputs found"
            return result

        result["op_return_data"] = hex_data
        result["vout_index"] = vout_index

        parse_result = self.parse_brc20_operation(hex_data)

        if parse_result["success"]:
            result["has_brc20"] = True
            result["operation"] = parse_result["data"]
        else:
            result["error_code"] = parse_result["error_code"]
            result["error_message"] = parse_result["error_message"]

        return result

    def _has_multiple_op_returns(self, tx: Dict[str, Any]) -> bool:
        if not isinstance(tx, dict) or "vout" not in tx:
            return False

        op_return_count = 0
        for vout in tx["vout"]:
            if not isinstance(vout, dict):
                continue

            script_pub_key = vout.get("scriptPubKey", {})
            if isinstance(script_pub_key, dict) and script_pub_key.get("type") == "nulldata":
                op_return_count += 1

        return op_return_count > 1

    def extract_multi_transfer_op_returns(self, tx: Dict[str, Any]) -> List[Tuple[str, int]]:
        if not isinstance(tx, dict) or "vout" not in tx:
            return []

        vouts = tx.get("vout", [])
        if not vouts:
            return []

        op_return_count = 0
        for vout in vouts:
            if isinstance(vout, dict) and vout.get("scriptPubKey", {}).get("type") == "nulldata":
                op_return_count += 1

        if op_return_count <= 1:
            return []

        transfer_ops = []
        for i, vout in enumerate(vouts):
            if not isinstance(vout, dict):
                continue

            script_pub_key = vout.get("scriptPubKey", {})
            if script_pub_key.get("type") == "nulldata":
                hex_script = script_pub_key.get("hex", "")
                op_return_data = extract_op_return_data(hex_script)
                if op_return_data and self._is_transfer_operation_fast(op_return_data):
                    transfer_ops.append((op_return_data, i))
        return transfer_ops

    def _is_likely_brc20_fast(self, hex_script: str) -> bool:
        try:
            from src.utils.bitcoin import extract_op_return_data

            op_return_data = extract_op_return_data(hex_script)
            if not op_return_data:
                return False

            data_bytes = bytes.fromhex(op_return_data)
            json_str = data_bytes.decode("utf-8", errors="ignore")

            return '"p":"brc-20"' in json_str or '"p": "brc-20"' in json_str

        except Exception:
            return False

    def _is_likely_wmint_fast(self, hex_script: str) -> bool:
        """
        Fast detection of wmint magic code in OP_RETURN.
        Magic code: 5B577C4254437C4D5D
        """
        try:
            from src.utils.bitcoin import extract_op_return_data

            op_return_data = extract_op_return_data(hex_script)
            if not op_return_data:
                return False

            data_bytes = bytes.fromhex(op_return_data)

            wrap_magic = bytes.fromhex("5B577C4254437C4D5D")
            return data_bytes.startswith(wrap_magic)

        except Exception:
            return False

    def _is_transfer_operation_fast(self, hex_data: str) -> bool:
        try:
            json_str = bytes.fromhex(hex_data).decode("utf-8")
            return '"p":"brc-20"' in json_str and '"op":"transfer"' in json_str
        except (ValueError, UnicodeDecodeError):
            return False

    def validate_multi_transfer_structure(
        self, tx: Dict[str, Any], transfer_ops: List[Tuple[str, int]]
    ) -> ValidationResult:

        vouts = tx.get("vout", [])
        for i, (hex_data, op_return_index) in enumerate(transfer_ops):
            expected_op_return_index = 2 * i
            if op_return_index != expected_op_return_index:
                return ValidationResult(
                    False,
                    BRC20ErrorCodes.INVALID_OUTPUT_POSITION,
                    f"Step {i}: OP_RETURN found at vout {op_return_index}, " f"expected {expected_op_return_index}",
                )

            receiver_index = expected_op_return_index + 1
            if receiver_index >= len(vouts):
                return ValidationResult(
                    False,
                    BRC20ErrorCodes.NO_RECEIVER_OUTPUT,
                    f"Step {i}: Missing recipient output at vout {receiver_index}",
                )

        return ValidationResult(True)

    def validate_multi_transfer_meta_rules(
        self, parsed_ops: List[Tuple[Dict[str, Any], int]]
    ) -> Tuple[ValidationResult, Optional[str], Optional[str]]:

        if not parsed_ops:
            return ValidationResult(True), None, "0"

        total_amount = "0"
        from src.utils.amounts import add_amounts

        valid_ops = []
        for parse_result, _ in parsed_ops:
            if parse_result["success"]:
                valid_ops.append(parse_result)

        if not valid_ops:
            return (
                ValidationResult(
                    False,
                    BRC20ErrorCodes.MISSING_TICKER,
                    "No valid operations found in multi-transfer",
                ),
                None,
                "0",
            )

        first_ticker = valid_ops[0]["data"].get("tick", "").upper()

        for parse_result in valid_ops:
            data = parse_result["data"]
            ticker = data.get("tick", "").upper()
            if ticker != first_ticker:
                return (
                    ValidationResult(
                        False,
                        BRC20ErrorCodes.MULTI_TRANSFER_MIXED_TICKERS,
                        "Multi-transfer cannot contain multiple tickers",
                    ),
                    None,
                    "0",
                )
            total_amount = add_amounts(total_amount, data.get("amt", "0"))

        return ValidationResult(True), first_ticker, total_amount

    def parse_wmint_operation(self, hex_data: str) -> Dict[str, Any]:
        """
        Parse wmint operation from hex data.
        OP_RETURN contains: magic_code (5B577C4254437C4D5D) + control_block (32 bytes)

        Args:
            hex_data: Hex-encoded OP_RETURN data

        Returns:
            Dict with parsed operation data or error information
        """
        try:
            data_bytes = bytes.fromhex(hex_data)

            wrap_magic = bytes.fromhex("5B577C4254437C4D5D")
            if not data_bytes.startswith(wrap_magic):
                return {
                    "success": False,
                    "data": None,
                    "error_code": BRC20ErrorCodes.INVALID_PROTOCOL,
                    "error_message": "Not a wmint operation - missing magic code",
                }

            wrap_data = data_bytes[len(wrap_magic) :]

            if len(wrap_data) < 32:
                return {
                    "success": False,
                    "data": None,
                    "error_code": BRC20ErrorCodes.INVALID_JSON,
                    "error_message": "Wmint data too short - missing control_block",
                }

            control_block = wrap_data[:32]

            return {
                "success": True,
                "data": {
                    "op": "wmint",
                    "tick": "W",
                    "control_block": control_block.hex(),
                },
                "error_message": None,
                "error_code": None,
            }

        except Exception as e:
            return {
                "success": False,
                "data": None,
                "error_code": BRC20ErrorCodes.UNKNOWN_PROCESSING_ERROR,
                "error_message": f"Wmint parsing error: {str(e)}",
            }
