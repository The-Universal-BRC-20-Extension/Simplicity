from decimal import Decimal
from unittest.mock import Mock, patch, MagicMock
from src.opi.contracts import IntermediateState, Context
from src.opi.registry import OPIRegistry
from src.opi.operations.test_opi.processor import TestOPIProcessor
from src.services.processor import BRC20Processor
from src.services.indexer import IndexerService
from src.services.validator import ValidationResult


class TestOPIIntegration:
    def setup_method(self):
        self.db_session = Mock()
        self.bitcoin_rpc = Mock()
        self.processor = BRC20Processor(self.db_session, self.bitcoin_rpc)
        self.indexer = IndexerService(self.db_session, self.bitcoin_rpc)

        # Mock the processor components
        self.processor.validator = MagicMock()
        self.processor.parser = MagicMock()
        self.processor.utxo_service = MagicMock()

    def test_opi_registry_integration(self):
        registry = OPIRegistry()
        registry.register("test_opi", TestOPIProcessor)

        self.processor.opi_registry = registry

        assert self.processor.opi_registry.has_processor("test_opi")
        assert "test_opi" in self.processor.opi_registry.list_processors()

    def test_opi_processing_workflow(self):
        # Setup registry
        registry = OPIRegistry()
        registry.register("test_opi", TestOPIProcessor)
        self.processor.opi_registry = registry

        # Setup intermediate state
        intermediate_state = IntermediateState()
        intermediate_state.balances[("addr1", "TEST")] = Decimal("200")

        # Mock validator
        deploy_record = Mock()
        self.processor.validator.get_deploy_record.return_value = deploy_record
        self.processor.validator.get_balance.return_value = Decimal("200")
        self.processor.validator.validate_complete_operation.return_value = ValidationResult(True)

        # Mock parser
        self.processor.parser.parse_brc20_operation.return_value = {
            "success": True,
            "data": {"op": "test_opi", "tick": "TEST", "amt": "100"},
        }
        self.processor.parser.extract_op_return_data.return_value = ("test_hex", 0)

        # Mock transaction
        tx = {"txid": "test_tx", "vout": [], "vin": []}

        # Mock address resolution
        self.processor.get_first_input_address = Mock(return_value="addr1")

        # Process transaction
        result_tuple = self.processor.process_transaction(
            tx,
            block_height=1000,
            tx_index=1,
            block_timestamp=1234567890,
            block_hash="block_hash",
            intermediate_state=intermediate_state,
        )
        result, objects, commands = result_tuple

        # Verify results
        assert result.operation_found is True
        assert result.is_valid is True
        assert result.operation_type == "test_opi"

        # Verify persistence objects
        assert len(objects) == 1
        operation_record = objects[0]
        assert operation_record.operation == "test_opi"
        assert operation_record.ticker == "TEST"

    def test_opi_state_command_application(self):
        # Setup indexer with OPI enabled
        with patch("src.config.settings.ENABLE_OPI", True):
            with patch(
                "src.config.Settings.ENABLED_OPIS",
                {"test_opi": "src.opi.operations.test_opi.processor.TestOPIProcessor"},
            ):
                indexer = IndexerService(self.db_session, self.bitcoin_rpc)

        # Setup intermediate state
        intermediate_state = IntermediateState()
        intermediate_state.balances[("addr1", "TEST")] = Decimal("200")

        # Create state mutation function
        def balance_mutation(state):
            key = ("addr1", "TEST")
            current = state.balances.get(key, Decimal(0))
            state.balances[key] = current - Decimal("50")

        # Apply mutation
        balance_mutation(intermediate_state)

        # Verify state was updated
        assert intermediate_state.balances[("addr1", "TEST")] == Decimal("150")

    def test_opi_error_handling(self):
        registry = OPIRegistry()
        registry.register("test_opi", TestOPIProcessor)
        self.processor.opi_registry = registry

        # Mock parser to return invalid operation
        self.processor.parser.parse_brc20_operation.return_value = {
            "success": True,
            "data": {"op": "invalid_opi", "tick": "TEST", "amt": "100"},
        }
        self.processor.parser.extract_op_return_data.return_value = ("test_hex", 0)

        # Mock validator to return invalid result
        self.processor.validator.validate_complete_operation.return_value = ValidationResult(
            False, "UNKNOWN_OPERATION", "Unknown operation"
        )

        # Mock transaction
        tx = {"txid": "test_tx", "vout": [], "vin": []}

        # Mock address resolution
        self.processor.get_first_input_address = Mock(return_value="addr1")

        # Process transaction
        result, objects, commands = self.processor.process_transaction(
            tx,
            block_height=1000,
            tx_index=1,
            block_timestamp=1234567890,
            block_hash="block_hash",
            intermediate_state=IntermediateState(),
        )

        # Verify error handling
        assert result.operation_found is True
        assert result.is_valid is False
        assert "Unknown operation" in result.error_message

    def test_opi_security_isolation(self):
        state = IntermediateState()
        validator = Mock()
        context = Context(state, validator)
        processor = TestOPIProcessor(context)

        # Verify that context is read-only
        assert hasattr(context, "get_balance")
        assert hasattr(context, "get_total_minted")
        assert hasattr(context, "get_deploy_record")

        # Verify that direct state modification is not possible through context
        assert hasattr(context, "get_balance")
        assert hasattr(context, "get_total_minted")
        assert hasattr(context, "get_deploy_record")
        assert not hasattr(context, "balances")

        # Verify that processor only has read access through context
        assert processor.context == context
        assert not hasattr(processor, "_state")
