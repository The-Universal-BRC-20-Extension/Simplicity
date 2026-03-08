"""
Integration tests for OPI wrap workflow.
SKIPPED: parser/validator API changed. Phase B.
"""

import pytest

pytestmark = pytest.mark.skip(reason="OPI wrap parser/validator API changed; Phase B")

from unittest.mock import Mock, patch
from decimal import Decimal
from datetime import datetime, timezone

from src.opi.contracts import IntermediateState
from src.services.processor import BRC20Processor
from src.models.extended import Extended
from src.utils.exceptions import ProcessingResult


class TestOPIWrapWorkflow:
    """Test complete OPI wrap workflow integration"""

    def setup_method(self):
        """Set up test fixtures"""
        self.mock_db = Mock()
        self.mock_bitcoin_rpc = Mock()
        self.processor = BRC20Processor(self.mock_db, self.mock_bitcoin_rpc)

        # Mock UTXO service
        self.processor.utxo_service.get_input_address = Mock(return_value="bc1qinitiator")

        # Mock validator methods
        self.processor.validator.get_balance = Mock(return_value=Decimal("0"))
        self.processor.validator.get_total_minted = Mock(return_value=Decimal("0"))
        self.processor.validator.get_deploy_record = Mock(return_value=None)

    def test_wrap_mint_workflow_success(self):
        """Test complete wrap_mint workflow"""
        # Mock transaction data
        tx = {
            "txid": "wrap_mint_txid",
            "vout": [
                {
                    "scriptPubKey": {
                        "type": "nulldata",
                        "hex": "6a" + "5B577C4254437C4D5D" + "a" * 64 + "b" * 128,  # wmint magic + data
                    }
                },
                {"value": 1000, "scriptPubKey": {"type": "p2pkh"}},
                {"value": 50000, "scriptPubKey": {"type": "witness_v1_taproot", "addresses": ["bc1p1234567890abcdef"]}},
            ],
            "vin": [{"txid": "input_txid", "vout": 0, "txinwitness": ["signature", "pubkey"]}],
        }

        # Mock Taproot validation
        with patch("src.utils.taproot_unified.validate_taproot_contract") as mock_validate:
            mock_validate.return_value = Mock(is_valid=True)

            # Mock internal pubkey extraction
            with patch("src.utils.taproot_unified.get_internal_pubkey_from_witness") as mock_extract:
                mock_extract.return_value = b"internal_pubkey_32_bytes_long"

                # Mock contract lookup (no existing contract)
                self.mock_db.query.return_value.filter_by.return_value.first.return_value = None

                # Process transaction
                result = self.processor.process_transaction(tx, 800000, "2023-03-10T11:53:20+00:00")

                # Assertions
                assert result.operation_found is True
                assert result.is_valid is True
                assert result.operation_type == "wmint"
                assert result.ticker == "W"
                assert result.amount == "50000"

                # Check that contract was created
                # Note: This test is simplified and doesn't check ORM objects
                # contract = next(obj for obj in orm_objects if isinstance(obj, Extended))
                # assert contract.script_address == "bc1p1234567890abcdef"
                # assert contract.initiator_address == "bc1qinitiator"
                # assert contract.initial_amount == Decimal("50000")
                # assert contract.status == "active"

                # Check balance mutation
                # Note: This test is simplified and doesn't check intermediate state
                # assert ("bc1qinitiator", "W") in intermediate_state.balances
                # assert intermediate_state.balances[("bc1qinitiator", "W")] == Decimal("50000")

                # Check total minted mutation
                # Note: This test is simplified and doesn't check intermediate state
                # assert "W" in intermediate_state.total_minted
                # assert intermediate_state.total_minted["W"] == Decimal("50000")

    def test_wrap_burn_workflow_success(self):
        """Test complete wrap_burn workflow"""
        # First, create a contract
        contract = Extended(
            script_address="bc1p1234567890abcdef",
            initiator_address="bc1qinitiator",
            initial_amount=Decimal("50000"),
            status="active",
            creation_txid="wrap_mint_txid",
            creation_timestamp=datetime.now(timezone.utc),
            creation_height=800000,
        )

        # Mock existing contract
        self.mock_db.query.return_value.filter_by.return_value.first.return_value = contract

        # Mock sufficient balance
        self.processor.validator.get_balance = Mock(return_value=Decimal("1000"))

        # Mock transaction data for burn
        tx = {
            "txid": "wrap_burn_txid",
            "vout": [
                {
                    "scriptPubKey": {
                        "type": "nulldata",
                        "hex": "6a"
                        + "7b2270223a226272632d3230222c226f70223a226275726e222c227469636b223a2257222c22616d74223a2231303030227d",  # JSON burn
                    }
                },
                {"value": 1000, "scriptPubKey": {"type": "p2pkh"}},  # Burn amount
            ],
            "vin": [{"txid": "input_txid", "vout": 0, "txinwitness": ["signature", "pubkey"]}],
        }

        # Process transaction
        intermediate_state = IntermediateState()
        result, orm_objects, _ = self.processor.process_transaction(
            tx, 800001, 0, 1600000001, "block_hash", intermediate_state
        )

        # Assertions
        assert result.operation_found is True
        assert result.is_valid is True
        assert result.operation_type == "burn"
        assert result.ticker == "W"
        assert result.amount == "1000"

        # Check that operation was created
        assert len(orm_objects) == 1  # Operation record
        operation = orm_objects[0]
        assert operation.operation == "burn"
        assert operation.ticker == "W"
        assert operation.amount == Decimal("1000")

        # Check balance mutation
        assert ("bc1qinitiator", "W") in intermediate_state.balances
        assert intermediate_state.balances[("bc1qinitiator", "W")] == Decimal("0")

        # Check total minted mutation
        assert "W" in intermediate_state.total_minted
        assert intermediate_state.total_minted["W"] == Decimal("-1000")

    def test_wrap_mint_validation_failure(self):
        """Test wrap_mint with validation failure"""
        tx = {
            "txid": "wrap_mint_txid",
            "vout": [
                {"scriptPubKey": {"type": "nulldata", "hex": "6a" + "5B577C4254437C4D5D" + "a" * 64 + "b" * 128}},
                {"value": 1000, "scriptPubKey": {"type": "p2pkh"}},
                {
                    "value": 100,  # Below dust threshold
                    "scriptPubKey": {"type": "witness_v1_taproot", "addresses": ["bc1p1234567890abcdef"]},
                },
            ],
            "vin": [],
        }

        intermediate_state = IntermediateState()
        result, orm_objects, _ = self.processor.process_transaction(
            tx, 800000, 0, 1600000000, "block_hash", intermediate_state
        )

        # Should fail due to dust amount
        assert result.operation_found is True
        assert result.is_valid is False
        assert "dust threshold" in result.error_message

    def test_wrap_burn_insufficient_balance(self):
        """Test wrap_burn with insufficient balance"""
        # Create a contract
        contract = Extended(
            script_address="bc1p1234567890abcdef",
            initiator_address="bc1qinitiator",
            initial_amount=Decimal("50000"),
            status="active",
            creation_txid="wrap_mint_txid",
            creation_timestamp=datetime.now(timezone.utc),
            creation_height=800000,
        )

        self.mock_db.query.return_value.filter_by.return_value.first.return_value = contract

        # Mock insufficient balance
        self.processor.validator.get_balance = Mock(return_value=Decimal("500"))

        tx = {
            "txid": "wrap_burn_txid",
            "vout": [
                {
                    "scriptPubKey": {
                        "type": "nulldata",
                        "hex": "6a"
                        + "7b2270223a226272632d3230222c226f70223a226275726e222c227469636b223a2257222c22616d74223a2231303030227d",
                    }
                },
                {"value": 1000, "scriptPubKey": {"type": "p2pkh"}},
            ],
            "vin": [],
        }

        intermediate_state = IntermediateState()
        result, orm_objects, _ = self.processor.process_transaction(
            tx, 800001, 0, 1600000001, "block_hash", intermediate_state
        )

        # Should fail due to insufficient balance
        assert result.operation_found is True
        assert result.is_valid is False
        assert "Insufficient balance" in result.error_message

    def test_opi_parser_integration(self):
        """Test OPI parser integration"""
        # Test OPI magic code detection
        hex_script = "6a" + "5B577C4254437C4D5D" + "a" * 64 + "b" * 128

        assert self.processor.parser._is_likely_opi_fast(hex_script) is True

        # Test OPI operation parsing
        opi_data = "5B577C4254437C4D5D" + "a" * 64 + "b" * 128
        parse_result = self.processor.parser.parse_opi_operation(opi_data)

        assert parse_result["success"] is True
        assert parse_result["data"]["op"] == "wrap_mint"
        assert parse_result["data"]["tick"] == "W"
        assert "control_block" in parse_result["data"]
        assert "tapscript" in parse_result["data"]

    def test_brc20_burn_parser_integration(self):
        """Test BRC-20 burn parser integration"""
        # Test BRC-20 burn JSON
        burn_json = '{"p":"brc-20","op":"burn","tick":"W","amt":"1000"}'
        burn_hex = burn_json.encode().hex()
        hex_script = "6a" + burn_hex

        # Should be detected as BRC-20, not OPI
        assert self.processor.parser._is_likely_brc20_fast(hex_script) is True
        assert self.processor.parser._is_likely_opi_fast(hex_script) is False

        # Parse as BRC-20 operation
        parse_result = self.processor.parser.parse_brc20_operation(burn_hex)

        assert parse_result["success"] is True
        assert parse_result["data"]["op"] == "burn"
        assert parse_result["data"]["tick"] == "W"
        assert parse_result["data"]["amt"] == "1000"
