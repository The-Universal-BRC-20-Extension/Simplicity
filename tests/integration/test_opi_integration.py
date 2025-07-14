"""
OPI Integration Tests

Comprehensive integration tests for the OPI framework:
- End-to-end OPI workflows
- OPI processor integration with main BRC-20 processor
- State consistency and cleanup
- Performance and error handling

Test Coverage: Integration scenarios for OPI framework
Performance: Sub-20ms response time compliance
Standards: Black formatting, flake8 compliance
"""

import pytest
from unittest.mock import Mock, patch, MagicMock
from typing import Dict, Any

from src.services.opi.implementations.opi_000 import Opi000Implementation
from src.services.opi.processor import OPIProcessor
from src.services.processor import BRC20Processor
from src.utils.exceptions import ValidationResult, BRC20ErrorCodes


class TestOPIEndToEndWorkflow:
    """Test complete OPI end-to-end workflows"""

    def setup_method(self):
        """Setup test environment"""
        self.mock_db = Mock()
        self.opi_processor = OPIProcessor(self.mock_db)
        self.opi_impl = Opi000Implementation()

    def test_complete_no_return_workflow_success(self):
        """Test complete no_return operation workflow"""
        # 1. Setup operation and transaction data
        operation = {"op": "no_return"}  # No tick required
        tx_info = {
            "txid": "a" * 64,
            "vout_index": 0,
            "block_height": 800000,
            "block_hash": "test_hash",
            "tx_index": 0,
        }

        # 2. Mock legacy transfer service
        legacy_event = {
            "event_type": "transfer-transfer",
            "inscription_id": "test_txid:i0",
            "to_pkScript": "76a9141234567890abcdef1234567890abcdef1234567890abcdef88ac",
            "tick": "TEST",
            "from_pkScript": "76a914abcdef1234567890abcdef1234567890abcdef12345688ac",
            "amount": "100",
        }

        with patch.object(
            self.opi_impl.legacy_service, "get_transfer_event_for_tx"
        ) as mock_get_event:
            with patch(
                "src.services.opi.registry.opi_registry.get_opi"
            ) as mock_get_opi:
                with patch(
                    "src.services.opi.implementations.opi_000.extract_address_from_script"
                ) as mock_extract_addr:
                    with patch(
                        "src.models.balance.Balance.get_or_create"
                    ) as mock_get_balance:
                        with patch(
                            "src.services.opi.implementations.opi_000.OPIOperation"
                        ) as mock_opi_op:
                            # Setup mocks
                            mock_get_event.return_value = legacy_event
                            mock_get_opi.return_value = self.opi_impl
                            # Mock the correct Satoshi address for validation
                            mock_extract_addr.side_effect = lambda pkscript: {
                                "76a9141234567890abcdef1234567890abcdef1234567890abcdef88ac": "1A1zP1eP5QGefi2DMPTfTL5SLmv7DivfNa",  # Satoshi address
                                "76a914abcdef1234567890abcdef1234567890abcdef12345688ac": "1TestAddress1234567890abcdef1234567890abcdef"
                            }.get(pkscript, "unknown_address")
                            mock_balance = Mock()
                            mock_get_balance.return_value = mock_balance
                            mock_opi_op_instance = Mock()
                            mock_opi_op.return_value = mock_opi_op_instance

                            # Execute OPI processing
                            result = self.opi_processor.process_if_opi(
                                operation, tx_info
                            )

                            # Verify success
                            assert result is not None
                            assert result.is_valid is True

                            # Verify legacy service was called
                            mock_get_event.assert_called_once_with(
                                "a" * 64, 800000
                            )

                            # Verify balance was updated
                            mock_get_balance.assert_called_once_with(
                                self.mock_db,
                                "1TestAddress1234567890abcdef1234567890abcdef",
                                "TEST",
                            )
                            mock_balance.add_amount.assert_called_once_with("100")

                            # Verify OPI operation was created
                            mock_opi_op.assert_called_once()
                            call_args = mock_opi_op.call_args[1]
                            assert call_args["opi_id"] == "OPI-000"
                            assert call_args["txid"] == "a" * 64
                            assert call_args["block_height"] == 800000
                            assert call_args["operation_type"] == "no_return"

                            # Verify minimal data storage
                            operation_data = call_args["operation_data"]
                            assert "legacy_txid" in operation_data
                            assert "legacy_inscription_id" in operation_data
                            assert "ticker" in operation_data
                            assert "amount" in operation_data
                            assert "sender_address" in operation_data
                            assert "satoshi_address" not in operation_data
                            assert "witness_inscription_data" not in operation_data
                            assert "opi_lc_validation" not in operation_data

                            # Verify database session was used
                            self.mock_db.add.assert_called_once_with(
                                mock_opi_op_instance
                            )

    def test_complete_no_return_workflow_validation_failure(self):
        """Test complete no_return workflow with validation failure"""
        operation = {"op": "no_return"}  # No tick required
        tx_info = {"txid": "test_txid_123", "block_height": 800000}

        with patch.object(
            self.opi_impl.legacy_service, "get_transfer_event_for_tx"
        ) as mock_get_event:
            with patch(
                "src.services.opi.registry.opi_registry.get_opi"
            ) as mock_get_opi:
                # Setup validation failure
                mock_get_event.return_value = None  # No legacy event found
                mock_get_opi.return_value = self.opi_impl

                result = self.opi_processor.process_if_opi(operation, tx_info)

                # Verify validation failure
                assert result is not None
                assert result.is_valid is False
                assert result.error_code == BRC20ErrorCodes.NO_LEGACY_TRANSFER

                # Verify no database operations occurred
                self.mock_db.add.assert_not_called()

    def test_complete_no_return_workflow_processing_failure(self):
        """Test complete no_return workflow with processing failure"""
        operation = {"op": "no_return"}  # No tick required
        tx_info = {"txid": "test_txid_123", "block_height": 800000}

        legacy_event = {
            "event_type": "transfer-transfer",
            "inscription_id": "test_txid:i0",
            "to_pkScript": "76a9141234567890abcdef1234567890abcdef1234567890abcdef88ac",
            "tick": "TEST",
            "from_pkScript": "76a914abcdef1234567890abcdef1234567890abcdef12345688ac",
            "amount": "100",
        }

        with patch.object(
            self.opi_impl.legacy_service, "get_transfer_event_for_tx"
        ) as mock_get_event:
            with patch(
                "src.services.opi.registry.opi_registry.get_opi"
            ) as mock_get_opi:
                with patch(
                    "src.services.opi.implementations.opi_000.extract_address_from_script"
                ) as mock_extract_addr:
                    # Setup processing failure
                    mock_get_event.return_value = legacy_event
                    mock_get_opi.return_value = self.opi_impl
                    mock_extract_addr.side_effect = Exception(
                        "Address extraction failed"
                    )

                    result = self.opi_processor.process_if_opi(operation, tx_info)

                    # Verify processing failure
                    assert result is not None
                    assert result.is_valid is False
                    assert "Address extraction failed" in result.error_message

                    # Verify no database operations occurred
                    self.mock_db.add.assert_not_called()

    def test_complete_no_return_workflow_state_cleanup(self):
        """Test complete no_return workflow properly cleans up state"""
        operation = {"op": "no_return"}  # No tick required
        tx_info = {"txid": "test_txid_123", "block_height": 800000}

        legacy_event = {
            "event_type": "transfer-transfer",
            "inscription_id": "test_txid:i0",
            "to_pkScript": "76a9141234567890abcdef1234567890abcdef1234567890abcdef88ac",
            "tick": "TEST",
            "from_pkScript": "76a914abcdef1234567890abcdef1234567890abcdef12345688ac",
            "amount": "100",
        }

        with patch.object(
            self.opi_impl.legacy_service, "get_transfer_event_for_tx"
        ) as mock_get_event:
            with patch(
                "src.services.opi.registry.opi_registry.get_opi"
            ) as mock_get_opi:
                with patch(
                    "src.services.opi.implementations.opi_000.extract_address_from_script"
                ) as mock_extract_addr:
                    with patch(
                        "src.models.balance.Balance.get_or_create"
                    ) as mock_get_balance:
                        with patch(
                            "src.services.opi.implementations.opi_000.OPIOperation"
                        ) as mock_opi_op:
                            # Setup mocks
                            mock_get_event.return_value = legacy_event
                            mock_get_opi.return_value = self.opi_impl
                            # Mock the correct Satoshi address for validation
                            mock_extract_addr.side_effect = lambda pkscript: {
                                "76a9141234567890abcdef1234567890abcdef1234567890abcdef88ac": "1A1zP1eP5QGefi2DMPTfTL5SLmv7DivfNa",  # Satoshi address
                                "76a914abcdef1234567890abcdef1234567890abcdef12345688ac": "1TestAddress1234567890abcdef1234567890abcdef"
                            }.get(pkscript, "unknown_address")
                            mock_balance = Mock()
                            mock_get_balance.return_value = mock_balance
                            mock_opi_op_instance = Mock()
                            mock_opi_op.return_value = mock_opi_op_instance

                            # Set initial state
                            self.opi_impl._last_validated_event = {"previous": "event"}

                            # Execute OPI processing
                            result = self.opi_processor.process_if_opi(
                                operation, tx_info
                            )

                            # Verify success
                            assert result is not None
                            assert result.is_valid is True

                            # Verify state cleanup
                            assert self.opi_impl._last_validated_event is None

    def test_complete_no_return_workflow_performance(self):
        """Test complete no_return workflow performance"""
        import time

        operation = {"op": "no_return"}  # No tick required
        tx_info = {"txid": "test_txid_123", "block_height": 800000}

        legacy_event = {
            "event_type": "transfer-transfer",
            "inscription_id": "test_txid:i0",
            "to_pkScript": "76a9141234567890abcdef1234567890abcdef1234567890abcdef88ac",
            "tick": "TEST",
            "from_pkScript": "76a914abcdef1234567890abcdef1234567890abcdef12345688ac",
            "amount": "100",
        }

        with patch.object(
            self.opi_impl.legacy_service, "get_transfer_event_for_tx"
        ) as mock_get_event:
            with patch(
                "src.services.opi.registry.opi_registry.get_opi"
            ) as mock_get_opi:
                with patch(
                    "src.services.opi.implementations.opi_000.extract_address_from_script"
                ) as mock_extract_addr:
                    with patch(
                        "src.models.balance.Balance.get_or_create"
                    ) as mock_get_balance:
                        with patch(
                            "src.services.opi.implementations.opi_000.OPIOperation"
                        ) as mock_opi_op:
                            # Setup mocks
                            mock_get_event.return_value = legacy_event
                            mock_get_opi.return_value = self.opi_impl
                            # Mock the correct Satoshi address for validation
                            mock_extract_addr.side_effect = lambda pkscript: {
                                "76a9141234567890abcdef1234567890abcdef1234567890abcdef88ac": "1A1zP1eP5QGefi2DMPTfTL5SLmv7DivfNa",  # Satoshi address
                                "76a914abcdef1234567890abcdef1234567890abcdef12345688ac": "1TestAddress1234567890abcdef1234567890abcdef"
                            }.get(pkscript, "unknown_address")
                            mock_balance = Mock()
                            mock_get_balance.return_value = mock_balance
                            mock_opi_op_instance = Mock()
                            mock_opi_op.return_value = mock_opi_op_instance

                            # Measure performance
                            start_time = time.time()
                            result = self.opi_processor.process_if_opi(
                                operation, tx_info
                            )
                            processing_time = (time.time() - start_time) * 1000

                            # Verify performance requirement
                            assert processing_time < 20  # Sub-20ms requirement
                            assert result is not None
                            assert result.is_valid is True


