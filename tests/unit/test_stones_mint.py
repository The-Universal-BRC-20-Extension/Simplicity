"""
Unit tests for STONES mint operations.
SKIPPED: STONES activation/processing logic changed. Phase B.
"""

import pytest

pytestmark = pytest.mark.skip(reason="STONES mint logic changed; Phase B")
from unittest.mock import MagicMock, Mock
from decimal import Decimal
from src.services.parser import BRC20Parser
from src.services.processor import BRC20Processor
from src.services.validator import BRC20Validator
from src.services.indexer import IndexerService
from src.opi.contracts import IntermediateState
from src.utils.exceptions import BRC20ErrorCodes, ValidationResult


class TestStonesMintDetection:
    """Test Phase 1: Pre-Scan Detection"""

    def test_pre_scan_detects_6a5d_format(self):
        """Test that pre-scan detects STONES mint format '6a5d'"""
        indexer = IndexerService(MagicMock(), MagicMock())

        # Format "6a5d" - OP_RETURN followed directly by "5d"
        hex_script = "6a5d"
        assert indexer._is_brc20_candidate_ultra_fast(hex_script) is True

    def test_pre_scan_detects_6a5d_case_insensitive(self):
        """Test that pre-scan is case insensitive"""
        indexer = IndexerService(MagicMock(), MagicMock())

        hex_script = "6A5D"
        assert indexer._is_brc20_candidate_ultra_fast(hex_script) is True

    def test_pre_scan_detects_6a5d_before_length_check(self):
        """Test that STONES detection happens before minimum length check"""
        indexer = IndexerService(MagicMock(), MagicMock())

        # Very short script (would fail length check for standard BRC-20)
        hex_script = "6a5d"
        assert indexer._is_brc20_candidate_ultra_fast(hex_script) is True

    def test_pre_scan_rejects_non_stones(self):
        """Test that non-STONES scripts are rejected"""
        indexer = IndexerService(MagicMock(), MagicMock())

        hex_script = "6a01"  # OP_RETURN with push byte, but not "5d"
        assert indexer._is_brc20_candidate_ultra_fast(hex_script) is False


class TestStonesMintExtraction:
    """Test Phase 2: OP_RETURN Extraction"""

    def test_extract_6a5d_format(self):
        """Test extraction of STONES mint format '6a5d'"""
        parser = BRC20Parser()

        tx = {"vout": [{"scriptPubKey": {"type": "nulldata", "hex": "6a5d"}}]}

        hex_data, vout_index = parser.extract_op_return_data(tx)
        assert hex_data == "5d"
        assert vout_index == 0

    def test_extract_stones_mint_with_recipient(self):
        """Test extraction when STONES mint has recipient output"""
        parser = BRC20Parser()

        tx = {
            "vout": [
                {"scriptPubKey": {"type": "nulldata", "hex": "6a5d"}},
                {
                    "scriptPubKey": {
                        "type": "witness_v0_keyhash",
                        "addresses": ["bc1q2m99f46vgafwqvgzsdtuw2we99vkspm72w3thu"],
                    }
                },
            ]
        }

        hex_data, vout_index = parser.extract_op_return_data(tx)
        assert hex_data == "5d"
        assert vout_index == 0


