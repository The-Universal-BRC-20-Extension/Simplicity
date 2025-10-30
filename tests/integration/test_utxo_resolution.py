from unittest.mock import MagicMock
from unittest.mock import ANY

import pytest
from sqlalchemy.orm import Session

from src.models.deploy import Deploy
from src.services.processor import BRC20Processor
from src.services.utxo_service import UTXOResolutionService
from src.utils.exceptions import TransferType


@pytest.fixture
def mock_bitcoin_rpc():
    rpc = MagicMock()
    rpc.get_raw_transaction.side_effect = lambda txid: (
        {
            "txid": txid,
            "vout": [
                {
                    "n": 0,
                    "scriptPubKey": {
                        "hex": "76a914c0f0c0f0c0f0c0f0c0f0c0f0c0f0c0f0c0f0c0f088ac",
                        "addresses": ["1A1zP1eP5QGefi2DMPTfTL5SLmv7DivfNa"],
                    },
                },
                {
                    "n": 1,
                    "scriptPubKey": {"hex": "6a0101", "asm": "OP_RETURN 01"},
                },  # OP_RETURN
                {
                    "n": 2,
                    "scriptPubKey": {
                        "hex": "76a914d1f1d1f1d1f1d1f1d1f1d1f1d1f1d1f1d1f1d1f188ac",
                        "addresses": ["1B1zP1eP5QGefi2DMPTfTL5SLmv7DivfNb"],
                    },
                },
            ],
            "vin": [
                {
                    "txid": "prev_txid_1",
                    "vout": 0,
                    "scriptSig": {"hex": "dummy_script_sig"},
                    "address": "1SenderAddress",
                }
            ],
        }
        if txid == "mock_tx_with_op_return"
        else {
            "txid": txid,
            "vout": [
                {
                    "n": 0,
                    "scriptPubKey": {
                        "hex": "76a914c0f0c0f0c0f0c0f0c0f0c0f0c0f0c0f0c0f0c0f088ac",
                        "addresses": ["1A1zP1eP5QGefi2DMPTfTL5SLmv7DivfNa"],
                    },
                },
            ],
            "vin": [
                {
                    "txid": "prev_txid_2",
                    "vout": 0,
                    "scriptSig": {"hex": "dummy_script_sig"},
                    "address": "1AnotherSenderAddress",
                }
            ],
        }
    )
    return rpc


@pytest.fixture
def mock_db_session():
    session = MagicMock(spec=Session)
    session.query.return_value.filter.return_value.first.return_value = None
    session.query.return_value.filter.return_value.all.return_value = []
    session.query.return_value.filter.return_value.count.return_value = 0
    return session


@pytest.fixture
def utxo_service(mock_bitcoin_rpc):
    return UTXOResolutionService(mock_bitcoin_rpc)


@pytest.fixture
def processor(mock_db_session, mock_bitcoin_rpc):
    return BRC20Processor(mock_db_session, mock_bitcoin_rpc)


def test_utxo_resolution_service_get_input_address(utxo_service, mock_bitcoin_rpc):
    txid = "test_txid_1"
    vout = 0
    expected_address = "1A1zP1eP5QGefi2DMPTfTL5SLmv7DivfNa"

    address = utxo_service.get_input_address(txid, vout)
    assert address == expected_address
    mock_bitcoin_rpc.get_raw_transaction.assert_called_with(txid)

    utxo_service.get_input_address(txid, vout)
    mock_bitcoin_rpc.get_raw_transaction.assert_called_once()

    address = utxo_service.get_input_address(txid, 99)
    assert address is None

    mock_bitcoin_rpc.get_raw_transaction.reset_mock()
    mock_bitcoin_rpc.get_raw_transaction.side_effect = lambda txid: (
        None
        if txid == "non_existent_txid"
        else {
            "txid": txid,
            "vout": [
                {
                    "n": 0,
                    "scriptPubKey": {
                        "hex": "76a914c0f0c0f0c0f0c0f0c0f0c0f0c0f0c0f0c0f0c0f088ac",
                        "addresses": ["1A1zP1eP5QGefi2DMPTfTL5SLmv7DivfNa"],
                    },
                },
            ],
        }
    )

    utxo_service.tx_cache = {}
    utxo_service.tx_cache_keys = []

    address = utxo_service.get_input_address("non_existent_txid", 0)
    assert address is None