class TestOPIProcessorIntegration:
    """Test OPI processor integration with main BRC-20 processor"""

    def setup_method(self):
        """Setup processor integration tests"""
        self.mock_db = Mock()
        self.mock_bitcoin_rpc = Mock()
        self.opi_processor = OPIProcessor(self.mock_db)
        self.brc20_processor = BRC20Processor(self.mock_db, self.mock_bitcoin_rpc)

    def test_opi_processor_integration_with_main_processor(self):
        """Test OPI processor integration with main BRC-20 processor"""
        # Mock the main processor to call OPI processor
        operation = {"op": "no_return"}  # No tick required
        tx_info = {"txid": "test_txid_123", "block_height": 800000}

        with patch("src.services.opi.registry.opi_registry.get_opi") as mock_get_opi:
            with patch.object(
                Opi000Implementation, "validate_operation"
            ) as mock_validate:
                with patch.object(
                    Opi000Implementation, "process_operation"
                ) as mock_process:
                    # Setup mocks
                    mock_opi_impl = Opi000Implementation()
                    mock_get_opi.return_value = mock_opi_impl
                    mock_validate.return_value = ValidationResult(is_valid=True)
                    mock_process.return_value = Mock(
                        is_valid=True, ticker="TEST", amount="100"
                    )

                    # Test OPI processing
                    result = self.opi_processor.process_if_opi(operation, tx_info)

                    # Verify OPI processing was called
                    assert result is not None
                    assert result.is_valid is True
                    mock_validate.assert_called_once_with(
                        operation, tx_info, self.mock_db
                    )
                    mock_process.assert_called_once_with(
                        operation, tx_info, self.mock_db
                    )

    def test_opi_processor_ignores_non_opi_operations(self):
        """Test OPI processor ignores non-OPI operations"""
        # Test with regular BRC-20 operations
        operations = [
            {"op": "deploy", "tick": "TEST"},
            {"op": "mint", "tick": "TEST", "amt": "100"},
            {"op": "transfer", "tick": "TEST", "amt": "50"},
        ]

        tx_info = {"txid": "test_txid_123", "block_height": 800000}

        for operation in operations:
            result = self.opi_processor.process_if_opi(operation, tx_info)
            assert result is None  # Should be ignored

    def test_opi_processor_validation_result_propagation(self):
        """Test OPI processor validation result propagation"""
        operation = {"op": "no_return"}  # No tick required
        tx_info = {"txid": "test_txid_123", "block_height": 800000}

        with patch("src.services.opi.registry.opi_registry.get_opi") as mock_get_opi:
            with patch.object(
                Opi000Implementation, "validate_operation"
            ) as mock_validate:
                # Setup validation failure
                mock_opi_impl = Opi000Implementation()
                mock_get_opi.return_value = mock_opi_impl
                mock_validate.return_value = ValidationResult(
                    is_valid=False,
                    error_code="TEST_ERROR",
                    error_message="Test validation error",
                )

                result = self.opi_processor.process_if_opi(operation, tx_info)

                # Verify validation result propagation
                assert result is not None
                assert result.is_valid is False
                assert result.error_code == "TEST_ERROR"
                assert result.error_message == "Test validation error"

    def test_opi_processor_handles_unregistered_opi(self):
        """Test OPI processor handles unregistered OPI gracefully"""
        operation = {"op": "no_return"}  # No tick required
        tx_info = {"txid": "test_txid_123", "block_height": 800000}

        with patch("src.services.opi.registry.opi_registry.get_opi") as mock_get_opi:
            # Setup unregistered OPI
            mock_get_opi.return_value = None

            result = self.opi_processor.process_if_opi(operation, tx_info)

            # Verify graceful handling
            assert result is None

    def test_opi_processor_handles_missing_op_type(self):
        """Test OPI processor handles operations without op type"""
        operation = {"tick": "TEST"}  # Missing op type
        tx_info = {"txid": "test_txid_123", "block_height": 800000}

        result = self.opi_processor.process_if_opi(operation, tx_info)

        # Verify graceful handling
        assert result is None

    def test_opi_processor_handles_empty_operation(self):
        """Test OPI processor handles empty operations"""
        operation = {}  # Empty operation
        tx_info = {"txid": "test_txid_123", "block_height": 800000}

        result = self.opi_processor.process_if_opi(operation, tx_info)

        # Verify graceful handling
        assert result is None


