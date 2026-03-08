from unittest.mock import MagicMock

import pytest
from sqlalchemy.orm import Session

from src.services.bitcoin_rpc import BitcoinRPCService
from src.services.processor import BRC20Processor
from src.services.validator import ValidationResult


@pytest.fixture
def mock_db_session():
    session = MagicMock(spec=Session)
    session.query.return_value.filter.return_value.first.return_value = None
    session.query.return_value.filter.return_value.all.return_value = []
    session.query.return_value.filter.return_value.count.return_value = 0
    return session


@pytest.fixture
def mock_bitcoin_rpc():
    rpc = MagicMock(spec=BitcoinRPCService)
    rpc.get_raw_transaction.return_value = {
        "txid": "dummy_txid",
        "vout": [
            {
                "n": 0,
                "scriptPubKey": {
                    "hex": "76a914c0f0c0f0c0f0c0f0c0f0f0f0f0f0f0f0f0f0f0f088ac",
                    "addresses": ["1DummyAddress"],
                },
            }
        ],
    }
    return rpc


@pytest.fixture
def processor(mock_db_session, mock_bitcoin_rpc):
    processor = BRC20Processor(mock_db_session, mock_bitcoin_rpc)
    processor.log_operation = MagicMock()
    return processor


def test_non_brc20_op_return_handling(processor):
    tx_info = {
        "txid": "txid_non_brc20_json",
        "vout": [
            {
                "n": 0,
                "scriptPubKey": {
                    "hex": "6a047b22666f6f223a22626172227d",
                    "asm": 'OP_RETURN { "foo": "bar" }',
                },
            },
            {
                "n": 1,
                "scriptPubKey": {
                    "hex": "76a914c0f0c0f0c0f0c0f0c0f0f0f0f0f0f0f0f0f0f0f088ac",
                    "addresses": ["1RecipientAddress"],
                },
            },
        ],
        "vin": [],
    }

    result, _, _ = processor.process_transaction(tx_info, 100, 0, 1609459200, "test_block_hash")  # 2021-01-01 timestamp

    assert not result.operation_found
    assert not result.is_valid
    assert result.error_message is None

    processor.log_operation.assert_not_called()


def test_valid_json_invalid_protocol_handling(processor):
    tx_info = {
        "txid": "txid_invalid_protocol",
        "vout": [
            {
                "n": 0,
                "scriptPubKey": {
                    "hex": "6a047b2270223a226272632d3231222c226f70223a22" "6465706c6f79227d",
                    "asm": 'OP_RETURN { "p": "brc-21", "op": "deploy" }',
                },
            },
            {
                "n": 1,
                "scriptPubKey": {
                    "hex": "76a914c0f0c0f0c0f0c0f0c0f0f0f0f0f0f0f0f0f0f0f088ac",
                    "addresses": ["1RecipientAddress"],
                },
            },
        ],
        "vin": [],
    }

    result, _, _ = processor.process_transaction(tx_info, 100, 0, 1609459200, "test_block_hash")  # 2021-01-01 timestamp

    assert not result.operation_found
    assert not result.is_valid
    assert result.error_message is None

    processor.log_operation.assert_not_called()


def test_non_json_op_return_handling(processor):
    tx_info = {
        "txid": "txid_non_json",
        "vout": [
            {
                "n": 0,
                "scriptPubKey": {"hex": "6a0468656c6c6f", "asm": "OP_RETURN hello"},
            },
            {
                "n": 1,
                "scriptPubKey": {
                    "hex": "76a914c0f0c0f0c0f0c0f0f0f0f0f0f0f0f0f0f0f0f0f088ac",
                    "addresses": ["1RecipientAddress"],
                },
            },
        ],
        "vin": [],
    }

    result, _, _ = processor.process_transaction(tx_info, 100, 0, 1609459200, "test_block_hash")  # 2021-01-01 timestamp

    assert not result.operation_found
    assert not result.is_valid
    assert result.error_message is None

    processor.log_operation.assert_not_called()


def test_valid_brc20_op_is_processed(processor):
    tx_info = {
        "txid": "txid_valid_brc20",
        "vout": [
            {
                "n": 0,
                "scriptPubKey": {
                    "hex": "6a4c4e7b2270223a20226272632d3230222c226f70223a2264"
                    "65706c6f79222c20227469636b223a202254455354222c2022"
                    "6d223a202231303030222c20226c223a2022313030227d",
                    "asm": 'OP_RETURN { "p": "brc-20", "op": "deploy", "tick": ' '"TEST", "m": "1000", "l": "100" }',
                },
            },
            {
                "n": 1,
                "scriptPubKey": {
                    "hex": "76a914c0f0c0f0c0f0c0f0c0f0f0f0f0f0f0f0f0f0f0f088ac",
                    "addresses": ["1RecipientAddress"],
                },
            },
        ],
        "vin": [{"txid": "prev_txid", "vout": 0}],
    }

    hex_data = (
        "7b2270223a20226272632d3230222c226f70223a226465706c6f79222c2022"
        "7469636b223a202254455354222c20226d223a202231303030222c20226c22"
        "3a2022313030227d"
    )
    processor.parser.extract_op_return_data = MagicMock(return_value=(hex_data, 0))
    processor.parser.parse_brc20_operation = MagicMock(
        return_value={
            "success": True,
            "data": {
                "p": "brc-20",
                "op": "deploy",
                "tick": "TEST",
                "m": "1000",
                "l": "100",
            },
        }
    )

    processor.validator.validate_complete_operation = MagicMock(return_value=ValidationResult(True, None, None))
    processor.process_deploy = MagicMock()

    result, _, _ = processor.process_transaction(tx_info, 100, 0, 1609459200, "test_block_hash")

    assert result.operation_found
    assert result.is_valid
    assert result.error_message is None

    processor.process_deploy.assert_called_once()


def test_no_op_return_handling(processor):
    tx_info = {
        "txid": "txid_no_op_return",
        "vout": [
            {
                "n": 0,
                "scriptPubKey": {
                    "hex": "76a914c0f0c0f0c0f0c0f0f0f0f0f0f0f0f0f0f0f0f0f088ac",
                    "addresses": ["1RecipientAddress"],
                },
            }
        ],
        "vin": [],
    }

    result, _, _ = processor.process_transaction(tx_info, 100, 0, 1609459200, "test_block_hash")  # 2021-01-01 timestamp

    assert not result.operation_found
    assert not result.is_valid
    assert result.error_message is None
    processor.log_operation.assert_not_called()
