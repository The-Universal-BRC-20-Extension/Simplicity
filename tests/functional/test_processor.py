from unittest.mock import Mock, patch

import pytest
from sqlalchemy.orm import Session
from decimal import Decimal

from src.models.balance import Balance
from src.models.deploy import Deploy
from src.models.transaction import BRC20Operation
from src.services.bitcoin_rpc import BitcoinRPCService
from src.services.processor import BRC20Processor
from src.services.validator import ValidationResult
from src.utils.exceptions import TransferType
from datetime import datetime, timezone


def create_mock_deploy(ticker="TEST", max_supply="1000000", limit_per_op="1000"):
    deploy = Mock(spec=Deploy)
    deploy.ticker = ticker.upper()
    deploy.max_supply = max_supply
    deploy.limit_per_op = limit_per_op
    deploy.deploy_txid = "test_deploy_txid"
    deploy.deploy_height = 800000
    deploy.deploy_timestamp = datetime.now(timezone.utc)
    deploy.deployer_address = "test_deployer_address"
    return deploy


def create_mock_balance(address="test_address", ticker="TEST", balance="1000"):
    balance_obj = Mock(spec=Balance)
    balance_obj.address = address
    balance_obj.ticker = ticker.upper()
    balance_obj.balance = balance
    return balance_obj


