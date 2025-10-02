from decimal import Decimal
from unittest.mock import Mock
from src.opi.operations.test_opi.processor import TestOPIProcessor
from src.opi.contracts import Context, IntermediateState


class TestTestOPIProcessor:
    def setup_method(self):
        self.state = IntermediateState()
        self.validator = Mock()
        self.context = Context(self.state, self.validator)
        self.processor = TestOPIProcessor(self.context)

    def test_process_op_missing_fields(self):
        op_data = {"op": "test_opi"}
        tx_info = {"txid": "test_tx"}

        result, state = self.processor.process_op(op_data, tx_info)

        assert result.operation_found is True
        assert result.is_valid is False
        assert "Missing required fields" in result.error_message
        assert state.orm_objects == []
        assert state.state_mutations == []

    def test_process_op_ticker_not_deployed(self):
        op_data = {"op": "test_opi", "tick": "TEST", "amt": "100"}
        tx_info = {"txid": "test_tx", "sender_address": "addr1"}

        self.validator.get_deploy_record.return_value = None

        result, state = self.processor.process_op(op_data, tx_info)

        assert result.operation_found is True
        assert result.is_valid is False
        assert "not deployed" in result.error_message
        assert state.orm_objects == []
        assert state.state_mutations == []

    def test_process_op_insufficient_balance(self):
        op_data = {"op": "test_opi", "tick": "TEST", "amt": "100"}
        tx_info = {"txid": "test_tx", "sender_address": "addr1"}

        deploy_record = Mock()
        self.validator.get_deploy_record.return_value = deploy_record
        self.validator.get_balance.return_value = Decimal("50")

        result, state = self.processor.process_op(op_data, tx_info)

        assert result.operation_found is True
        assert result.is_valid is False
        assert "Insufficient balance" in result.error_message
        assert state.orm_objects == []
        assert state.state_mutations == []

    def test_process_op_success(self):
        op_data = {"op": "test_opi", "tick": "TEST", "amt": "100"}
        tx_info = {
            "txid": "test_tx",
            "sender_address": "addr1",
            "block_height": 1000,
            "block_hash": "block_hash",
            "tx_index": 1,
            "vout_index": 0,
            "block_timestamp": 1234567890,
            "raw_op_return": "test_data",
        }

        deploy_record = Mock()
        self.validator.get_deploy_record.return_value = deploy_record
        self.validator.get_balance.return_value = Decimal("200")

        result, state = self.processor.process_op(op_data, tx_info)

        assert result.operation_found is True
        assert result.is_valid is True
        assert result.operation_type == "test_opi"
        assert result.ticker == "TEST"
        assert result.amount == "100"

        assert len(state.state_mutations) == 1
        mutation = state.state_mutations[0]

        test_state = IntermediateState()
        mutation(test_state)
        assert test_state.balances[("addr1", "TEST")] == Decimal("-100")

        assert len(state.orm_objects) == 1
        operation_record = state.orm_objects[0]
        assert operation_record.txid == "test_tx"
        assert operation_record.operation == "test_opi"
        assert operation_record.ticker == "TEST"
        assert operation_record.amount == "100"
        assert operation_record.from_address == "addr1"

    def test_process_op_uses_intermediate_state(self):
        op_data = {"op": "test_opi", "tick": "TEST", "amt": "100"}
        tx_info = {"txid": "test_tx", "sender_address": "addr1"}

        self.state.balances[("addr1", "TEST")] = Decimal("150")
        deploy_record = Mock()
        self.state.deploys["TEST"] = deploy_record

        result, state = self.processor.process_op(op_data, tx_info)

        assert result.is_valid is True

        self.validator.get_balance.assert_not_called()
        self.validator.get_deploy_record.assert_not_called()

    def test_state_immutability(self):
        op_data = {"op": "test_opi", "tick": "TEST", "amt": "100"}
        tx_info = {"txid": "test_tx", "sender_address": "addr1"}

        deploy_record = Mock()
        self.validator.get_deploy_record.return_value = deploy_record
        self.validator.get_balance.return_value = Decimal("200")

        result, state = self.processor.process_op(op_data, tx_info)

        assert hasattr(state, "__hash__")  # frozen dataclass should be hashable