class TestOPIStateConsistency:
    """Test OPI state consistency and cleanup"""

    def setup_method(self):
        """Setup state consistency tests"""
        self.mock_db = Mock()
        self.opi_processor = OPIProcessor(self.mock_db)

    def test_opi_implementation_state_cleanup(self):
        """Test OPI implementation state cleanup after processing"""
        operation = {"op": "no_return"}  # No tick required
        tx_info = {"txid": "test_txid_123", "block_height": 800000}

        with patch("src.services.opi.registry.opi_registry.get_opi") as mock_get_opi:
            with patch.object(
                Opi000Implementation, "validate_operation"
            ) as mock_validate:
                with patch.object(
                    Opi000Implementation, "process_operation"
                ) as mock_process:
                    # Setup mocks
                    mock_opi_impl = Opi000Implementation()
                    mock_get_opi.return_value = mock_opi_impl
                    mock_validate.return_value = ValidationResult(is_valid=True)
                    mock_process.return_value = Mock(is_valid=True)

                    # Set initial state
                    mock_opi_impl._last_validated_event = {"test": "event"}

                    result = self.opi_processor.process_if_opi(operation, tx_info)

                    # Verify state cleanup
                    assert result is not None
                    assert mock_opi_impl._last_validated_event is None

    def test_opi_implementation_state_cleanup_on_error(self):
        """Test OPI implementation state cleanup on processing error"""
        operation = {"op": "no_return"}  # No tick required
        tx_info = {"txid": "test_txid_123", "block_height": 800000}

        with patch("src.services.opi.registry.opi_registry.get_opi") as mock_get_opi:
            with patch.object(
                Opi000Implementation, "validate_operation"
            ) as mock_validate:
                with patch.object(
                    Opi000Implementation, "process_operation"
                ) as mock_process:
                    # Setup mocks
                    mock_opi_impl = Opi000Implementation()
                    mock_get_opi.return_value = mock_opi_impl
                    mock_validate.return_value = ValidationResult(is_valid=True)
                    mock_process.side_effect = Exception("Processing error")

                    # Set initial state
                    mock_opi_impl._last_validated_event = {"test": "event"}

                    result = self.opi_processor.process_if_opi(operation, tx_info)

                    # Verify state cleanup even on error
                    assert result is not None
                    assert result.is_valid is False
                    assert mock_opi_impl._last_validated_event is None

    def test_opi_implementation_state_cleanup_on_validation_error(self):
        """Test OPI implementation state cleanup on validation error"""
        operation = {"op": "no_return"}  # No tick required
        tx_info = {"txid": "test_txid_123", "block_height": 800000}

        with patch("src.services.opi.registry.opi_registry.get_opi") as mock_get_opi:
            with patch.object(
                Opi000Implementation, "validate_operation"
            ) as mock_validate:
                # Setup mocks
                mock_opi_impl = Opi000Implementation()
                mock_get_opi.return_value = mock_opi_impl
                mock_validate.return_value = ValidationResult(
                    is_valid=False,
                    error_code="TEST_ERROR",
                    error_message="Test validation error",
                )

                # Set initial state
                mock_opi_impl._last_validated_event = {"test": "event"}

                result = self.opi_processor.process_if_opi(operation, tx_info)

                # Verify state cleanup
                assert result is not None
                assert result.is_valid is False
                assert mock_opi_impl._last_validated_event is None