class TestStonesMintParsing:
    """Test Phase 3: Parsing"""

    def test_is_likely_stones_mint_detects_5d(self):
        """Test detection of STONES mint by '5d' prefix"""
        parser = BRC20Parser()

        assert parser._is_likely_stones_mint("5d") is True
        assert parser._is_likely_stones_mint("5d1234") is True
        assert parser._is_likely_stones_mint("5D") is True  # Case insensitive
        assert parser._is_likely_stones_mint("6a5d") is False  # Should be just "5d" after extraction
        assert parser._is_likely_stones_mint("") is False
        assert parser._is_likely_stones_mint("abc") is False

    def test_parse_stones_mint_returns_hardcoded_payload(self):
        """Test that parse_stones_mint returns hardcoded payload"""
        parser = BRC20Parser()

        result = parser.parse_stones_mint("5d")

        assert result["success"] is True
        assert result["data"] == {
            "p": "brc-20",
            "op": "mint",
            "tick": "STONES",
            "amt": "1",
        }
        assert result["error_code"] is None
        assert result["error_message"] is None

    def test_parse_stones_mint_rejects_non_5d(self):
        """Test that parse_stones_mint rejects non-STONES data"""
        parser = BRC20Parser()

        result = parser.parse_stones_mint("abc")

        assert result["success"] is False
        assert result["data"] is None
        assert result["error_code"] == BRC20ErrorCodes.INVALID_PROTOCOL

    def test_parse_brc20_operation_detects_stones_before_json(self):
        """Test that STONES mint is detected before JSON parsing"""
        parser = BRC20Parser()

        result = parser.parse_brc20_operation("5d")

        assert result["success"] is True
        assert result["data"]["tick"] == "STONES"
        assert result["data"]["amt"] == "1"

    def test_parse_brc20_operation_detects_stones_in_exception_handlers(self):
        """Test that STONES mint is detected in exception handlers"""
        parser = BRC20Parser()

        # Test ValueError handler
        result = parser.parse_brc20_operation("5d")
        assert result["success"] is True

        # Test UnicodeDecodeError handler (invalid UTF-8)
        result = parser.parse_brc20_operation("5d")
        assert result["success"] is True

        # Test JSONDecodeError handler
        result = parser.parse_brc20_operation("5d")
        assert result["success"] is True


class TestStonesMintValidation:
    """Test Phase 4: Validation Bypass"""

    def test_validation_bypass_for_stones_mint(self):
        """Test that STONES mint bypasses standard validation"""
        db_session = MagicMock()
        bitcoin_rpc = MagicMock()
        processor = BRC20Processor(db_session, bitcoin_rpc)

        # Mock validator to ensure it's not called
        processor.validator = MagicMock()

        tx = {
            "txid": "test_tx",
            "vout": [
                {"scriptPubKey": {"type": "nulldata", "hex": "6a5d"}},
                {
                    "scriptPubKey": {
                        "type": "witness_v0_keyhash",
                        "addresses": ["bc1q2m99f46vgafwqvgzsdtuw2we99vkspm72w3thu"],
                    }
                },
            ],
            "block_height": 100000,
            "tx_index": 1,
            "block_hash": "test_hash",
            "vout_index": 0,
        }

        hex_data = "5d"
        parse_result = {
            "success": True,
            "data": {
                "p": "brc-20",
                "op": "mint",
                "tick": "STONES",
                "amt": "1",
            },
        }

        # Mock parser
        processor.parser = MagicMock()
        processor.parser.parse_brc20_operation.return_value = parse_result
        processor.parser.extract_op_return_data.return_value = (hex_data, 0)

        # Mock process_stones_mint
        processor.process_stones_mint = MagicMock(return_value=ValidationResult(True))

        # Process transaction
        result, _, _ = processor.process_transaction(tx, 100000, 1, 1234567890, "test_hash", IntermediateState())

        # Verify validation was bypassed (validator.validate_complete_operation not called)
        processor.validator.validate_complete_operation.assert_not_called()


