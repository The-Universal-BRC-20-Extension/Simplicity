import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "src"))
from src.services.parser import BRC20Parser  # noqa: E402
from src.utils.exceptions import BRC20ErrorCodes  # noqa: E402

"""
Tests for BRC-20 parser functionality.
"""


class TestBRC20Parser:
    """Test BRC-20 parsing functionality"""

    def setup_method(self):
        """Setup test fixtures"""
        self.parser = BRC20Parser()

        self.valid_deploy_hex = (
            "7b2270223a226272632d3230222c226f70223a226465"
            "706c6f79222c227469636b223a224f505154222c226d22"
            "3a223231303030303030222c226c223a2231303030227d"
        )

        self.valid_mint_hex = (
            "7b2270223a226272632d3230222c226f70223a226d696e"
            "74222c227469636b223a224f505154222c22616d74223a"
            "22353030227d"
        )

        self.valid_transfer_hex = (
            "7b2270223a226272632d3230222c226f70223a22747261"
            "6e73666572222c227469636b223a224f505154222c2261"
            "6d74223a22323530227d"
        )
        # {"p":"brc-20","op":"transfer","tick":"OPQT","amt":"250"}

        # Invalid payloads
        self.invalid_json_hex = "7b2270223a226272632d32302c226f70223a22" "6465706c6f79227d"  # Malformed JSON
        self.empty_ticker_hex = (
            "7b2270223a226272632d3230222c226f70223a22646570"
            "6c6f79222c227469636b223a22222c226d223a22323130"
            "3030303030227d"
        )  # ticker=""

        # Valid ticker "0" test
        self.zero_ticker_hex = (
            "7b2270223a226272632d3230222c226f70223a22646570"
            "6c6f79222c227469636b223a2230222c226d223a223231"
            "303030303030227d"
        )
        # {"p":"brc-20","op":"deploy","tick":"0","m":"21000000"}

        # Create proper OP_RETURN scripts
        self.valid_deploy_script = self._create_op_return_script(self.valid_deploy_hex)
        self.valid_mint_script = self._create_op_return_script(self.valid_mint_hex)
        self.valid_transfer_script = self._create_op_return_script(self.valid_transfer_hex)
        self.invalid_json_script = self._create_op_return_script(self.invalid_json_hex)
        self.empty_ticker_script = self._create_op_return_script(self.empty_ticker_hex)
        self.zero_ticker_script = self._create_op_return_script(self.zero_ticker_hex)

    def _create_op_return_script(self, data_hex: str) -> str:
        """Create proper OP_RETURN script with correct length"""
        data_length = len(data_hex) // 2
        return f"6a{data_length:02x}{data_hex}"

    def test_extract_op_return_valid_single(self):
        """Test valid OP_RETURN extraction with single output"""
        tx = {
            "vout": [
                {
                    "scriptPubKey": {
                        "type": "pubkeyhash",
                        "hex": "76a914...",
                        "addresses": ["1A1zP1eP5QGefi2DMPTfTL5SLmv7DivfNa"],
                    }
                },
                {"scriptPubKey": {"type": "nulldata", "hex": self.valid_deploy_script}},
            ]
        }

        hex_data, vout_index = self.parser.extract_op_return_data(tx)

        assert hex_data == self.valid_deploy_hex
        assert vout_index == 1

    def test_extract_op_return_multiple_rejection(self):
        """Test multiple OP_RETURN rejection - CRITICAL RULE"""
        tx = {
            "vout": [
                {
                    "scriptPubKey": {
                        "type": "nulldata",
                        "hex": f"6a4c50{self.valid_deploy_hex}",
                    }
                },
                {
                    "scriptPubKey": {
                        "type": "nulldata",
                        "hex": f"6a4c50{self.valid_mint_hex}",
                    }
                },
            ]
        }

        hex_data, vout_index = self.parser.extract_op_return_data(tx)

        assert hex_data is None
        assert vout_index is None

    def test_extract_op_return_no_op_return(self):
        """Test transaction with no OP_RETURN"""
        tx = {
            "vout": [
                {
                    "scriptPubKey": {
                        "type": "pubkeyhash",
                        "hex": "76a914...",
                        "addresses": ["1A1zP1eP5QGefi2DMPTfTL5SLmv7DivfNa"],
                    }
                }
            ]
        }

        hex_data, vout_index = self.parser.extract_op_return_data(tx)

        assert hex_data is None
        assert vout_index is None

    def test_parse_valid_deploy(self):
        """Test valid deploy parsing"""
        result = self.parser.parse_brc20_operation(self.valid_deploy_hex)

        assert result["success"] is True
        assert "data" in result

        operation = result["data"]
        assert operation["p"] == "brc-20"
        assert operation["op"] == "deploy"
        assert operation["tick"] == "OPQT"
        assert operation["m"] == "21000000"
        assert operation["l"] == "1000"

    def test_parse_valid_mint(self):
        """Test valid mint parsing"""
        result = self.parser.parse_brc20_operation(self.valid_mint_hex)

        assert result["success"] is True
        assert "data" in result

        operation = result["data"]
        assert operation["p"] == "brc-20"
        assert operation["op"] == "mint"
        assert operation["tick"] == "OPQT"
        assert operation["amt"] == "500"

    def test_parse_valid_transfer(self):
        """Test valid transfer parsing"""
        result = self.parser.parse_brc20_operation(self.valid_transfer_hex)

        assert result["success"] is True
        assert "data" in result

        operation = result["data"]
        assert operation["p"] == "brc-20"
        assert operation["op"] == "transfer"
        assert operation["tick"] == "OPQT"
        assert operation["amt"] == "250"

    def test_parse_invalid_json(self):
        """Test malformed JSON rejection"""
        result = self.parser.parse_brc20_operation(self.invalid_json_hex)

        assert result["success"] is False
        assert result["error_code"] == BRC20ErrorCodes.INVALID_PROTOCOL
        assert "Not a BRC-20 operation" in result["error_message"]

    def test_parse_empty_ticker_invalid(self):
        """Test empty ticker rejection - CRITICAL RULE"""
        result = self.parser.parse_brc20_operation(self.empty_ticker_hex)

        assert result["success"] is False
        assert result["error_code"] == BRC20ErrorCodes.EMPTY_TICKER
        assert "Ticker cannot be empty" in result["error_message"]

    def test_parse_zero_ticker_valid(self):
        """Test ticker '0' is valid - CRITICAL RULE"""
        result = self.parser.parse_brc20_operation(self.zero_ticker_hex)

        assert result["success"] is True
        assert "data" in result

        operation = result["data"]
        assert operation["tick"] == "0"

    def test_validate_ticker_format(self):
        """Test ticker format validation"""
        # Valid tickers
        assert self.parser.validate_ticker_format("OPQT") is True
        assert self.parser.validate_ticker_format("0") is True
        assert self.parser.validate_ticker_format("bitcoin") is True
        assert self.parser.validate_ticker_format("1") is True

        # Invalid tickers
        assert self.parser.validate_ticker_format("") is False
        assert self.parser.validate_ticker_format(None) is False
        assert self.parser.validate_ticker_format(123) is False

    def test_validate_json_structure_missing_protocol(self):
        """Test missing protocol field"""
        operation = {"op": "deploy", "tick": "TEST", "m": "1000"}

        is_valid, error_code, error_message = self.parser.validate_json_structure(operation)

        assert is_valid is False
        assert error_code == BRC20ErrorCodes.MISSING_PROTOCOL

    def test_validate_json_structure_invalid_protocol(self):
        """Test invalid protocol field"""
        operation = {"p": "brc-21", "op": "deploy", "tick": "TEST", "m": "1000"}

        is_valid, error_code, error_message = self.parser.validate_json_structure(operation)

        assert is_valid is False
        assert error_code == BRC20ErrorCodes.INVALID_PROTOCOL

    def test_validate_json_structure_missing_operation(self):
        """Test missing operation field"""
        operation = {"p": "brc-20", "tick": "TEST", "m": "1000"}

        is_valid, error_code, error_message = self.parser.validate_json_structure(operation)

        assert is_valid is False
        assert error_code == BRC20ErrorCodes.MISSING_OPERATION

    def test_validate_json_structure_invalid_operation(self):
        """Test invalid operation field"""
        operation = {"p": "brc-20", "op": "burn", "tick": "TEST", "m": "1000"}

        is_valid, error_code, error_message = self.parser.validate_json_structure(operation)

        assert is_valid is False
        assert error_code == BRC20ErrorCodes.INVALID_OPERATION

    def test_validate_json_structure_missing_ticker(self):
        """Test missing ticker field"""
        operation = {"p": "brc-20", "op": "deploy", "m": "1000"}

        is_valid, error_code, error_message = self.parser.validate_json_structure(operation)

        assert is_valid is False
        assert error_code == BRC20ErrorCodes.MISSING_TICKER

    def test_validate_deploy_fields_missing_max_supply(self):
        """Test deploy missing max supply"""
        operation = {"p": "brc-20", "op": "deploy", "tick": "TEST"}

        is_valid, error_code, error_message = self.parser.validate_json_structure(operation)

        assert is_valid is False
        assert error_code == BRC20ErrorCodes.INVALID_AMOUNT
        assert "Missing max supply" in error_message

    def test_validate_deploy_fields_invalid_max_supply_type(self):
        """Test deploy with non-string max supply"""
        operation = {"p": "brc-20", "op": "deploy", "tick": "TEST", "m": 1000}

        is_valid, error_code, error_message = self.parser.validate_json_structure(operation)

        assert is_valid is False
        assert error_code == BRC20ErrorCodes.INVALID_AMOUNT
        assert "must be string" in error_message

    def test_validate_mint_fields_missing_amount(self):
        """Test mint missing amount"""
        operation = {"p": "brc-20", "op": "mint", "tick": "TEST"}

        is_valid, error_code, error_message = self.parser.validate_json_structure(operation)

        assert is_valid is False
        assert error_code == BRC20ErrorCodes.INVALID_AMOUNT
        assert "Missing amount" in error_message

    def test_validate_transfer_fields_missing_amount(self):
        """Test transfer missing amount"""
        operation = {"p": "brc-20", "op": "transfer", "tick": "TEST"}

        is_valid, error_code, error_message = self.parser.validate_json_structure(operation)

        assert is_valid is False
        assert error_code == BRC20ErrorCodes.INVALID_AMOUNT
        assert "Missing amount" in error_message

    def test_parse_transaction_complete_valid(self):
        """Test complete transaction parsing"""
        tx = {
            "vout": [
                {
                    "scriptPubKey": {
                        "type": "pubkeyhash",
                        "hex": "76a914...",
                        "addresses": ["1A1zP1eP5QGefi2DMPTfTL5SLmv7DivfNa"],
                    }
                },
                {"scriptPubKey": {"type": "nulldata", "hex": self.valid_deploy_script}},
            ]
        }

        result = self.parser.parse_transaction(tx)

        assert result["has_brc20"] is True
        assert result["op_return_data"] == self.valid_deploy_hex
        assert result["vout_index"] == 1
        assert result["operation"] is not None
        assert result["operation"]["op"] == "deploy"
        assert result["error_code"] is None

    def test_parse_transaction_multiple_op_returns(self):
        """Test transaction with multiple OP_RETURN outputs"""
        tx = {
            "vout": [
                {
                    "scriptPubKey": {
                        "type": "nulldata",
                        "hex": f"6a4c50{self.valid_deploy_hex}",
                    }
                },
                {
                    "scriptPubKey": {
                        "type": "nulldata",
                        "hex": f"6a4c50{self.valid_mint_hex}",
                    }
                },
            ]
        }

        result = self.parser.parse_transaction(tx)

        assert result["has_brc20"] is False
        assert result["error_code"] == BRC20ErrorCodes.MULTIPLE_OP_RETURNS
        assert "Multiple OP_RETURN" in result["error_message"]

    def test_parse_transaction_invalid_brc20(self):
        """Test transaction with invalid BRC-20 data"""
        tx = {
            "vout": [
                {
                    "scriptPubKey": {
                        "type": "pubkeyhash",
                        "hex": "76a914...",
                        "addresses": ["1A1zP1eP5QGefi2DMPTfTL5SLmv7DivfNa"],
                    }
                },
                {"scriptPubKey": {"type": "nulldata", "hex": self.invalid_json_script}},
            ]
        }

        result = self.parser.parse_transaction(tx)

        assert result["has_brc20"] is False
        assert result["op_return_data"] is None
        assert result["vout_index"] is None
        assert result["operation"] is None
        assert result["error_code"] is None

    def test_parse_transaction_no_op_return(self):
        """Test transaction with no OP_RETURN"""
        tx = {
            "vout": [
                {
                    "scriptPubKey": {
                        "type": "pubkeyhash",
                        "hex": "76a914...",
                        "addresses": ["1A1zP1eP5QGefi2DMPTfTL5SLmv7DivfNa"],
                    }
                }
            ]
        }

        result = self.parser.parse_transaction(tx)

        assert result["has_brc20"] is False
        assert result["op_return_data"] is None
        assert result["vout_index"] is None
        assert result["operation"] is None
        assert result["error_code"] is None  # No error, just no BRC-20 data

    def test_op_return_size_limit(self):
        """Test OP_RETURN size limit enforcement"""
        large_data = "a" * 100
        large_hex = large_data.encode("utf-8").hex()

        tx = {"vout": [{"scriptPubKey": {"type": "nulldata", "hex": f"6a4c64{large_hex}"}}]}

        hex_data, vout_index = self.parser.extract_op_return_data(tx)

        assert hex_data is None
        assert vout_index is None

    def test_extract_op_return_first_position_valid_mint(self):
        """Test OP_RETURN in first position for mint (valid)"""
        tx = {
            "vout": [
                {"scriptPubKey": {"type": "nulldata", "hex": self.valid_mint_script}},
                {
                    "scriptPubKey": {
                        "type": "pubkeyhash",
                        "hex": "76a914...",
                        "addresses": ["1A1zP1eP5QGefi2DMPTfTL5SLmv7DivfNa"],
                    }
                },
            ]
        }

        hex_data, vout_index = self.parser.extract_op_return_data_with_position_check(tx, "mint")

        assert hex_data == self.valid_mint_hex
        assert vout_index == 0

    def test_extract_op_return_first_position_valid_transfer(self):
        """Test OP_RETURN in first position for transfer (valid)"""
        tx = {
            "vout": [
                {
                    "scriptPubKey": {
                        "type": "nulldata",
                        "hex": self.valid_transfer_script,
                    }
                },
                {
                    "scriptPubKey": {
                        "type": "pubkeyhash",
                        "hex": "76a914...",
                        "addresses": ["1A1zP1eP5QGefi2DMPTfTL5SLmv7DivfNa"],
                    }
                },
            ]
        }

        hex_data, vout_index = self.parser.extract_op_return_data_with_position_check(tx, "transfer")

        assert hex_data == self.valid_transfer_hex
        assert vout_index == 0

    def test_deploy_op_return_any_position_still_valid(self):
        """Test that deploy operations can still have OP_RETURN in any position"""
        tx = {
            "vout": [
                {
                    "scriptPubKey": {
                        "type": "pubkeyhash",
                        "hex": "76a914...",
                        "addresses": ["1A1zP1eP5QGefi2DMPTfTL5SLmv7DivfNa"],
                    }
                },
                {"scriptPubKey": {"type": "nulldata", "hex": self.valid_deploy_script}},
            ]
        }

        hex_data, vout_index = self.parser.extract_op_return_data_with_position_check(tx, "deploy")

        assert hex_data == self.valid_deploy_hex
        assert vout_index == 1

    def test_extract_op_return_second_position_invalid_mint(self):
        """Test OP_RETURN in second position for mint (invalid)"""
        tx = {
            "vout": [
                {
                    "scriptPubKey": {
                        "type": "pubkeyhash",
                        "hex": "76a914...",
                        "addresses": ["1A1zP1eP5QGefi2DMPTfTL5SLmv7DivfNa"],
                    }
                },
                {"scriptPubKey": {"type": "nulldata", "hex": self.valid_mint_script}},
            ]
        }

        hex_data, vout_index = self.parser.extract_op_return_data_with_position_check(tx, "mint")

        assert hex_data is None
        assert vout_index is None

    def test_extract_op_return_second_position_invalid_transfer(self):
        """Test OP_RETURN in second position for transfer (invalid)"""
        tx = {
            "vout": [
                {
                    "scriptPubKey": {
                        "type": "pubkeyhash",
                        "hex": "76a914...",
                        "addresses": ["1A1zP1eP5QGefi2DMPTfTL5SLmv7DivfNa"],
                    }
                },
                {
                    "scriptPubKey": {
                        "type": "nulldata",
                        "hex": self.valid_transfer_script,
                    }
                },
            ]
        }

        hex_data, vout_index = self.parser.extract_op_return_data_with_position_check(tx, "transfer")

        assert hex_data is None
        assert vout_index is None

    def test_extract_op_return_third_position_invalid(self):
        """Test OP_RETURN in third position (invalid)"""
        tx = {
            "vout": [
                {
                    "scriptPubKey": {
                        "type": "pubkeyhash",
                        "hex": "76a914...",
                        "addresses": ["1A1zP1eP5QGefi2DMPTfTL5SLmv7DivfNa"],
                    }
                },
                {
                    "scriptPubKey": {
                        "type": "pubkeyhash",
                        "hex": "76a914...",
                        "addresses": ["1A1zP1eP5QGefi2DMPTfTL5SLmv7DivfNa"],
                    }
                },
                {"scriptPubKey": {"type": "nulldata", "hex": self.valid_deploy_script}},
            ]
        }

        hex_data, vout_index = self.parser.extract_op_return_data_with_position_check(tx, "deploy")

        assert hex_data == self.valid_deploy_hex
        assert vout_index == 2

    def test_extract_op_return_multiple_with_first_invalid(self):
        """Test multiple OP_RETURN with first position still invalid"""
        tx = {
            "vout": [
                {"scriptPubKey": {"type": "nulldata", "hex": self.valid_deploy_script}},
                {"scriptPubKey": {"type": "nulldata", "hex": self.valid_mint_script}},
            ]
        }

        hex_data, vout_index = self.parser.extract_op_return_data_with_position_check(tx, "mint")

        assert hex_data is None
        assert vout_index is None
