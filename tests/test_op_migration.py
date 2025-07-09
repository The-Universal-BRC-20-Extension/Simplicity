"""
Test Op Model Migration
"""

from datetime import datetime
from unittest.mock import Mock, patch

import pytest

from src.api.models import Op
from src.models.transaction import BRC20Operation
from src.services.calculation_service import BRC20CalculationService
from src.services.data_transformation_service import DataTransformationService


class TestOpMigration:
    """Test suite for Op model migration validation"""

    def test_op_model_new_field_names(self):
        """Test that Op model accepts new field names"""
        op = Op(
            id=1,
            tx_id="test_txid_123",
            txid="test_txid_123",
            op="mint",
            ticker="OPQT",
            amount_str="1000",
            block_height=800000,
            block_hash="test_hash_456",
            tx_index=0,
            timestamp="2024-01-01T00:00:00Z",
            from_address="bc1qfrom",
            to_address="bc1qto",
            valid=True,
        )

        assert op.tx_id == "test_txid_123"
        assert op.op == "mint"
        assert op.ticker == "OPQT"
        assert op.amount_str == "1000"
        assert op.block_height == 800000
        assert op.timestamp == "2024-01-01T00:00:00Z"
        assert op.valid is True

    def test_op_model_rejects_old_field_names(self):
        """Test that Op model rejects old field names"""
        with pytest.raises(Exception):
            Op(
                id=1,
                operation="mint",
                tick="OPQT",
                amount="1000",
                height=800000,
                time=1234567890,
                is_valid=True,
            )

    def test_calculation_service_map_operation_to_op_model(self):
        """Test that _map_operation_to_op_model returns correct format"""
        mock_db_op = Mock(spec=BRC20Operation)
        mock_db_op.id = 1
        mock_db_op.txid = "test_txid_456"
        mock_db_op.operation = "transfer"
        mock_db_op.ticker = "OPQT"
        mock_db_op.amount = "500"
        mock_db_op.block_height = 800001
        mock_db_op.tx_index = 1
        mock_db_op.timestamp = datetime(2024, 1, 1, 12, 0, 0)
        mock_db_op.from_address = "bc1qsender"
        mock_db_op.to_address = "bc1qrecipient"
        mock_db_op.is_valid = True

        with patch("src.services.calculation_service.Session"):
            calc_service = BRC20CalculationService(Mock())

            result = calc_service._map_operation_to_op_model(
                mock_db_op, "test_block_hash"
            )

            assert result["tx_id"] == "test_txid_456"
            assert result["op"] == "transfer"
            assert result["ticker"] == "OPQT"
            assert result["amount_str"] == "500"
            assert result["block_height"] == 800001
            assert result["timestamp"] == "2024-01-01T12:00:00Z"
            assert result["valid"] is True

            assert "operation" not in result
            assert "tick" not in result
            assert "amount" not in result
            assert "height" not in result
            assert "time" not in result
            assert "is_valid" not in result

    def test_data_transformation_service_new_format(self):
        """Test that DataTransformationService handles new format correctly"""
        backend_data = {
            "id": 2,
            "tx_id": "test_txid_789",
            "txid": "test_txid_789",
            "op": "deploy",
            "ticker": "NEWT",
            "amount_str": None,
            "block_height": 800002,
            "block_hash": "test_hash_789",
            "tx_index": 2,
            "timestamp": "2024-01-01T12:30:00Z",
            "from_address": None,
            "to_address": "bc1qdeployer",
            "valid": True,
        }

        result = DataTransformationService.transform_transaction_operation(backend_data)

        assert result["tx_id"] == "test_txid_789"
        assert result["op"] == "deploy"
        assert result["ticker"] == "NEWT"
        assert result["amount_str"] is None
        assert result["block_height"] == 800002
        assert result["timestamp"] == "2024-01-01T12:30:00Z"
        assert result["valid"] is True

    def test_calculation_service_functions_return_new_format(self):
        """Test that calculation service functions return new format"""
        with patch("src.services.calculation_service.Session"):
            calc_service = BRC20CalculationService(Mock())

            mock_db_op = Mock(spec=BRC20Operation)
            mock_db_op.id = 3
            mock_db_op.txid = "test_txid_999"
            mock_db_op.operation = "mint"
            mock_db_op.ticker = "OPQT"
            mock_db_op.amount = "1000"
            mock_db_op.block_height = 800003
            mock_db_op.tx_index = 3
            mock_db_op.timestamp = datetime(2024, 1, 1, 13, 0, 0)
            mock_db_op.from_address = None
            mock_db_op.to_address = "bc1qminter"
            mock_db_op.is_valid = True

            [(mock_db_op, "test_block_hash")]

            result = calc_service._map_operation_to_op_model(
                mock_db_op, "test_block_hash"
            )

            op = Op(**result)
            assert op.tx_id == "test_txid_999"
            assert op.op == "mint"
            assert op.ticker == "OPQT"
            assert op.amount_str == "1000"
            assert op.block_height == 800003
            assert op.valid is True

    def test_no_extra_fields_in_op_model(self):
        """Test that Op model doesn't contain old extra fields"""
        op = Op(
            id=4,
            tx_id="test_txid_extra",
            txid="test_txid_extra",
            op="mint",
            ticker="TEST",
            amount_str="100",
            block_height=800004,
            block_hash="test_hash_extra",
            tx_index=4,
            timestamp="2024-01-01T14:00:00Z",
            from_address=None,
            to_address="bc1qtest",
            valid=True,
        )

        assert not hasattr(op, "max_supply_str")
        assert not hasattr(op, "limit_per_mint_str")
        assert not hasattr(op, "decimals_str")
        assert not hasattr(op, "error_code")
        assert not hasattr(op, "error_message")

    def test_op_model_serialization(self):
        """Test that Op model can be serialized to dict properly"""
        op = Op(
            id=5,
            tx_id="test_txid_serialize",
            txid="test_txid_serialize",
            op="transfer",
            ticker="OPQT",
            amount_str="250",
            block_height=800005,
            block_hash="test_hash_serialize",
            tx_index=5,
            timestamp="2024-01-01T15:00:00Z",
            from_address="bc1qsender",
            to_address="bc1qrecipient",
            valid=True,
        )

        op_dict = op.model_dump()

        assert op_dict["tx_id"] == "test_txid_serialize"
        assert op_dict["op"] == "transfer"
        assert op_dict["ticker"] == "OPQT"
        assert op_dict["amount_str"] == "250"
        assert op_dict["block_height"] == 800005
        assert op_dict["timestamp"] == "2024-01-01T15:00:00Z"
        assert op_dict["valid"] is True

        assert "operation" not in op_dict
        assert "tick" not in op_dict
        assert "amount" not in op_dict
        assert "height" not in op_dict
        assert "time" not in op_dict
        assert "is_valid" not in op_dict