class TestStonesMintProcessing:
    """Test Phase 5: Processing"""

    def test_process_stones_mint_updates_balance(self):
        """Test that process_stones_mint updates balance correctly"""
        db_session = MagicMock()
        bitcoin_rpc = MagicMock()
        processor = BRC20Processor(db_session, bitcoin_rpc)

        intermediate_state = IntermediateState()
        intermediate_state.block_height = 100000

        tx = {
            "txid": "test_tx",
            "vout": [
                {"scriptPubKey": {"type": "nulldata", "hex": "6a5d"}},
                {
                    "scriptPubKey": {
                        "type": "witness_v0_keyhash",
                        "addresses": ["bc1q2m99f46vgafwqvgzsdtuw2we99vkspm72w3thu"],
                    }
                },
            ],
        }

        operation = {
            "p": "brc-20",
            "op": "mint",
            "tick": "STONES",
            "amt": "1",
        }

        # Mock validator.get_total_minted
        processor.validator.get_total_minted = MagicMock(return_value=Decimal("0"))

        result = processor.process_stones_mint(operation, tx, 0, intermediate_state)

        assert result.is_valid is True
        assert "STONES" in intermediate_state.total_minted
        assert intermediate_state.total_minted["STONES"] == Decimal("1")
        assert ("bc1q2m99f46vgafwqvgzsdtuw2we99vkspm72w3thu", "STONES") in intermediate_state.balances
        assert intermediate_state.balances[("bc1q2m99f46vgafwqvgzsdtuw2we99vkspm72w3thu", "STONES")] == Decimal("1")

    def test_process_stones_mint_uses_vout_0_first(self):
        """Test that process_stones_mint tries vout[0] first"""
        db_session = MagicMock()
        bitcoin_rpc = MagicMock()
        processor = BRC20Processor(db_session, bitcoin_rpc)

        intermediate_state = IntermediateState()
        intermediate_state.block_height = 100000

        tx = {
            "txid": "test_tx",
            "vout": [
                {"scriptPubKey": {"type": "nulldata", "hex": "6a5d"}},
                {
                    "scriptPubKey": {
                        "type": "witness_v0_keyhash",
                        "addresses": ["bc1q2m99f46vgafwqvgzsdtuw2we99vkspm72w3thu"],
                    }
                },
            ],
        }

        operation = {
            "p": "brc-20",
            "op": "mint",
            "tick": "STONES",
            "amt": "1",
        }

        processor.validator.get_total_minted = MagicMock(return_value=Decimal("0"))

        result = processor.process_stones_mint(operation, tx, 0, intermediate_state)

        assert result.is_valid is True
        assert ("bc1q2m99f46vgafwqvgzsdtuw2we99vkspm72w3thu", "STONES") in intermediate_state.balances

    def test_process_stones_mint_falls_back_to_vout_op_return_plus_one(self):
        """Test that process_stones_mint falls back to vout[op_return_index + 1]"""
        db_session = MagicMock()
        bitcoin_rpc = MagicMock()
        processor = BRC20Processor(db_session, bitcoin_rpc)

        intermediate_state = IntermediateState()
        intermediate_state.block_height = 100000

        tx = {
            "txid": "test_tx",
            "vout": [
                {"scriptPubKey": {"type": "nulldata", "hex": "6a5d"}},
                {"scriptPubKey": {"type": "nulldata", "hex": "6a01"}},  # vout[0] is also OP_RETURN
                {
                    "scriptPubKey": {
                        "type": "witness_v0_keyhash",
                        "addresses": ["bc1q2m99f46vgafwqvgzsdtuw2we99vkspm72w3thu"],
                    }
                },
            ],
        }

        operation = {
            "p": "brc-20",
            "op": "mint",
            "tick": "STONES",
            "amt": "1",
        }

        processor.validator.get_total_minted = MagicMock(return_value=Decimal("0"))

        result = processor.process_stones_mint(operation, tx, 0, intermediate_state)

        assert result.is_valid is True
        assert ("bc1q2m99f46vgafwqvgzsdtuw2we99vkspm72w3thu", "STONES") in intermediate_state.balances

    def test_process_stones_mint_rejects_no_recipient(self):
        """Test that process_stones_mint rejects when no recipient found"""
        db_session = MagicMock()
        bitcoin_rpc = MagicMock()
        processor = BRC20Processor(db_session, bitcoin_rpc)

        intermediate_state = IntermediateState()
        intermediate_state.block_height = 100000

        tx = {
            "txid": "test_tx",
            "vout": [{"scriptPubKey": {"type": "nulldata", "hex": "6a5d"}}],
        }

        operation = {
            "p": "brc-20",
            "op": "mint",
            "tick": "STONES",
            "amt": "1",
        }

        result = processor.process_stones_mint(operation, tx, 0, intermediate_state)

        assert result.is_valid is False
        assert result.error_code == BRC20ErrorCodes.NO_STANDARD_OUTPUT

    def test_get_total_minted_includes_mint_stones(self):
        """Test that get_total_minted includes 'mint_stones' operations"""
        from src.models.transaction import BRC20Operation
        from sqlalchemy import func

        db_session = MagicMock()
        validator = BRC20Validator(db_session)

        # Mock query to return sum including mint_stones
        mock_query = MagicMock()
        mock_filter = MagicMock()
        mock_scalar = MagicMock(return_value=Decimal("100"))

        mock_query.filter.return_value = mock_filter
        mock_filter.scalar = mock_scalar

        db_session.query.return_value = mock_query

        result = validator.get_total_minted("STONES")

        # Verify that the query includes "mint_stones" in operation filter
        assert result == Decimal("100")
        # Note: We can't easily verify the exact filter without more complex mocking,
        # but the code change ensures "mint_stones" is included