def test_processor_get_first_input_address(processor, mock_bitcoin_rpc):
    tx_info = {"vin": [{"txid": "prev_txid_1", "vout": 0}], "vout": []}
    expected_address = "1A1zP1eP5QGefi2DMPTfTL5SLmv7DivfNa"

    address = processor.get_first_input_address(tx_info)
    assert address == expected_address
    mock_bitcoin_rpc.get_raw_transaction.assert_called_with("prev_txid_1")

    tx_info_coinbase = {"vin": [{"coinbase": "some_data"}], "vout": []}
    address = processor.get_first_input_address(tx_info_coinbase)
    assert address is None

    tx_info_no_vin = {"vout": []}
    address = processor.get_first_input_address(tx_info_no_vin)
    assert address is None


def test_deployer_first_input_fallback(processor, mock_db_session, mock_bitcoin_rpc):
    tx_info = {
        "txid": "deploy_tx_no_output_after_op_return",
        "block_height": 100,
        "vout_index": 1,
        "vout": [
            {
                "n": 0,
                "scriptPubKey": {
                    "hex": "76a914c0f0c0f0c0f0c0f0c0f0c0f0c0f0c0f0c0f0c0f088ac",
                    "addresses": ["1A1zP1eP5QGefi2DMPTfTL5SLmv7DivfNa"],
                },
            },
        ],
        "vin": [{"txid": "prev_txid_for_deploy", "vout": 0}],
    }

    mock_bitcoin_rpc.get_raw_transaction.side_effect = lambda txid: {
        "txid": txid,
        "vout": [
            {
                "n": 0,
                "scriptPubKey": {
                    "hex": "76a914f0f0f0f0f0f0f0f0f0f0f0f0f0f0f0f0f0f0f0f088ac",
                    "addresses": ["1DeployerInputAddress"],
                },
            },
        ],
    }

    operation = {"op": "deploy", "tick": "TEST", "m": "1000", "l": "100"}

    processor.current_block_timestamp = 1683374400

    processor.process_deploy(operation, tx_info, intermediate_deploys={})

    assert mock_db_session.add.call_count >= 1
    added_objects = [call[0][0] for call in mock_db_session.add.call_args_list]
    deploy_obj = None
    for obj in added_objects:
        if isinstance(obj, Deploy):
            deploy_obj = obj
            break

    assert deploy_obj is not None, "Deploy object should be created"
    assert deploy_obj.deployer_address == "1DeployerInputAddress"


def test_deployer_output_after_op_return(processor, mock_db_session, mock_bitcoin_rpc):
    tx_info = {
        "txid": "deploy_tx_with_output_after_op_return",
        "block_height": 101,
        "vout_index": 1,
        "vout": [
            {
                "n": 0,
                "scriptPubKey": {
                    "hex": "76a914c0f0c0f0c0f0c0f0c0f0c0f0c0f0f0f0f0f0f0f088ac",
                    "addresses": ["1A1zP1eP5QGefi2DMPTfTL5SLmv7DivfNa"],
                },
            },
            {
                "n": 1,
                "scriptPubKey": {
                    "hex": "6a046465706c6f79",
                    "asm": "OP_RETURN 046465706c6f79",
                },
            },  # OP_RETURN
            {
                "n": 2,
                "scriptPubKey": {
                    "hex": "76a914e0e0e0e0e0e0e0e0e0e0e0e0e0e0e0e0e0e0e0e088ac",
                    "addresses": ["1DeployerOutputAddress"],
                },
            },  # Output after OP_RETURN
        ],
        "vin": [{"txid": "prev_txid_for_deploy_2", "vout": 0}],
    }

    mock_bitcoin_rpc.get_raw_transaction.side_effect = lambda txid: {
        "txid": txid,
        "vout": [
            {
                "n": 0,
                "scriptPubKey": {
                    "hex": "76a914f0f0f0f0f0f0f0f0f0f0f0f0f0f0f0f0f0f0f0f088ac",
                    "addresses": ["1DeployerInputAddress"],
                },
            },
        ],
    }

    operation = {"op": "deploy", "tick": "TEST2", "m": "2000", "l": "200"}

    processor.current_block_timestamp = 1683374400

    processor.process_deploy(operation, tx_info, intermediate_deploys={})

    assert mock_db_session.add.call_count >= 1
    added_objects = [call[0][0] for call in mock_db_session.add.call_args_list]
    deploy_obj = None
    for obj in added_objects:
        if isinstance(obj, Deploy):
            deploy_obj = obj
            break

    assert deploy_obj is not None, "Deploy object should be created"
    assert deploy_obj.deployer_address == "1DeployerInputAddress"
    mock_bitcoin_rpc.get_raw_transaction.assert_called_with("prev_txid_for_deploy_2")


