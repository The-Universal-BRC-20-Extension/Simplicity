from unittest.mock import Mock
from decimal import Decimal
from src.opi.registry import OPIRegistry
from src.opi.contracts import Context, IntermediateState
from src.opi.operations.test_opi.processor import TestOPIProcessor


class TestOPIBasic:
    def test_opi_registry_registration(self):
        registry = OPIRegistry()
        registry.register("test_opi", TestOPIProcessor)

        assert registry.has_processor("test_opi")
        assert "test_opi" in registry.list_processors()

    def test_opi_processor_instantiation(self):
        registry = OPIRegistry()
        registry.register("test_opi", TestOPIProcessor)

        mock_state = IntermediateState()
        mock_validator = Mock()
        context = Context(mock_state, mock_validator)

        processor = registry.get_processor("test_opi", context)
        assert processor is not None
        assert isinstance(processor, TestOPIProcessor)

    def test_opi_processor_operation_processing(self):
        registry = OPIRegistry()
        registry.register("test_opi", TestOPIProcessor)

        mock_state = IntermediateState()
        mock_validator = Mock()
        mock_validator.get_deploy_record.return_value = {"max_supply": "1000000"}
        mock_validator.get_balance.return_value = Decimal("200")

        context = Context(mock_state, mock_validator)
        processor = registry.get_processor("test_opi", context)

        operation_data = {"op": "test_opi", "tick": "TEST", "amt": "100"}
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

        result, state = processor.process_op(operation_data, tx_info)

        assert result.operation_found is True
        assert result.is_valid is True
        assert len(state.orm_objects) == 1
        assert len(state.state_mutations) == 1
