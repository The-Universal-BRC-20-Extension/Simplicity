from unittest.mock import Mock, patch

import pytest
from sqlalchemy.orm import Session

from src.models.balance import Balance
from src.models.deploy import Deploy
from src.models.transaction import BRC20Operation
from src.services.bitcoin_rpc import BitcoinRPCService
from src.services.processor import BRC20Processor
from src.services.validator import ValidationResult
from src.utils.exceptions import TransferType


class TestIntegration:

    @pytest.fixture
    def mock_db_session(self):
        return Mock(spec=Session)

    @pytest.fixture
    def mock_bitcoin_rpc(self):
        return Mock(spec=BitcoinRPCService)

    @pytest.fixture
    def processor(self, mock_db_session, mock_bitcoin_rpc):
        return BRC20Processor(mock_db_session, mock_bitcoin_rpc)

    def test_complete_token_lifecycle(self, processor, mock_db_session):
        # Step 1: Deploy
        deploy_operation = {"op": "deploy", "tick": "TEST", "m": "1000000", "l": "1000"}

        deploy_tx = {
            "txid": "deploy_txid",
            "block_height": 800000,
            "vin": [{"address": "deployer_address"}],
            "vout": [],
        }

        with patch.object(processor, "get_first_input_address", return_value="deployer_address"):
            processor.current_block_timestamp = 1677649200  # Set block timestamp

            with patch.object(
                processor.validator,
                "validate_complete_operation",
                return_value=ValidationResult(True),
            ):
                processor.process_deploy(deploy_operation, deploy_tx, intermediate_deploys={})

                assert mock_db_session.add.call_count >= 1

                added_objects = [call[0][0] for call in mock_db_session.add.call_args_list]

                deploy_obj = None
                for obj in added_objects:
                    if isinstance(obj, Deploy):
                        deploy_obj = obj
                        break

                if deploy_obj:
                    assert deploy_obj.ticker == "TEST"
                    assert deploy_obj.max_supply == "1000000"
                    assert deploy_obj.limit_per_op == "1000"
                else:
                    assert any(isinstance(obj, BRC20Operation) for obj in added_objects)

        mock_db_session.reset_mock()

        mint_operation = {"op": "mint", "tick": "TEST", "amt": "500"}

        mint_tx = {
            "txid": "mint_txid",
            "vout": [
                {"n": 0, "scriptPubKey": {"type": "nulldata", "hex": "6a20"}},
                {"n": 1, "scriptPubKey": {"addresses": ["minter_address"]}},
            ],
        }

        mock_balance = Mock()
        mock_balance.add_amount = Mock()

        with patch.object(
            processor.validator,
            "get_first_standard_output_address",
            return_value="minter_address",
        ):

            with patch.object(
                processor.validator,
                "validate_complete_operation",
                return_value=ValidationResult(True),
            ):
                with patch.object(
                    processor.validator,
                    "get_deploy_record",
                    return_value=Mock(ticker="TEST", max_supply="1000000", limit_per_op="1000"),
                ):
                    with patch.object(
                        processor.validator,
                        "get_total_minted",
                        return_value="0",
                    ):
                        from src.opi.contracts import IntermediateState

                        state = IntermediateState()
                        with patch.object(processor, "update_balance") as mock_update:
                            result = processor.process_mint(
                                mint_operation,
                                mint_tx,
                                intermediate_state=state,
                            )

                            # Check if the result is valid
                            if not result.is_valid:
                                print(f"Validation failed: {result.error_message}")
                            assert result.is_valid is True

                            mock_update.assert_called_once_with(
                                address="minter_address",
                                ticker="TEST",
                                amount_delta="500",
                                op_type="mint",
                                txid="mint_txid",
                                intermediate_state=state,
                            )

        mock_db_session.reset_mock()

        transfer_operation = {"op": "transfer", "tick": "TEST", "amt": "200"}

        transfer_tx = {
            "txid": "transfer_txid",
            "vin": [{"address": "minter_address"}],
            "vout": [
                {"n": 0, "scriptPubKey": {"type": "nulldata", "hex": "6a20"}},
                {"n": 1, "scriptPubKey": {"addresses": ["recipient_address"]}},
            ],
        }

        mock_sender_balance = Mock()
        mock_sender_balance.subtract_amount = Mock(return_value=True)
        mock_recipient_balance = Mock()
        mock_recipient_balance.add_amount = Mock()

        with patch.object(processor, "get_first_input_address", return_value="minter_address"):
            with patch.object(
                processor.validator,
                "get_first_standard_output_address",
                return_value="recipient_address",
            ):
                with patch.object(
                    processor,
                    "classify_transfer_type",
                    return_value=TransferType.SIMPLE,
                ):

                    with patch.object(
                        processor,
                        "resolve_transfer_addresses",
                        return_value={
                            "sender": "minter_address",
                            "recipient": "recipient_address",
                        },
                    ):
                        with patch.object(
                            processor.validator,
                            "validate_complete_operation",
                            return_value=ValidationResult(True),
                        ):
                            from src.opi.contracts import IntermediateState

                            state = IntermediateState()
                            with patch.object(processor, "update_balance") as mock_update:
                                processor.process_transfer(
                                    transfer_operation,
                                    transfer_tx,
                                    ValidationResult(True),
                                    "test_hex_data",
                                    800000,
                                    intermediate_state=state,
                                )

                                assert mock_update.call_count == 2

                                # Check the debit call
                                debit_call = mock_update.call_args_list[0]
                                assert debit_call[1]["address"] == "minter_address"
                                assert debit_call[1]["amount_delta"] == "-200"
                                assert debit_call[1]["op_type"] == "transfer_out"

                                # Check the credit call
                                credit_call = mock_update.call_args_list[1]
                                assert credit_call[1]["address"] == "recipient_address"
                                assert credit_call[1]["amount_delta"] == "200"
                                assert credit_call[1]["op_type"] == "transfer_in"

    def test_multiple_mints_same_block(self, processor, mock_db_session):
        mint_operation = {"op": "mint", "tick": "TEST", "amt": "100"}

        mint_tx1 = {
            "txid": "mint_txid_1",
            "vout": [
                {"n": 0, "scriptPubKey": {"type": "nulldata", "hex": "6a20"}},
                {"n": 1, "scriptPubKey": {"addresses": ["address1"]}},
            ],
        }

        mint_tx2 = {
            "txid": "mint_txid_2",
            "vout": [
                {"n": 0, "scriptPubKey": {"type": "nulldata", "hex": "6a20"}},
                {"n": 1, "scriptPubKey": {"addresses": ["address2"]}},
            ],
        }

        mock_balance1 = Mock()
        mock_balance1.add_amount = Mock()
        mock_balance2 = Mock()
        mock_balance2.add_amount = Mock()

        with patch.object(processor.validator, "get_first_standard_output_address") as mock_get_address:
            mock_get_address.side_effect = ["address1", "address2"]

            with patch.object(
                processor.validator,
                "validate_complete_operation",
                return_value=ValidationResult(True),
            ):
                with patch.object(
                    processor.validator,
                    "get_deploy_record",
                    return_value=Mock(ticker="TEST", max_supply="1000000", limit_per_op="1000"),
                ):
                    with patch.object(
                        processor.validator,
                        "get_total_minted",
                        return_value="0",
                    ):
                        from src.opi.contracts import IntermediateState

                        state = IntermediateState()
                        with patch.object(processor, "update_balance") as mock_update:
                            processor.process_mint(
                                mint_operation,
                                mint_tx1,
                                intermediate_state=state,
                            )
                            processor.process_mint(
                                mint_operation,
                                mint_tx2,
                                intermediate_state=state,
                            )

                            assert mock_update.call_count == 2
                            # Check first mint
                            first_call = mock_update.call_args_list[0]
                            assert first_call[1]["address"] == "address1"
                            assert first_call[1]["amount_delta"] == "100"
                            assert first_call[1]["op_type"] == "mint"
                            # Check second mint
                            second_call = mock_update.call_args_list[1]
                            assert second_call[1]["address"] == "address2"
                            assert second_call[1]["amount_delta"] == "100"
                            assert second_call[1]["op_type"] == "mint"

    def test_transfer_entire_balance(self, processor, mock_db_session):
        transfer_operation = {"op": "transfer", "tick": "TEST", "amt": "1000"}

        transfer_tx = {
            "txid": "transfer_txid",
            "vin": [{"address": "sender_address"}],
            "vout": [
                {"n": 0, "scriptPubKey": {"type": "nulldata", "hex": "6a20"}},
                {"n": 1, "scriptPubKey": {"addresses": ["recipient_address"]}},
            ],
        }

        mock_sender_balance = Mock()
        mock_sender_balance.subtract_amount = Mock(return_value=True)
        mock_recipient_balance = Mock()
        mock_recipient_balance.add_amount = Mock()

        with patch.object(processor, "get_first_input_address", return_value="sender_address"):
            with patch.object(
                processor.validator,
                "get_first_standard_output_address",
                return_value="recipient_address",
            ):
                with patch.object(Balance, "get_or_create") as mock_get_or_create:
                    mock_get_or_create.side_effect = [
                        mock_sender_balance,
                        mock_recipient_balance,
                    ]

                    with patch.object(
                        processor,
                        "classify_transfer_type",
                        return_value=TransferType.SIMPLE,
                    ):

                        with patch.object(
                            processor,
                            "resolve_transfer_addresses",
                            return_value={
                                "sender": "sender_address",
                                "recipient": "recipient_address",
                            },
                        ):
                            with patch.object(
                                processor.validator,
                                "validate_complete_operation",
                                return_value=ValidationResult(True),
                            ):
                                from src.opi.contracts import IntermediateState

                                state = IntermediateState()
                                from src.opi.contracts import IntermediateState

                                state = IntermediateState()
                                from src.opi.contracts import IntermediateState

                                state = IntermediateState()
                                from src.opi.contracts import IntermediateState

                                state = IntermediateState()
                                with patch.object(processor, "update_balance") as mock_update:
                                    processor.process_transfer(
                                        transfer_operation,
                                        transfer_tx,
                                        ValidationResult(True),
                                        "test_hex_data",
                                        800000,
                                        intermediate_state=state,
                                    )

                                    assert mock_update.call_count == 2

                                    # Check the debit call
                                    debit_call = mock_update.call_args_list[0]
                                    assert debit_call[1]["address"] == "sender_address"
                                    assert debit_call[1]["amount_delta"] == "-1000"
                                    assert debit_call[1]["op_type"] == "transfer_out"

                                    # Check the credit call
                                    credit_call = mock_update.call_args_list[1]
                                    assert credit_call[1]["address"] == "recipient_address"
                                    assert credit_call[1]["amount_delta"] == "1000"
                                    assert credit_call[1]["op_type"] == "transfer_in"

    def test_transfer_amount_exceeding_mint_limit(self, processor, mock_db_session):
        transfer_operation = {"op": "transfer", "tick": "TEST", "amt": "3000"}

        transfer_tx = {
            "txid": "transfer_txid",
            "vin": [{"address": "sender_address"}],
            "vout": [
                {"n": 0, "scriptPubKey": {"type": "nulldata", "hex": "6a20"}},
                {"n": 1, "scriptPubKey": {"addresses": ["recipient_address"]}},
            ],
        }

        mock_sender_balance = Mock()
        mock_sender_balance.subtract_amount = Mock(return_value=True)
        mock_recipient_balance = Mock()
        mock_recipient_balance.add_amount = Mock()

        with patch.object(processor, "get_first_input_address", return_value="sender_address"):
            with patch.object(
                processor.validator,
                "get_first_standard_output_address",
                return_value="recipient_address",
            ):
                with patch.object(Balance, "get_or_create") as mock_get_or_create:
                    mock_get_or_create.side_effect = [
                        mock_sender_balance,
                        mock_recipient_balance,
                    ]

                    with patch.object(
                        processor,
                        "classify_transfer_type",
                        return_value=TransferType.SIMPLE,
                    ):

                        with patch.object(
                            processor,
                            "resolve_transfer_addresses",
                            return_value={
                                "sender": "sender_address",
                                "recipient": "recipient_address",
                            },
                        ):
                            with patch.object(
                                processor.validator,
                                "validate_complete_operation",
                                return_value=ValidationResult(True),
                            ):
                                from src.opi.contracts import IntermediateState

                                state = IntermediateState()
                                with patch.object(processor, "update_balance") as mock_update:
                                    processor.process_transfer(
                                        transfer_operation,
                                        transfer_tx,
                                        ValidationResult(True),
                                        "test_hex_data",
                                        800000,
                                        intermediate_state=state,
                                    )

                                    assert mock_update.call_count == 2

                                    # Check the debit call
                                    debit_call = mock_update.call_args_list[0]
                                    assert debit_call[1]["address"] == "sender_address"
                                    assert debit_call[1]["amount_delta"] == "-3000"
                                    assert debit_call[1]["op_type"] == "transfer_out"

                                    # Check the credit call
                                    credit_call = mock_update.call_args_list[1]
                                    assert credit_call[1]["address"] == "recipient_address"
                                    assert credit_call[1]["amount_delta"] == "3000"
                                    assert credit_call[1]["op_type"] == "transfer_in"

    def test_invalid_operations_logged(self, processor, mock_db_session):

        operation_data = {"op": "mint", "tick": "INVALID", "amt": "100"}
        validation_result = ValidationResult(False, "TICKER_NOT_DEPLOYED", "Ticker not deployed")
        tx_info = {
            "txid": "invalid_txid",
            "block_height": 800000,
            "block_hash": "test_block_hash",
            "tx_index": 0,
            "vout": [
                {"n": 0, "scriptPubKey": {"type": "nulldata", "hex": "6a20"}},
                {"n": 1, "scriptPubKey": {"addresses": ["recipient"]}},
            ],
        }
        raw_op_return = "invalid_op_return_data"
        parsed_json = '{"op":"mint","tick":"INVALID","amt":"100"}'

        with patch.object(processor, "get_first_input_address", return_value="sender"):
            with patch.object(
                processor.validator,
                "get_first_standard_output_address",
                return_value="recipient",
            ):
                processor.current_block_timestamp = 1677649200  # Set block timestamp
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
                assert operation_call.is_valid is False
                assert operation_call.error_code == "TICKER_NOT_DEPLOYED"
                assert operation_call.error_message == "Ticker not deployed"

    def test_complex_transaction_processing(self, processor, mock_db_session):

        tx = {
            "txid": "complex_txid",
            "block_height": 800000,
            "vin": [{"address": "sender_address"}],
            "vout": [
                {"scriptPubKey": {"hex": "6a" + "20" + "0" * 64}},
                {"scriptPubKey": {"hex": "76a914" + "0" * 40 + "88ac"}},
                {"scriptPubKey": {"hex": "76a914" + "1" * 40 + "88ac"}},
            ],
        }

        with patch.object(
            processor.parser,
            "extract_op_return_data",
            return_value=("op_return_data", 0),
        ):
            with patch.object(
                processor.parser,
                "parse_brc20_operation",
                return_value={
                    "success": True,
                    "data": {"op": "transfer", "tick": "TEST", "amt": "100"},
                },
            ):
                with patch.object(
                    processor.parser,
                    "extract_op_return_data_with_position_check",
                    return_value=("op_return_data", 0),
                ):
                    with patch.object(
                        processor.validator,
                        "validate_complete_operation",
                        return_value=ValidationResult(True, None, None),
                    ):
                        with patch.object(processor, "process_transfer") as mock_process:
                            mock_process.return_value = ValidationResult(True)

                            result, _, _ = processor.process_transaction(
                                tx,
                                tx.get("block_height"),
                                tx_index=0,
                                block_timestamp=1677649200,
                                block_hash="test_block_hash",
                            )

                            assert result.operation_found
                            assert result.is_valid

                            mock_process.assert_called_once()

    def test_error_handling_during_processing(self, processor, mock_db_session):

        tx = {
            "txid": "error_txid",
            "block_height": 800000,
            "vin": [{"address": "sender_address"}],
            "vout": [],
        }

        with patch.object(
            processor.parser,
            "extract_op_return_data",
            return_value=("op_return_data", 0),
        ):
            with patch.object(
                processor.parser,
                "parse_brc20_operation",
                return_value={
                    "success": True,
                    "data": {"op": "transfer", "tick": "TEST", "amt": "100"},
                },
            ):
                with patch.object(
                    processor.parser,
                    "extract_op_return_data_with_position_check",
                    return_value=("op_return_data", 0),
                ):
                    with patch.object(
                        processor.validator,
                        "validate_complete_operation",
                        return_value=ValidationResult(True, None, None),
                    ):
                        with patch.object(
                            processor,
                            "process_transfer",
                            side_effect=Exception("Processing error"),
                        ):
                            result, _, _ = processor.process_transaction(
                                tx,
                                tx.get("block_height"),
                                tx_index=0,
                                block_timestamp=1677649200,
                                block_hash="test_block_hash",
                            )

                            assert result.operation_found
                            assert not result.is_valid
                            assert "Processing error" in result.error_message