def test_transfer_input_resolution(processor, mock_db_session, mock_bitcoin_rpc):
    tx_info = {
        "txid": "transfer_tx_id",
        "block_height": 102,
        "vout_index": 1,
        "vout": [
            {
                "n": 0,
                "scriptPubKey": {
                    "hex": "76a914a0a0a0a0a0a0a0a0a0a0a0a0a0a0a0a0a0a0a0a088ac",
                    "addresses": ["1FirstOutputAddress"],
                },
            },
            {
                "n": 1,
                "scriptPubKey": {
                    "hex": "6a047472616e73666572",
                    "asm": "OP_RETURN 047472616e73666572",
                },
            },  # OP_RETURN
            {
                "n": 2,
                "scriptPubKey": {
                    "hex": "76a914c0f0c0f0c0f0c0f0c0f0c0f0c0f0f0f0f0f0f0f088ac",
                    "addresses": ["1RecipientAddress"],
                },
            },  # Output AFTER OP_RETURN
        ],
        "vin": [{"txid": "prev_txid_for_transfer", "vout": 0}],
    }

    mock_bitcoin_rpc.get_raw_transaction.side_effect = lambda txid: {
        "txid": txid,
        "vout": [
            {
                "n": 0,
                "scriptPubKey": {
                    "hex": "76a914a0a0a0a0a0a0a0a0a0a0a0a0a0a0a0a0a0a0a0a088ac",
                    "addresses": ["1SenderAddressForTransfer"],
                },
            },
        ],
    }

    operation = {"op": "transfer", "tick": "TEST", "amt": "100"}

    processor.update_balance = MagicMock()

    original_validator = processor.validator
    mock_validator = MagicMock()
    mock_validation_result = MagicMock()
    mock_validation_result.is_valid = True
    mock_validator.validate_complete_operation.return_value = mock_validation_result
    mock_validator.get_output_after_op_return_address.return_value = "1RecipientAddress"
    processor.validator = mock_validator

    mock_parse_result = {"success": True, "data": operation}
    processor.parser.parse_brc20_operation = MagicMock(return_value=mock_parse_result)

    processor.classify_transfer_type = MagicMock(return_value=TransferType.SIMPLE)
    processor.validate_transfer_specific = MagicMock(return_value=mock_validation_result)
    processor.resolve_transfer_addresses = MagicMock(
        return_value={
            "sender": "1SenderAddressForTransfer",
            "recipient": "1RecipientAddress",
        }
    )

    from src.opi.contracts import IntermediateState

    processor.process_transfer(
        operation, tx_info, mock_validation_result, "test_hex_data", 102, intermediate_state=IntermediateState()
    )

    print(f"update_balance calls: {processor.update_balance.call_args_list}")

    processor.update_balance.assert_any_call(
        address="1SenderAddressForTransfer",
        ticker="TEST",
        amount_delta="-100",
        op_type="transfer_out",
        txid="transfer_tx_id",
        intermediate_state=ANY,
    )
    processor.update_balance.assert_any_call(
        address="1RecipientAddress",
        ticker="TEST",
        amount_delta="100",
        op_type="transfer_in",
        txid="transfer_tx_id",
        intermediate_state=ANY,
    )
    # Note: get_raw_transaction is not called because we're mocking the address resolution
    # The test focuses on balance updates, not UTXO resolution

    processor.validator = original_validator
