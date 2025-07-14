"""
BRC-20 OP_RETURN parsing and validation service.
"""

import json
from typing import Any, Dict, Optional, Tuple

from src.utils.bitcoin import extract_op_return_data, is_op_return_script
from src.utils.exceptions import BRC20ErrorCodes


class BRC20Parser:
    """Parse and validate BRC-20 OP_RETURN payloads"""

    def __init__(self):
        """Initialize parser"""
        self.max_op_return_size = 80  # Bitcoin OP_RETURN size limit

    def extract_op_return_data(
        self, tx: Dict[str, Any]
    ) -> Tuple[Optional[str], Optional[int]]:
        """
        Extract OP_RETURN data from transaction

        Args:
            tx: Transaction data from Bitcoin RPC

        Returns:
            Tuple[Optional[str], Optional[int]]: (hex_data, vout_index) or (None, None)

        RULES:
        - Exactly 1 OP_RETURN per transaction
        - OP_RETURN ≤ 80 bytes
        - Return (None, None) if multiple OP_RETURN or invalid
        """
        if not isinstance(tx, dict) or "vout" not in tx:
            return None, None

        op_return_outputs = []

        for i, vout in enumerate(tx["vout"]):
            if not isinstance(vout, dict):
                continue

            script_pub_key = vout.get("scriptPubKey", {})
            if not isinstance(script_pub_key, dict):
                continue

            if script_pub_key.get("type") == "nulldata":
                hex_script = script_pub_key.get("hex", "")
                if is_op_return_script(hex_script):
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
        """
        Extract OP_RETURN data with position validation based on operation type

        Args:
            tx: Transaction data from Bitcoin RPC
            operation_type: 'deploy', 'mint', or 'transfer' (if known)

        Returns:
            Tuple[Optional[str], Optional[int]]: (hex_data, vout_index) or (None, None)

        RULES:
        - Deploy: OP_RETURN can be in any position (existing behavior)
        - Mint/Transfer: OP_RETURN must be in first position (vout index 0)
        - If operation_type unknown, use existing behavior (any position)
        """
        if not isinstance(tx, dict) or "vout" not in tx:
            return None, None

        outputs = tx["vout"]
        if not outputs or len(outputs) == 0:
            return None, None

        if operation_type in ["mint", "transfer"]:
            return self._extract_op_return_first_position_only(tx)
        else:
            return self._extract_op_return_any_position(tx)

    def _extract_op_return_first_position_only(
        self, tx: Dict[str, Any]
    ) -> Tuple[Optional[str], Optional[int]]:
        """
        Extract OP_RETURN data from FIRST output only (for mint/transfer)

        CRITICAL RULE: OP_RETURN must be in the first output (vout index 0)
        """
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
            1
            for vout in outputs
            if isinstance(vout, dict)
            and vout.get("scriptPubKey", {}).get("type") == "nulldata"
        )

        if op_return_count != 1:
            return None, None

        # Extract the actual data from first OP_RETURN
        op_return_data = extract_op_return_data(hex_script)
        if op_return_data is None:
            return None, None

        # Check size limit
        try:
            data_bytes = bytes.fromhex(op_return_data)
            if len(data_bytes) > self.max_op_return_size:
                return None, None
        except ValueError:
            return None, None

        # Return data and vout index (always 0 for first output)
        return op_return_data, 0

    def _extract_op_return_any_position(
        self, tx: Dict[str, Any]
    ) -> Tuple[Optional[str], Optional[int]]:
        """
        Extract OP_RETURN data from any position (for deploy operations)

        This is the existing behavior for deploy operations
        """
        # Use existing logic for deploy operations
        return self.extract_op_return_data(tx)

    def parse_brc20_operation(self, hex_data: str) -> Dict[str, Any]:
        """
        Parse hex payload to BRC-20 JSON

        Args:
            hex_data: Hex-encoded OP_RETURN data

        Returns:
            Dict with keys:
            - success: bool
            - data: dict (if success=True)
            - error_code: str (if success=False)
            - error_message: str (if success=False)

        RULES:
        - Hex must decode to valid JSON
        - JSON must start with {"p":"brc-20"
        - All required fields must be present
        """
        if not isinstance(hex_data, str):
            return {
                "success": False,
                "error_code": BRC20ErrorCodes.INVALID_JSON,
                "error_message": "Invalid hex data format",
            }

        try:
            # Decode hex to bytes
            data_bytes = bytes.fromhex(hex_data)
        except ValueError:
            return {
                "success": False,
                "error_code": BRC20ErrorCodes.INVALID_JSON,
                "error_message": "Invalid hex encoding",
            }

        try:
            # Decode bytes to UTF-8 string
            json_str = data_bytes.decode("utf-8")
        except UnicodeDecodeError:
            return {
                "success": False,
                "error_code": BRC20ErrorCodes.INVALID_JSON,
                "error_message": "Invalid UTF-8 encoding",
            }

        try:
            # Parse JSON
            operation = json.loads(json_str)
        except json.JSONDecodeError as e:
            return {
                "success": False,
                "error_code": BRC20ErrorCodes.INVALID_JSON,
                "error_message": f"Invalid JSON: {str(e)}",
            }

        # Validate JSON structure
        is_valid, error_code, error_message = self.validate_json_structure(operation)
        if not is_valid:
            return {
                "success": False,
                "error_code": error_code,
                "error_message": error_message,
            }

        return {"success": True, "data": operation}

    def validate_json_structure(
        self, operation: Dict[str, Any]
    ) -> Tuple[bool, Optional[str], Optional[str]]:
        """
        Validate basic JSON structure

        Args:
            operation: Parsed JSON operation

        Returns:
            Tuple[bool, Optional[str], Optional[str]]: (is_valid, error_code,
                error_message)

        RULES:
        - p MUST be "brc-20"
        - op MUST be "deploy", "mint" or "transfer"
        - tick MUST be present and non-empty
        - Required fields according to operation
        """
        if not isinstance(operation, dict):
            return (
                False,
                BRC20ErrorCodes.INVALID_JSON,
                "Operation must be a JSON object",
            )

        # Check protocol field
        protocol = operation.get("p")
        if protocol is None:
            return False, BRC20ErrorCodes.MISSING_PROTOCOL, "Missing protocol field 'p'"

        if protocol != "brc-20":
            return (
                False,
                BRC20ErrorCodes.INVALID_PROTOCOL,
                f"Invalid protocol: {protocol}, expected 'brc-20'",
            )

        # Check operation field
        op = operation.get("op")
        if op is None:
            return (
                False,
                BRC20ErrorCodes.MISSING_OPERATION,
                "Missing operation field 'op'",
            )

        valid_operations = ["deploy", "mint", "transfer"]
        if op not in valid_operations:
            return (
                False,
                BRC20ErrorCodes.INVALID_OPERATION,
                f"Invalid operation: {op}, expected one of " f"{valid_operations}",
            )

        # Check ticker field
        ticker = operation.get("tick")
        if ticker is None:
            return False, BRC20ErrorCodes.MISSING_TICKER, "Missing ticker field 'tick'"

        # Validate ticker format
        if not self.validate_ticker_format(ticker):
            return False, BRC20ErrorCodes.EMPTY_TICKER, "Ticker cannot be empty"

        # Validate operation-specific fields
        if op == "deploy":
            return self._validate_deploy_fields(operation)
        elif op == "mint":
            return self._validate_mint_fields(operation)
        elif op == "transfer":
            return self._validate_transfer_fields(operation)

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

        # CRITICAL RULE: Empty string is invalid, but "0" is valid
        if ticker == "":
            return False

        # Any non-empty string is valid (size checked at OP_RETURN level)
        return True

    def _validate_deploy_fields(
        self, operation: Dict[str, Any]
    ) -> Tuple[bool, Optional[str], Optional[str]]:
        """Validate deploy operation fields"""
        # Check for invalid mixed formats
        has_m_format = "m" in operation
        has_l_format = "l" in operation
        has_max_format = "max" in operation
        has_lim_format = "lim" in operation
        
        if has_m_format and has_lim_format:
            return False, BRC20ErrorCodes.INVALID_AMOUNT, "Cannot use 'm' with 'lim' fields"
        
        if has_max_format and has_l_format:
            return False, BRC20ErrorCodes.INVALID_AMOUNT, "Cannot use 'max' with 'l' fields"
        
        # Use m/l format (preferred) or max/lim format (legacy)
        if has_m_format:
            max_supply = operation.get("m")
            limit_per_op = operation.get("l")
        elif has_max_format:
            max_supply = operation.get("max")
            limit_per_op = operation.get("lim")
        else:
            return False, BRC20ErrorCodes.INVALID_AMOUNT, "Missing max supply field (use 'm' or 'max')"

        if not isinstance(max_supply, str):
            return (
                False,
                BRC20ErrorCodes.INVALID_AMOUNT,
                "Max supply must be string",
            )

        if limit_per_op is not None and not isinstance(limit_per_op, str):
            return (
                False,
                BRC20ErrorCodes.INVALID_AMOUNT,
                "Limit per operation must be string",
            )

        return True, None, None

    def _validate_mint_fields(
        self, operation: Dict[str, Any]
    ) -> Tuple[bool, Optional[str], Optional[str]]:
        """Validate mint operation fields"""
        # Required: amount
        amount = operation.get("amt")
        if amount is None:
            return False, BRC20ErrorCodes.INVALID_AMOUNT, "Missing amount field 'amt'"

        if not isinstance(amount, str):
            return False, BRC20ErrorCodes.INVALID_AMOUNT, "Amount 'amt' must be string"

        return True, None, None

    def _validate_transfer_fields(
        self, operation: Dict[str, Any]
    ) -> Tuple[bool, Optional[str], Optional[str]]:
        """Validate transfer operation fields"""
        # Required: amount
        amount = operation.get("amt")
        if amount is None:
            return False, BRC20ErrorCodes.INVALID_AMOUNT, "Missing amount field 'amt'"

        if not isinstance(amount, str):
            return False, BRC20ErrorCodes.INVALID_AMOUNT, "Amount 'amt' must be string"

        return True, None, None

    def parse_transaction(self, tx: Dict[str, Any]) -> Dict[str, Any]:
        """
        Parse complete transaction for BRC-20 operations

        Args:
            tx: Transaction data from Bitcoin RPC

        Returns:
            Dict with parsing results
        """
        result = {
            "has_brc20": False,
            "op_return_data": None,
            "vout_index": None,
            "operation": None,
            "error_code": None,
            "error_message": None,
        }

        # Extract OP_RETURN data
        hex_data, vout_index = self.extract_op_return_data(tx)

        if hex_data is None:
            # No valid OP_RETURN found (could be multiple or invalid)
            if self._has_multiple_op_returns(tx):
                result["error_code"] = BRC20ErrorCodes.MULTIPLE_OP_RETURNS
                result["error_message"] = "Multiple OP_RETURN outputs found"
            return result

        result["op_return_data"] = hex_data
        result["vout_index"] = vout_index

        # Parse BRC-20 operation
        parse_result = self.parse_brc20_operation(hex_data)

        if parse_result["success"]:
            result["has_brc20"] = True
            result["operation"] = parse_result["data"]
        else:
            result["error_code"] = parse_result["error_code"]
            result["error_message"] = parse_result["error_message"]

        return result

    def _has_multiple_op_returns(self, tx: Dict[str, Any]) -> bool:
        """Check if transaction has multiple OP_RETURN outputs"""
        if not isinstance(tx, dict) or "vout" not in tx:
            return False

        op_return_count = 0
        for vout in tx["vout"]:
            if not isinstance(vout, dict):
                continue

            script_pub_key = vout.get("scriptPubKey", {})
            if (
                isinstance(script_pub_key, dict)
                and script_pub_key.get("type") == "nulldata"
            ):
                op_return_count += 1

        return op_return_count > 1
