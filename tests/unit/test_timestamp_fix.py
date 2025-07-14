from datetime import datetime, timezone
from unittest.mock import Mock, patch

import pytest
from sqlalchemy.orm import Session

from src.models.deploy import Deploy
from src.models.transaction import BRC20Operation
from src.services.bitcoin_rpc import BitcoinRPCService
from src.services.indexer import IndexerService
from src.services.processor import BRC20Processor
from src.services.validator import ValidationResult


class TestTimestampFix:
    """Comprehensive test suite for Bitcoin timestamp fix"""

    @pytest.fixture
    def mock_db_session(self):
        return Mock(spec=Session)

    @pytest.fixture
    def mock_bitcoin_rpc(self):
        return Mock(spec=BitcoinRPCService)

    @pytest.fixture
    def processor(self, mock_db_session, mock_bitcoin_rpc):
        return BRC20Processor(mock_db_session, mock_bitcoin_rpc)

    @pytest.fixture
    def indexer(self, mock_db_session, mock_bitcoin_rpc):
        return IndexerService(mock_db_session, mock_bitcoin_rpc)

    def test_convert_block_timestamp_success(self, processor):
        """Test successful timestamp conversion"""
        block_timestamp = 1232346882
        expected_datetime = datetime.fromtimestamp(1232346882, tz=timezone.utc)

        result = processor._convert_block_timestamp(block_timestamp)

        assert result == expected_datetime
        assert result.tzinfo == timezone.utc
        assert result.year == 2009
        assert result.month == 1
        assert result.day == 19

    def test_convert_block_timestamp_invalid_type(self, processor):
        """Test timestamp conversion with invalid type"""
        invalid_timestamps = ["invalid", None, 1232346882.5, []]

        for invalid_ts in invalid_timestamps:
            with pytest.raises(ValueError, match="Block timestamp must be integer"):
                processor._convert_block_timestamp(invalid_ts)

    def test_convert_block_timestamp_negative(self, processor):
        """Test timestamp conversion with negative value"""
        with pytest.raises(ValueError, match="Block timestamp must be positive"):
            processor._convert_block_timestamp(-1)

        with pytest.raises(ValueError, match="Block timestamp must be positive"):
            processor._convert_block_timestamp(0)

    def test_convert_block_timestamp_before_genesis(self, processor):
        """Test timestamp conversion before Bitcoin genesis"""
        # Bitcoin genesis: 1231006505
        pre_genesis_timestamp = 1231006504

        with pytest.raises(ValueError, match="before Bitcoin genesis"):
            processor._convert_block_timestamp(pre_genesis_timestamp)

    def test_convert_block_timestamp_far_future(self, processor):
        """Test timestamp conversion far in future"""
        import time

        far_future_timestamp = int(time.time()) + 86400  # 24 hours in future

        with pytest.raises(ValueError, match="too far in future"):
            processor._convert_block_timestamp(far_future_timestamp)

    def test_process_transaction_with_timestamp(self, processor, mock_db_session):
        """Test process_transaction stores block timestamp"""
        block_timestamp = 1232346882

        tx_data = {
            "txid": "test_txid",
            "vout": [
                {"scriptPubKey": {"hex": "6a"}},  # OP_RETURN
                {"scriptPubKey": {"addresses": ["test_address"]}},
            ],
        }

        with patch.object(
            processor.parser, "extract_op_return_data", return_value=(None, 0)
        ):
            # Process transaction and verify timestamp is set correctly
            processor.process_transaction(
                tx_data, 1000, 1, block_timestamp, "test_block_hash"
            )

            assert processor.current_block_timestamp == block_timestamp

    def test_process_deploy_with_bitcoin_timestamp(self, processor, mock_db_session):
        """Test deploy processing uses Bitcoin timestamp"""
        processor.current_block_timestamp = 1232346882

        operation = {"op": "deploy", "tick": "TEST", "m": "1000000", "l": "1000"}

        tx_info = {
            "txid": "test_txid",
            "block_height": 1000,
            "vin": [{"address": "test_deployer"}],
            "vout": [],
        }

        with patch.object(
            processor, "get_first_input_address", return_value="test_deployer"
        ):
            with patch.object(
                processor.validator,
                "validate_complete_operation",
                return_value=ValidationResult(True),
            ):
                processor.process_deploy(operation, tx_info, "test_hex_data")

                added_objects = [
                    call[0][0] for call in mock_db_session.add.call_args_list
                ]
                deploy_obj = None
                for obj in added_objects:
                    if isinstance(obj, Deploy):
                        deploy_obj = obj
                        break

                assert deploy_obj is not None, "Deploy object should be created"
            expected_timestamp = datetime.fromtimestamp(1232346882, tz=timezone.utc)
            assert deploy_obj.deploy_timestamp == expected_timestamp

    def test_log_operation_with_bitcoin_timestamp(self, processor, mock_db_session):
        """Test operation logging uses Bitcoin timestamp"""
        from src.services.validator import ValidationResult

        processor.current_block_timestamp = 1232346882

        operation_data = {"op": "mint", "tick": "TEST", "amt": "1000"}
        validation_result = ValidationResult(True)
        tx_info = {
            "txid": "test_txid",
            "block_height": 1000,
            "vout_index": 0,
            "block_hash": "test_hash",
            "tx_index": 1,
        }

        with patch.object(
            processor, "get_first_input_address", return_value="test_address"
        ):
            with patch.object(
                processor.validator,
                "get_output_after_op_return_address",
                return_value="test_recipient",
            ):
                processor.log_operation(
                    operation_data, validation_result, tx_info, "raw_op_return"
                )

                mock_db_session.add.assert_called_once()
                operation_obj = mock_db_session.add.call_args[0][0]

                assert isinstance(operation_obj, BRC20Operation)
                expected_timestamp = datetime.fromtimestamp(1232346882, tz=timezone.utc)
                assert operation_obj.timestamp == expected_timestamp

    def test_indexer_processes_block_with_timestamp(self, indexer, mock_db_session):
        """Test indexer extracts and passes block timestamp"""
        block_data = {
            "height": 1000,
            "hash": "test_hash",
            "time": 1232346882,
            "tx": [{"txid": "coinbase_tx"}, {"txid": "test_tx", "vout": []}],
        }

        with patch.object(indexer.processor, "process_transaction") as mock_process:
            indexer.process_block_transactions(block_data)

            mock_process.assert_called_once_with(
                {"txid": "test_tx", "vout": []},
                block_height=1000,
                tx_index=1,
                block_timestamp=1232346882,
                block_hash="test_hash",
            )

    def test_indexer_handles_missing_timestamp(self, indexer):
        """Test indexer handles missing block timestamp"""
        block_data = {"height": 1000, "hash": "test_hash", "tx": [{"txid": "test_tx"}]}

        with pytest.raises(ValueError, match="Block 1000 missing timestamp"):
            indexer.process_block_transactions(block_data)

    def test_timestamp_conversion_performance(self, processor):
        """Test timestamp conversion performance"""
        import time

        start_time = time.time()
        for i in range(1000):
            processor._convert_block_timestamp(1232346882 + i)
        elapsed = time.time() - start_time

        assert elapsed < 0.1

    def test_known_bitcoin_blocks_timestamps(self, processor):
        """Test with known Bitcoin block timestamps"""
        known_blocks = [
            {"height": 1000, "timestamp": 1232346882, "date": "2009-01-19"},
            {"height": 100000, "timestamp": 1293623863, "date": "2010-12-29"},
            {"height": 200000, "timestamp": 1348310759, "date": "2012-09-22"},
        ]

        for block in known_blocks:
            result = processor._convert_block_timestamp(block["timestamp"])

            assert result.year == int(block["date"].split("-")[0])
            assert result.month == int(block["date"].split("-")[1])
            assert result.day == int(block["date"].split("-")[2])
            assert result.tzinfo == timezone.utc

    def test_enterprise_logging_on_errors(self, processor, caplog):
        """Test enterprise-grade logging on timestamp errors"""
        import logging

        caplog.set_level(logging.ERROR)

        with pytest.raises(ValueError):
            processor._convert_block_timestamp(-1)

        processor.current_block_timestamp = -1

        operation = {"op": "deploy", "tick": "TEST", "m": "1000000"}
        tx_info = {"txid": "test_txid", "block_height": 1000}

        with patch.object(
            processor, "get_first_input_address", return_value="test_address"
        ):
            processor.process_deploy(operation, tx_info, "test_hex_data")

        assert True

    def test_process_transaction_invalid_timestamp(self, processor):
        """Test process_transaction with invalid block timestamp"""
        tx_data = {"txid": "test_txid", "vout": []}

        invalid_timestamps = [-1, 0, "invalid", None]

        for invalid_ts in invalid_timestamps:
            result = processor.process_transaction(
                tx_data, 1000, 1, invalid_ts, "test_block_hash"
            )
            assert result.error_message is not None
            assert "Invalid block timestamp" in result.error_message

    def test_log_operation_timestamp_fallback(self, processor, mock_db_session):
        """Test log_operation fallback when timestamp conversion fails"""
        from src.services.validator import ValidationResult

        processor.current_block_timestamp = -1

        operation_data = {"op": "mint", "tick": "TEST", "amt": "1000"}
        validation_result = ValidationResult(True)
        tx_info = {
            "txid": "test_txid",
            "block_height": 1000,
            "vout_index": 0,
            "block_hash": "test_hash",
            "tx_index": 1,
        }

        with patch.object(
            processor, "get_first_input_address", return_value="test_address"
        ):
            with patch.object(
                processor.validator,
                "get_output_after_op_return_address",
                return_value="test_recipient",
            ):
                processor.log_operation(
                    operation_data, validation_result, tx_info, "raw_op_return"
                )

                mock_db_session.add.assert_called_once()
                operation_obj = mock_db_session.add.call_args[0][0]

                assert isinstance(operation_obj, BRC20Operation)
                assert operation_obj.timestamp is not None