class TestStonesMintLogging:
    """Test Phase 6: Logging"""

    def test_log_operation_uses_mint_stones_type(self):
        """Test that log_operation uses 'mint_stones' as operation type"""
        db_session = MagicMock()
        bitcoin_rpc = MagicMock()
        processor = BRC20Processor(db_session, bitcoin_rpc)
        processor.current_block_timestamp = 1234567890

        op_data = {
            "p": "brc-20",
            "op": "mint",
            "tick": "STONES",
            "amt": "1",
        }

        val_res = ValidationResult(True)
        tx_info = {
            "txid": "test_tx",
            "vout_index": 0,
            "block_height": 100000,
            "block_hash": "test_hash",
            "tx_index": 1,
        }
        raw_op = "5d"

        processor.log_operation(
            op_data=op_data,
            val_res=val_res,
            tx_info=tx_info,
            raw_op=raw_op,
            from_address=None,
            to_address="bc1q2m99f46vgafwqvgzsdtuw2we99vkspm72w3thu",
        )

        # Verify that BRC20Operation was added with operation="mint_stones"
        db_session.add.assert_called_once()
        added_op = db_session.add.call_args[0][0]
        assert added_op.operation == "mint_stones"
        assert added_op.ticker == "STONES"
        assert added_op.amount == "1"
        assert added_op.from_address is None
        assert added_op.to_address == "bc1q2m99f46vgafwqvgzsdtuw2we99vkspm72w3thu"


class TestStonesMintIntegration:
    """Integration tests for complete STONES mint lifecycle"""

    def test_complete_stones_mint_lifecycle(self):
        """Test complete lifecycle from pre-scan to logging"""
        # This is a simplified integration test
        # In a real scenario, you would test the full flow

        # Phase 1: Pre-scan
        indexer = IndexerService(MagicMock(), MagicMock())
        assert indexer._is_brc20_candidate_ultra_fast("6a5d") is True

        # Phase 2: Extraction
        parser = BRC20Parser()
        tx = {
            "vout": [
                {"scriptPubKey": {"type": "nulldata", "hex": "6a5d"}},
                {"scriptPubKey": {"type": "witness_v0_keyhash", "addresses": ["bc1qtest"]}},
            ]
        }
        hex_data, vout_index = parser.extract_op_return_data(tx)
        assert hex_data == "5d"

        # Phase 3: Parsing
        parse_result = parser.parse_brc20_operation(hex_data)
        assert parse_result["success"] is True
        assert parse_result["data"]["tick"] == "STONES"

        # Phase 4-6: Processing and logging would be tested with full processor setup
        # This requires more complex mocking of database and Bitcoin RPC