class TestBRC20Processor:

    @pytest.fixture
    def mock_db_session(self):
        return Mock(spec=Session)

    @pytest.fixture
    def mock_bitcoin_rpc(self):
        return Mock(spec=BitcoinRPCService)

    @pytest.fixture
    def processor(self, mock_db_session, mock_bitcoin_rpc):
        return BRC20Processor(mock_db_session, mock_bitcoin_rpc)

    def test_process_deploy_success(self, processor, mock_db_session):
        operation = {"op": "deploy", "tick": "TEST", "m": "1000000", "l": "1000"}

        tx_info = {
            "txid": "test_txid",
            "block_height": 800000,
            "vin": [{"address": "test_deployer_address"}],
            "vout": [],
        }

        _hex_data = "test_hex_data"

        with patch.object(processor, "get_first_input_address", return_value="test_deployer_address"):
            with patch.object(
                processor.validator,
                "validate_complete_operation",
                return_value=ValidationResult(True),
            ):
                with patch.object(processor, "log_operation"):
                    processor.current_block_timestamp = 1677649200
                    processor.process_deploy(operation, tx_info, intermediate_deploys={})

                    mock_db_session.add.assert_called_once()

                    deploy_call = mock_db_session.add.call_args[0][0]
                    assert isinstance(deploy_call, Deploy)
                    assert deploy_call.ticker == "TEST"
                    assert deploy_call.max_supply == "1000000"
                    assert deploy_call.limit_per_op == "1000"

    def test_process_mint_within_limits(self, processor, mock_db_session):
        operation = {"op": "mint", "tick": "TEST", "amt": "500"}

        tx_info = {
            "txid": "test_txid",
            "vout": [
                {"n": 0, "scriptPubKey": {"type": "nulldata", "hex": "6a..."}},
                {"n": 1, "scriptPubKey": {"addresses": ["test_recipient"]}},
            ],
        }

        _hex_data = "test_hex_data"
        _block_height = 800000

        with patch.object(
            processor.validator,
            "get_output_after_op_return_address",
            return_value="test_recipient",
        ):

            with patch.object(
                processor.validator,
                "get_deploy_record",
                return_value=create_mock_deploy(),
            ):
                with patch.object(
                    processor.validator,
                    "get_total_minted",
                    return_value="0",
                ):
                    with patch.object(
                        processor.validator,
                        "validate_complete_operation",
                        return_value=ValidationResult(True),
                    ):
                        with patch.object(processor, "update_balance") as mock_update:
                            with patch.object(processor, "log_operation"):
                                from src.opi.contracts import IntermediateState

                                state = IntermediateState()
                                result = processor.process_mint(
                                    operation,
                                    tx_info,
                                    intermediate_state=state,
                                )

                                assert result.is_valid is True

                                mock_update.assert_called_once_with(
                                    address="test_recipient",
                                    ticker="TEST",
                                    amount_delta="500",
                                    op_type="mint",
                                    txid="test_txid",
                                    intermediate_state=state,
                                )

    def test_mint_op_return_position_before_block_height(self, processor):
        operation = {"op": "mint", "tick": "TEST", "amt": "500"}

        tx_info = {
            "txid": "test_txid",
            "block_height": 800000,
            "vout": [
                {
                    "n": 0,
                    "scriptPubKey": {
                        "type": "pubkeyhash",
                        "addresses": ["regular_address"],
                    },
                },
                {"n": 1, "scriptPubKey": {"type": "nulldata", "hex": "6a..."}},
                {"n": 2, "scriptPubKey": {"addresses": ["test_recipient"]}},
            ],
        }

        _hex_data = "test_hex_data"
        _block_height = 800000

        with patch.object(
            processor.validator,
            "get_output_after_op_return_address",
            return_value="test_recipient",
        ):
            with patch.object(
                processor.validator,
                "get_deploy_record",
                return_value=create_mock_deploy(),
            ):
                with patch.object(
                    processor.validator,
                    "get_total_minted",
                    return_value="0",
                ):
                    with patch.object(
                        processor.validator,
                        "validate_complete_operation",
                        return_value=ValidationResult(True),
                    ):
                        with patch.object(processor, "update_balance") as mock_update:
                            with patch.object(processor, "log_operation"):
                                with patch.object(
                                    processor.parser,
                                    "extract_op_return_data",
                                    return_value=("valid_data", 1),
                                ):
                                    from src.opi.contracts import IntermediateState

                                    state = IntermediateState()
                                    result = processor.process_mint(
                                        operation,
                                        tx_info,
                                        intermediate_state=state,
                                    )

                                    assert result.is_valid is True
                                    mock_update.assert_called_once()

    def test_mint_op_return_position_after_block_height_valid(self, processor):
        operation = {"op": "mint", "tick": "TEST", "amt": "500"}

        tx_info = {
            "txid": "test_txid",
            "block_height": 990000,
            "vout": [
                {"n": 0, "scriptPubKey": {"type": "nulldata", "hex": "6a..."}},
                {"n": 1, "scriptPubKey": {"addresses": ["test_recipient"]}},
            ],
        }

        _hex_data = "test_hex_data"
        _block_height = 800000

        with patch.object(
            processor.validator,
            "get_output_after_op_return_address",
            return_value="test_recipient",
        ):
            with patch.object(
                processor.validator,
                "get_deploy_record",
                return_value=create_mock_deploy(),
            ):
                with patch.object(
                    processor.validator,
                    "get_total_minted",
                    return_value="0",
                ):
                    with patch.object(
                        processor.validator,
                        "validate_complete_operation",
                        return_value=ValidationResult(True),
                    ):
                        with patch.object(processor, "update_balance") as mock_update:
                            with patch.object(processor, "log_operation"):
                                with patch.object(
                                    processor.parser,
                                    "extract_op_return_data_with_position_check",
                                    return_value=("valid_data", 0),
                                ):
                                    from src.opi.contracts import IntermediateState

                                    state = IntermediateState()
                                    result = processor.process_mint(
                                        operation,
                                        tx_info,
                                        intermediate_state=state,
                                    )

                                    assert result.is_valid is True
                                    mock_update.assert_called_once()

    def test_mint_op_return_position_after_block_height_invalid(self, processor):
        operation = {"op": "mint", "tick": "TEST", "amt": "500"}

        tx_info = {
            "txid": "test_txid",
            "block_height": 990000,
            "vout": [
                {
                    "n": 0,
                    "scriptPubKey": {
                        "type": "pubkeyhash",
                        "addresses": ["regular_address"],
                    },
                },
                {"n": 1, "scriptPubKey": {"type": "nulldata", "hex": "6a..."}},
                {"n": 2, "scriptPubKey": {"addresses": ["test_recipient"]}},
            ],
        }

        _hex_data = "test_hex_data"
        _block_height = 800000

        with patch.object(
            processor.validator,
            "get_deploy_record",
            return_value=create_mock_deploy(),
        ):
            with patch.object(
                processor.validator,
                "get_total_minted",
                return_value="0",
            ):
                with patch.object(
                    processor.validator,
                    "validate_mint",
                    return_value=ValidationResult(
                        False,
                        "OP_RETURN_NOT_FIRST",
                        "OP_RETURN must be in first position after block 984444",
                    ),
                ):
                    with patch.object(processor, "log_operation"):
                        with patch.object(
                            processor.parser,
                            "extract_op_return_data_with_position_check",
                            return_value=(None, None),
                        ):
                            from src.opi.contracts import IntermediateState

                            state = IntermediateState()
                            result = processor.process_mint(
                                operation,
                                tx_info,
                                intermediate_state=state,
                            )

                            assert result.is_valid is False
                            assert "OP_RETURN_NOT_FIRST" in result.error_code
                            assert "984444" in result.error_message

    def test_process_transfer_sufficient_balance(self, processor, mock_db_session):
        operation = {"op": "transfer", "tick": "TEST", "amt": "100"}

        tx_info = {
            "txid": "test_txid",
            "vin": [{"address": "sender_address"}],
            "vout": [
                {"n": 0, "scriptPubKey": {"type": "nulldata", "hex": "6a..."}},
                {"n": 1, "scriptPubKey": {"addresses": ["recipient_address"]}},
            ],
        }

        _hex_data = "test_hex_data"
        _block_height = 800000

        with patch.object(processor, "classify_transfer_type", return_value=TransferType.SIMPLE):
            with patch.object(
                processor,
                "get_first_input_address",
                return_value="sender_address",
            ):
                with patch.object(
                    processor.validator,
                    "get_output_after_op_return_address",
                    return_value="recipient_address",
                ):
                    with patch.object(
                        processor.validator,
                        "validate_complete_operation",
                        return_value=ValidationResult(True),
                    ):
                        with patch.object(processor, "update_balance") as mock_update:
                            with patch.object(processor, "log_operation"):
                                validation_result = ValidationResult(True)
                                from src.opi.contracts import IntermediateState

                                state = IntermediateState()
                                processor.process_transfer(
                                    operation,
                                    tx_info,
                                    validation_result,
                                    _hex_data,
                                    _block_height,
                                    intermediate_state=state,
                                )

                                assert mock_update.call_count == 2

                                debit_call = mock_update.call_args_list[0]
                                assert debit_call[1]["address"] == "sender_address"
                                assert debit_call[1]["amount_delta"] == "-100"
                                assert debit_call[1]["op_type"] == "transfer_out"

                                credit_call = mock_update.call_args_list[1]
                                assert credit_call[1]["address"] == "recipient_address"
                                assert credit_call[1]["amount_delta"] == "100"
                                assert credit_call[1]["op_type"] == "transfer_in"

    def test_process_transfer_exceeds_mint_limit(self, processor, mock_db_session):
        operation = {"op": "transfer", "tick": "TEST", "amt": "5000"}

        tx_info = {
            "txid": "test_txid",
            "vin": [{"address": "sender_address"}],
            "vout": [
                {"n": 0, "scriptPubKey": {"type": "nulldata", "hex": "6a..."}},
                {"n": 1, "scriptPubKey": {"addresses": ["recipient_address"]}},
            ],
        }

        _hex_data = "test_hex_data"
        _block_height = 800000

        with patch.object(processor, "classify_transfer_type", return_value=TransferType.SIMPLE):
            with patch.object(
                processor,
                "get_first_input_address",
                return_value="sender_address",
            ):
                with patch.object(
                    processor.validator,
                    "get_output_after_op_return_address",
                    return_value="recipient_address",
                ):
                    with patch.object(
                        processor.validator,
                        "validate_complete_operation",
                        return_value=ValidationResult(True),
                    ):
                        with patch.object(processor, "update_balance") as mock_update:
                            with patch.object(processor, "log_operation"):
                                validation_result = ValidationResult(True)
                                from src.opi.contracts import IntermediateState

                                state = IntermediateState()
                                result = processor.process_transfer(
                                    operation,
                                    tx_info,
                                    validation_result,
                                    _hex_data,
                                    _block_height,
                                    intermediate_state=state,
                                )

                                assert result.is_valid is True

                                assert mock_update.call_count == 2

                                debit_call = mock_update.call_args_list[0]
                                assert debit_call[1]["amount_delta"] == "-5000"

    def test_allocation_first_standard_output(self, processor):
        tx_outputs = [
            {"scriptPubKey": {"hex": "6a" + "20" + "0" * 64}},
            {"scriptPubKey": {"hex": "76a914" + "0" * 40 + "88ac"}},
            {"scriptPubKey": {"hex": "76a914" + "1" * 40 + "88ac"}},
        ]

        with patch(
            "src.utils.bitcoin.extract_address_from_script",
            return_value="first_standard_address",
        ):
            address = processor.validator.get_first_standard_output_address(tx_outputs)
            assert address is not None

    def test_allocation_skip_op_return(self, processor):
        tx_outputs = [{"scriptPubKey": {"hex": "6a" + "20" + "0" * 64}}]

        address = processor.validator.get_first_standard_output_address(tx_outputs)
        assert address is None

    def test_allocation_multiple_outputs(self, processor):
        tx_outputs = [
            {"scriptPubKey": {"hex": "76a914" + "0" * 40 + "88ac"}},
            {"scriptPubKey": {"hex": "76a914" + "1" * 40 + "88ac"}},
        ]

        with patch("src.utils.bitcoin.extract_address_from_script") as mock_extract:
            mock_extract.side_effect = ["first_address", "second_address"]

            address = processor.validator.get_first_standard_output_address(tx_outputs)
            assert address is None

    def test_log_all_operations(self, processor, mock_db_session):
        operation_data = {"op": "mint", "tick": "TEST", "amt": "100"}
        validation_result = ValidationResult(True, None, None)
        tx_info = {
            "txid": "test_txid",
            "block_height": 800000,
            "block_hash": "test_block_hash",
            "tx_index": 0,
            "vout": [
                {"n": 0, "scriptPubKey": {"type": "nulldata", "hex": "6a..."}},
                {"n": 1, "scriptPubKey": {"addresses": ["recipient"]}},
            ],
        }
        raw_op_return = "test_op_return_data"
        parsed_json = '{"op":"mint","tick":"TEST","amt":"100"}'

        with patch.object(processor, "get_first_input_address", return_value="sender"):
            with patch.object(
                processor.validator,
                "get_output_after_op_return_address",
                return_value="recipient",
            ):
                processor.current_block_timestamp = 1677649200
                processor.log_operation(
                    operation_data,
                    validation_result,
                    tx_info,
                    raw_op_return,
                    parsed_json,
                )

                mock_db_session.add.assert_called_once()

                operation_call = mock_db_session.add.call_args[0][0]
                assert isinstance(operation_call, BRC20Operation)
                assert operation_call.txid == "test_txid"
                assert operation_call.operation == "mint"
                assert operation_call.ticker == "TEST"
                assert operation_call.amount == "100"
                assert operation_call.is_valid is True

    def test_update_balance_mint(self, processor, mock_db_session):
        with patch.object(processor.validator, "get_balance", return_value=Decimal("0")):
            with patch.object(Balance, "get_or_create", return_value=create_mock_balance()):
                from src.opi.contracts import IntermediateState

                state = IntermediateState()
                processor.update_balance("test_address", "TEST", "100", "mint", "test_txid", intermediate_state=state)

            assert state.balances[("test_address", "TEST")] == Decimal("100")

    def test_update_balance_transfer_debit(self, processor, mock_db_session):
        with patch.object(processor.validator, "get_balance", return_value=Decimal("1000")):
            with patch.object(Balance, "get_or_create", return_value=create_mock_balance()):
                from src.opi.contracts import IntermediateState

                state = IntermediateState()
                processor.update_balance(
                    "test_address", "TEST", "-100", "transfer_out", "test_txid", intermediate_state=state
                )

            assert state.balances[("test_address", "TEST")] == Decimal("900")

    def test_update_balance_insufficient_funds(self, processor, mock_db_session):
        with patch.object(processor.validator, "get_balance", return_value=Decimal("50")):
            from src.opi.contracts import IntermediateState

            result = processor.update_balance(
                "test_address", "TEST", "-100", "transfer_out", "test_txid", intermediate_state=IntermediateState()
            )
            assert result is False

    def test_classify_transfer_type_simple(self, processor):
        tx_info = {
            "vin": [{"txid": "test", "vout": 0}],
            "vout": [
                {"scriptPubKey": {"type": "nulldata"}},
                {"scriptPubKey": {"type": "pubkeyhash"}},
            ],
        }

        with patch.object(processor, "_has_marketplace_sighash", return_value=False):
            result = processor.classify_transfer_type(tx_info, 900000)
            assert result == TransferType.SIMPLE

    def test_classify_transfer_type_valid_marketplace(self, processor):
        tx_info = {
            "vin": [
                {"txinwitness": ["...83"], "txid": "tx1", "vout": 0},
                {"txinwitness": ["...83"], "txid": "tx2", "vout": 0},
                {"txinwitness": ["...01"], "txid": "tx3", "vout": 0},
            ]
        }

        with patch.object(processor, "_has_marketplace_sighash", return_value=True):
            with patch.object(
                processor,
                "validate_marketplace_transfer",
                return_value=ValidationResult(True),
            ):
                result = processor.classify_transfer_type(tx_info, 901350)
                assert result == TransferType.MARKETPLACE

    def test_classify_transfer_type_invalid_marketplace(self, processor):
        tx_info = {
            "vin": [
                {"txinwitness": ["...83"], "txid": "tx1", "vout": 0},
                {"txinwitness": ["...01"], "txid": "tx2", "vout": 0},
            ]
        }

        with patch.object(processor, "_has_marketplace_sighash", return_value=True):
            with patch.object(
                processor,
                "validate_marketplace_transfer",
                return_value=ValidationResult(False, "INVALID_MARKETPLACE_TRANSACTION", "Invalid template"),
            ):
                result = processor.classify_transfer_type(tx_info, 901350)
                assert result == TransferType.INVALID_MARKETPLACE

    def test_invalid_marketplace_early_return_performance(self, processor):
        import time

        from src.utils.exceptions import TransferType

        invalid_marketplace_tx = {
            "txid": "invalid_test",
            "vin": [
                {"txinwitness": ["...83"], "txid": "tx1", "vout": 0},
                {"txinwitness": ["...01"], "txid": "tx2", "vout": 0},
            ],
            "vout": [
                {"scriptPubKey": {"type": "nulldata"}},
                {"scriptPubKey": {"type": "pubkeyhash"}},
            ],
        }

        with patch.object(
            processor,
            "classify_transfer_type",
            return_value=TransferType.INVALID_MARKETPLACE,
        ):
            with patch.object(processor, "log_operation"):
                with patch.object(
                    processor.parser,
                    "extract_op_return_data",
                    return_value=("test_hex", 0),
                ):
                    with patch.object(
                        processor.parser,
                        "extract_op_return_data_with_position_check",
                        return_value=("test_hex", 0),
                    ):
                        with patch.object(
                            processor.parser,
                            "parse_brc20_operation",
                            return_value={
                                "success": True,
                                "data": {
                                    "op": "transfer",
                                    "tick": "TEST",
                                    "amt": "100",
                                },
                            },
                        ):

                            start_time = time.time()
                            result = processor.process_transaction(
                                invalid_marketplace_tx,
                                901350,
                                0,
                                1677649200,
                                "test_block_hash",
                            )
                            processing_time = time.time() - start_time

                            assert processing_time < 0.1
                            result, _, _ = result
                            assert not result.is_valid
                            assert not result.is_valid

    def test_process_transfer_with_type_logging(self, processor):
        from src.utils.exceptions import TransferType

        operation = {"op": "transfer", "tick": "TEST", "amt": "100"}

        tx_info = {
            "txid": "test_txid",
            "vin": [{"address": "sender_address"}],
            "vout": [
                {"n": 0, "scriptPubKey": {"type": "nulldata", "hex": "6a..."}},
                {"n": 1, "scriptPubKey": {"addresses": ["recipient_address"]}},
            ],
        }

        _hex_data = "test_hex_data"
        _block_height = 800000

        with patch.object(processor, "classify_transfer_type", return_value=TransferType.MARKETPLACE):

            with patch.object(
                processor,
                "get_first_input_address",
                return_value="sender_address",
            ):
                with patch.object(
                    processor.validator,
                    "get_output_after_op_return_address",
                    return_value="recipient_address",
                ):
                    with patch.object(
                        processor.validator,
                        "validate_complete_operation",
                        return_value=ValidationResult(True),
                    ):
                        from src.opi.contracts import IntermediateState

                        with patch.object(processor, "update_balance"):
                            with patch.object(processor, "log_operation"):
                                validation_result = ValidationResult(True)
                                result = processor.process_transfer(
                                    operation,
                                    tx_info,
                                    validation_result,
                                    _hex_data,
                                    _block_height,
                                    intermediate_state=IntermediateState(),
                                )

                            assert result.is_valid is True

    def test_marketplace_transfer_op_return_any_position_valid(self, processor):
        from src.utils.exceptions import TransferType

        marketplace_tx = {
            "txid": "marketplace_test_txid",
            "vin": [
                {
                    "txinwitness": [
                        "3045022100a1b2c3d4e5f6a7b8c9d0e1f2a3b4c5d6e7f8a9b0"
                        "c1d2e3f4a5b6c7d8e9f0a1b20220a1b2c3d4e5f6a7b8c9d0e1f2"
                        "a3b4c5d6e7f8a9b0c1d2e3f4a5b6c7d8e9f0a1b283"
                    ],
                    "txid": "tx1",
                    "vout": 0,
                },
                {
                    "txinwitness": [
                        "3045022100a1b2c3d4e5f6a7b8c9d0e1f2a3b4c5d6e7f8a9b0"
                        "c1d2e3f4a5b6c7d8e9f0a1b20220a1b2c3d4e5f6a7b8c9d0e1f2"
                        "a3b4c5d6e7f8a9b0c1d2e3f4a5b6c7d8e9f0a1b283"
                    ],
                    "txid": "tx2",
                    "vout": 0,
                },
                {"txinwitness": ["...01"], "txid": "tx3", "vout": 0},
            ],
            "vout": [
                {
                    "scriptPubKey": {
                        "type": "pubkeyhash",
                        "addresses": ["1FirstAddress"],
                    }
                },
                {
                    "scriptPubKey": {
                        "type": "nulldata",
                        "hex": "6a4c547b2270223a226272632d3230222c226f70223a22747261"
                        "6e73666572222c227469636b223a2254455354222c22616d74223a"
                        "2231303030227d",
                    }
                },
                {
                    "scriptPubKey": {
                        "type": "pubkeyhash",
                        "addresses": ["1RecipientAddress"],
                    }
                },
            ],
            "block_height": 901350,
            "block_hash": "test_block_hash",
            "tx_index": 1,
        }

        with patch.object(
            processor.parser,
            "extract_op_return_data",
            return_value=(
                "7b2270223a226272632d3230222c226f70223a227472616e73666572222c22"
                "7469636b223a2254455354222c22616d74223a2231303030227d",
                1,
            ),
        ):
            with patch.object(
                processor.parser,
                "parse_brc20_operation",
                return_value={
                    "success": True,
                    "data": {"op": "transfer", "tick": "TEST", "amt": "1000"},
                },
            ):
                with patch.object(
                    processor,
                    "classify_transfer_type",
                    return_value=TransferType.MARKETPLACE,
                ):
                    with patch.object(
                        processor.validator,
                        "validate_complete_operation",
                        return_value=ValidationResult(True),
                    ):
                        with patch.object(
                            processor,
                            "get_first_input_address",
                            return_value="1SenderAddress",
                        ):
                            with patch.object(
                                processor.validator,
                                "get_output_after_op_return_address",
                                return_value="1RecipientAddress",
                            ):
                                with patch.object(processor, "update_balance"):
                                    with patch.object(processor, "log_operation"):

                                        result = processor.process_transaction(
                                            marketplace_tx,
                                            901350,
                                            1,
                                            1677649200,
                                            "test_block_hash",
                                        )

                                        result, _, _ = result
                                        assert result.is_valid
                                        assert result.error_message is None

    def test_simple_transfer_op_return_not_first_position_invalid(self, processor):
        from src.utils.exceptions import TransferType

        simple_tx = {
            "txid": "simple_test_txid",
            "vin": [{"txinwitness": ["...01"], "txid": "tx1", "vout": 0}],
            "vout": [
                {
                    "scriptPubKey": {
                        "type": "pubkeyhash",
                        "addresses": ["1FirstAddress"],
                    }
                },
                {
                    "scriptPubKey": {
                        "type": "nulldata",
                        "hex": "6a4c547b2270223a226272632d3230222c226f70223a22747261"
                        "6e73666572222c227469636b223a2254455354222c22616d74223a"
                        "2231303030227d",
                    }
                },
                {
                    "scriptPubKey": {
                        "type": "pubkeyhash",
                        "addresses": ["1RecipientAddress"],
                    }
                },
            ],
            "block_height": 901350,
            "block_hash": "test_block_hash",
            "tx_index": 1,
        }

        with patch.object(
            processor.parser,
            "extract_op_return_data",
            return_value=(
                "7b2270223a226272632d3230222c226f70223a227472616e73666572222c22"
                "7469636b223a2254455354222c22616d74223a2231303030227d",
                1,
            ),
        ):
            with patch.object(
                processor.parser,
                "parse_brc20_operation",
                return_value={
                    "success": True,
                    "data": {"op": "transfer", "tick": "TEST", "amt": "1000"},
                },
            ):
                with patch.object(
                    processor,
                    "classify_transfer_type",
                    return_value=TransferType.SIMPLE,
                ):
                    with patch.object(
                        processor.parser,
                        "extract_op_return_data_with_position_check",
                        return_value=(None, None),
                    ):
                        with patch.object(processor, "log_operation"):

                            result = processor.process_transaction(simple_tx, 901350, 1, 1677649200, "test_block_hash")

                            result, _, _ = result
                            assert not result.is_valid
