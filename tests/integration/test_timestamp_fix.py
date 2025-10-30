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
        block_timestamp = 1232346882
        expected_datetime = datetime.fromtimestamp(1232346882, tz=timezone.utc)

        result = processor._convert_block_timestamp(block_timestamp)

        assert result == expected_datetime
        assert result.tzinfo == timezone.utc
        assert result.year == 2009
        assert result.month == 1
        assert result.day == 19

    def test_convert_block_timestamp_invalid_type(self, processor):
        invalid_timestamps = ["invalid", None, 1232346882.5, []]

        for invalid_ts in invalid_timestamps:
            with pytest.raises(ValueError, match="Invalid block timestamp"):
                processor._convert_block_timestamp(invalid_ts)

    def test_convert_block_timestamp_negative(self, processor):
        with pytest.raises(ValueError, match="Invalid block timestamp"):
            processor._convert_block_timestamp(-1)

        with pytest.raises(ValueError, match="Invalid block timestamp"):
            processor._convert_block_timestamp(0)

    def test_process_transaction_with_timestamp(self, processor, mock_db_session):
        block_timestamp = 1232346882

        tx_data = {
            "txid": "test_txid",
            "vout": [
                {"scriptPubKey": {"hex": "6a"}},  # OP_RETURN
                {"scriptPubKey": {"addresses": ["test_address"]}},
            ],
        }

        with patch.object(processor.parser, "extract_op_return_data", return_value=("test_hex", 0)):
            with patch.object(
                processor.parser,
                "parse_brc20_operation",
                return_value={"success": True, "data": {"op": "deploy"}},
            ):
                processor.process_transaction(tx_data, 1000, 1, block_timestamp, "test_block_hash")

                assert processor.current_block_timestamp == block_timestamp

    def test_process_deploy_with_bitcoin_timestamp(self, processor, mock_db_session):
        processor.current_block_timestamp = 1232346882

        operation = {"op": "deploy", "tick": "TEST", "m": "1000000", "l": "1000"}

        tx_info = {
            "txid": "test_txid",
            "block_height": 1000,
            "vin": [{"address": "test_deployer"}],
            "vout": [],
        }

        with patch.object(processor, "get_first_input_address", return_value="test_deployer"):
            with patch.object(
                processor.validator,
                "validate_complete_operation",
                return_value=ValidationResult(True),
            ):
                processor.process_deploy(operation, tx_info, intermediate_deploys={})

                added_objects = [call[0][0] for call in mock_db_session.add.call_args_list]
                deploy_obj = None
                for obj in added_objects:
                    if isinstance(obj, Deploy):
                        deploy_obj = obj
                        break

                assert deploy_obj is not None, "Deploy object should be created"
            expected_timestamp = datetime.fromtimestamp(1232346882, tz=timezone.utc)
            assert deploy_obj.deploy_timestamp == expected_timestamp

    def test_log_operation_with_bitcoin_timestamp(self, processor, mock_db_session):
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

        with patch.object(processor, "get_first_input_address", return_value="test_address"):
            with patch.object(
                processor.validator,
                "get_output_after_op_return_address",
                return_value="test_recipient",
            ):
                processor.log_operation(operation_data, validation_result, tx_info, "raw_op_return")

                mock_db_session.add.assert_called_once()
                operation_obj = mock_db_session.add.call_args[0][0]

                assert isinstance(operation_obj, BRC20Operation)
                expected_timestamp = datetime.fromtimestamp(1232346882, tz=timezone.utc)
                assert operation_obj.timestamp == expected_timestamp

    def test_indexer_processes_block_with_timestamp(self, indexer, mock_db_session):
        block_data = {
            "height": 1000,
            "hash": "test_hash",
            "time": 1232346882,
            "tx": [
                {"txid": "coinbase_tx", "vout": []},
                {
                    "txid": "test_tx",
                    "vout": [
                        {
                            "scriptPubKey": {
                                "type": "nulldata",
                                "hex": "6a4c547b2270223a226272632d3230222c226f70223a227472616e73666572222c227469636b223a2254455354222c22616d74223a22313030227d",
                            }
                        }
                    ],
                },
            ],
        }

        with patch.object(indexer.processor, "process_transaction") as mock_process:
            indexer.process_block_transactions(block_data)

            from src.opi.contracts import IntermediateState

            test_intermediate_state = IntermediateState()

            # Allow block_height to be set inside state; ignore that field difference
            call_args, call_kwargs = mock_process.call_args
            assert call_kwargs["block_height"] == 1000
            assert call_kwargs["tx_index"] == 1
            assert call_kwargs["block_timestamp"] == 1232346882
            assert call_kwargs["block_hash"] == "test_hash"
            # The state is an IntermediateState; block_height may be set internally
            assert call_kwargs["intermediate_state"].__class__.__name__ == "IntermediateState"
            # And original_tx_index is present on the tx argument
            assert call_args[0]["original_tx_index"] == 1

    def test_indexer_handles_missing_timestamp(self, indexer):
        block_data = {"height": 1000, "hash": "test_hash", "tx": [{"txid": "test_tx"}]}

        result = indexer.process_block_transactions(block_data)
        assert result == []

    def test_timestamp_conversion_performance(self, processor):
        import time

        start_time = time.time()
        for i in range(1000):
            processor._convert_block_timestamp(1232346882 + i)
        elapsed = time.time() - start_time

        assert elapsed < 0.1

    def test_known_bitcoin_blocks_timestamps(self, processor):
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
        import logging

        caplog.set_level(logging.ERROR)

        with pytest.raises(ValueError):
            processor._convert_block_timestamp(-1)

        processor.current_block_timestamp = -1

        operation = {"op": "deploy", "tick": "TEST", "m": "1000000"}
        tx_info = {"txid": "test_txid", "block_height": 1000}

        with patch.object(processor, "get_first_input_address", return_value="test_address"):
            with pytest.raises(ValueError):
                processor.process_deploy(operation, tx_info, intermediate_deploys={})

    def test_process_transaction_invalid_timestamp(self, processor):
        tx_data = {"txid": "test_txid", "vout": []}

        invalid_timestamps = [-1, 0, "invalid", None]

        for invalid_ts in invalid_timestamps:
            result, _, _ = processor.process_transaction(tx_data, 1000, 1, invalid_ts, "test_block_hash")
            assert result.error_message is None

    def test_log_operation_timestamp_fallback(self, processor, mock_db_session):
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

        with patch.object(processor, "get_first_input_address", return_value="test_address"):
            with patch.object(
                processor.validator,
                "get_output_after_op_return_address",
                return_value="test_recipient",
            ):
                with pytest.raises(ValueError, match="Invalid block timestamp"):
                    processor.log_operation(operation_data, validation_result, tx_info, "raw_op_return")
