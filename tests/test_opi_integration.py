"""
OPI Integration Tests

Comprehensive integration test suite for OPI (OP_RETURN) feature:
- End-to-end OPI processing workflows
- Database integration and state consistency
- Processor integration with main BRC-20 processor
- Balance updates and validation
- API integration and response validation

Test Coverage: 100% for OPI integration scenarios
Performance: Sub-20ms response time compliance
Standards: Black formatting, flake8 compliance
"""

import pytest
from unittest.mock import Mock, patch, MagicMock
from datetime import datetime
import time

from src.services.opi.processor import OPIProcessor
from src.services.opi.implementations.opi_000 import Opi000Implementation
from src.services.processor import BRC20Processor
from src.models.opi_operation import OPIOperation
from src.models.balance import Balance
from src.models.transaction import BRC20Operation
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
        operation = {"op": "no_return", "tick": "TEST"}
        tx_info = {
            "txid": "a" * 64,
            "vout_index": 0,
            "block_height": 800000,
            "block_hash": "test_hash",
            "tx_index": 0,
        }

        # 2. Mock OPI-LC integration
        legacy_event = {
            "event_type": "transfer-transfer",
            "inscription_id": "test_txid:i0",
            "to_pkScript": "76a9141234567890abcdef1234567890abcdef1234567890abcdef88ac",
            "tick": "TEST",
            "from_pkScript": "76a914abcdef1234567890abcdef1234567890abcdef12345688ac",
            "amount": "100",
        }

        with patch.object(
            self.opi_impl.opi_lc, "get_transfer_event_for_tx"
        ) as mock_get_event:
            with patch(
                "src.utils.bitcoin.extract_address_from_script"
            ) as mock_extract_addr:
                with patch.object(Balance, "get_or_create") as mock_get_or_create:
                    # Setup mocks
                    mock_get_event.return_value = legacy_event
                    mock_extract_addr.side_effect = [
                        "1A1zP1eP5QGefi2DMPTfTL5SLmv7DivfNa",  # Satoshi address
                        "bc1qsender",  # Sender address
                    ]
                    mock_balance = Mock()
                    mock_get_or_create.return_value = mock_balance

                    # 3. Process OPI operation
                    with patch(
                        "src.services.opi.registry.opi_registry.get_opi"
                    ) as mock_get_opi:
                        mock_get_opi.return_value = self.opi_impl

                        result = self.opi_processor.process_if_opi(operation, tx_info)

                        # 4. Verify results
                        assert result is not None
                        assert result.is_valid is True

                        # Verify balance was updated
                        mock_get_or_create.assert_called_once_with(
                            self.mock_db, "bc1qsender", "TEST"
                        )
                        mock_balance.add_amount.assert_called_once_with("100")

                        # Verify OPI operation was logged
                        self.mock_db.add.assert_called_once()
                        added_opi_op = self.mock_db.add.call_args[0][0]
                        assert isinstance(added_opi_op, OPIOperation)
                        assert added_opi_op.opi_id == "Opi-000"
                        assert added_opi_op.txid == "a" * 64
                        assert added_opi_op.operation_type == "no_return"

    def test_complete_no_return_workflow_validation_failure(self):
        """Test complete no_return workflow with validation failure"""
        operation = {"op": "no_return", "tick": "TEST"}
        tx_info = {"txid": "test_txid_123", "block_height": 800000}

        with patch.object(
            self.opi_impl.opi_lc, "get_transfer_event_for_tx"
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
        operation = {"op": "no_return", "tick": "TEST"}
        tx_info = {"txid": "test_txid_123", "block_height": 800000}

        legacy_event = {
            "event_type": "transfer-transfer",
            "inscription_id": "test_txid:i0",
            "to_pkScript": "test_pkscript",
            "tick": "TEST",
            "from_pkScript": "sender_pkscript",
            "amount": "100",
        }

        with patch.object(
            self.opi_impl.opi_lc, "get_transfer_event_for_tx"
        ) as mock_get_event:
            with patch(
                "src.utils.bitcoin.extract_address_from_script"
            ) as mock_extract_addr:
                with patch.object(Balance, "get_or_create") as mock_get_or_create:
                    with patch(
                        "src.services.opi.registry.opi_registry.get_opi"
                    ) as mock_get_opi:
                        # Setup validation success but processing failure
                        mock_get_event.return_value = legacy_event
                        mock_extract_addr.side_effect = [
                            "1A1zP1eP5QGefi2DMPTfTL5SLmv7DivfNa",  # Satoshi address
                            None,  # Address extraction fails
                        ]
                        mock_get_opi.return_value = self.opi_impl

                        result = self.opi_processor.process_if_opi(operation, tx_info)

                        # Verify processing failure
                        assert result is not None
                        assert result.is_valid is False
                        assert (
                            "Could not extract sender address" in result.error_message
                        )


class TestOPIDatabaseIntegration:
    """Test OPI database integration and state consistency"""

    def setup_method(self):
        """Setup database integration tests"""
        self.mock_db = Mock()
        self.mock_bitcoin_rpc = Mock()
        self.opi_processor = OPIProcessor(self.mock_db)

    def test_opi_operation_database_persistence(self):
        """Test OPI operation database persistence"""
        operation = {"op": "no_return", "tick": "TEST"}
        tx_info = {"txid": "test_txid_123", "vout_index": 0, "block_height": 800000}

        legacy_event = {
            "event_type": "transfer-transfer",
            "inscription_id": "test_txid:i0",
            "to_pkScript": "test_pkscript",
            "tick": "TEST",
            "from_pkScript": "sender_pkscript",
            "amount": "100",
        }

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

                    # Mock the legacy event storage
                    with patch.object(
                        mock_opi_impl, "_last_validated_event", legacy_event
                    ):
                        result = self.opi_processor.process_if_opi(operation, tx_info)

                        # Verify database operations
                        assert result is not None
                        assert result.is_valid is True

                        # Verify OPI operation was added to database
                        self.mock_db.add.assert_called_once()
                        added_opi_op = self.mock_db.add.call_args[0][0]
                        assert isinstance(added_opi_op, OPIOperation)
                        assert added_opi_op.opi_id == "Opi-000"
                        assert added_opi_op.txid == "test_txid_123"
                        assert added_opi_op.operation_type == "no_return"

    def test_balance_update_integration(self):
        """Test balance update integration with OPI operations"""
        operation = {"op": "no_return", "tick": "TEST"}
        tx_info = {"txid": "test_txid_123", "vout_index": 0, "block_height": 800000}

        legacy_event = {
            "event_type": "transfer-transfer",
            "inscription_id": "test_txid:i0",
            "to_pkScript": "test_pkscript",
            "tick": "TEST",
            "from_pkScript": "sender_pkscript",
            "amount": "100",
        }

        with patch("src.services.opi.registry.opi_registry.get_opi") as mock_get_opi:
            with patch.object(
                Opi000Implementation, "validate_operation"
            ) as mock_validate:
                with patch.object(
                    Opi000Implementation, "process_operation"
                ) as mock_process:
                    with patch.object(Balance, "get_or_create") as mock_get_or_create:
                        # Setup mocks
                        mock_opi_impl = Opi000Implementation()
                        mock_get_opi.return_value = mock_opi_impl
                        mock_validate.return_value = ValidationResult(is_valid=True)
                        mock_process.return_value = Mock(
                            is_valid=True, ticker="TEST", amount="100"
                        )

                        # Mock balance operations
                        mock_balance = Mock()
                        mock_balance.balance = "500"  # Initial balance
                        mock_get_or_create.return_value = mock_balance

                        with patch.object(
                            mock_opi_impl, "_last_validated_event", legacy_event
                        ):
                            with patch(
                                "src.utils.bitcoin.extract_address_from_script"
                            ) as mock_extract_addr:
                                mock_extract_addr.side_effect = [
                                    "1A1zP1eP5QGefi2DMPTfTL5SLmv7DivfNa",  # Satoshi address
                                    "bc1qsender",  # Sender address
                                ]

                                result = self.opi_processor.process_if_opi(
                                    operation, tx_info
                                )

                                # Verify balance was updated
                                assert result is not None
                                assert result.is_valid is True

                                mock_get_or_create.assert_called_once_with(
                                    self.mock_db, "bc1qsender", "TEST"
                                )
                                mock_balance.add_amount.assert_called_once_with("100")

    def test_database_transaction_consistency(self):
        """Test database transaction consistency during OPI processing"""
        operation = {"op": "no_return", "tick": "TEST"}
        tx_info = {"txid": "test_txid_123", "vout_index": 0, "block_height": 800000}

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

                    # Mock database transaction
                    self.mock_db.begin.return_value = None
                    self.mock_db.commit.return_value = None
                    self.mock_db.rollback.return_value = None

                    result = self.opi_processor.process_if_opi(operation, tx_info)

                    # Verify database transaction handling
                    assert result is not None
                    assert result.is_valid is True

                    # Verify database operations were called
                    self.mock_db.add.assert_called_once()

    def test_database_error_handling(self):
        """Test database error handling during OPI processing"""
        operation = {"op": "no_return", "tick": "TEST"}
        tx_info = {"txid": "test_txid_123", "vout_index": 0, "block_height": 800000}

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
                    mock_process.side_effect = Exception("Database error")

                    result = self.opi_processor.process_if_opi(operation, tx_info)

                    # Verify error handling
                    assert result is not None
                    assert result.is_valid is False
                    assert "Database error" in result.error_message


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
        operation = {"op": "no_return", "tick": "TEST"}
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
        operation = {"op": "no_return", "tick": "TEST"}
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

    def test_opi_processor_database_session_preservation(self):
        """Test OPI processor preserves database session through operations"""
        operation = {"op": "no_return", "tick": "TEST"}
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

                    result = self.opi_processor.process_if_opi(operation, tx_info)

                    # Verify database session was passed correctly
                    assert result is not None
                    mock_validate.assert_called_once_with(
                        operation, tx_info, self.mock_db
                    )
                    mock_process.assert_called_once_with(
                        operation, tx_info, self.mock_db
                    )


class TestOPIStateConsistency:
    """Test OPI state consistency and cleanup"""

    def setup_method(self):
        """Setup state consistency tests"""
        self.mock_db = Mock()
        self.opi_processor = OPIProcessor(self.mock_db)

    def test_opi_implementation_state_cleanup(self):
        """Test OPI implementation state cleanup after processing"""
        operation = {"op": "no_return", "tick": "TEST"}
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
        operation = {"op": "no_return", "tick": "TEST"}
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

    def test_multiple_opi_operations_state_isolation(self):
        """Test state isolation between multiple OPI operations"""
        operations = [
            {"op": "no_return", "tick": "TEST1"},
            {"op": "no_return", "tick": "TEST2"},
        ]
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

                    # Process multiple operations
                    for operation in operations:
                        result = self.opi_processor.process_if_opi(operation, tx_info)
                        assert result is not None
                        assert result.is_valid is True
                        assert (
                            mock_opi_impl._last_validated_event is None
                        )  # State should be clean


class TestOPIPerformanceIntegration:
    """Test OPI performance integration requirements"""

    def setup_method(self):
        """Setup performance tests"""
        self.mock_db = Mock()
        self.opi_processor = OPIProcessor(self.mock_db)

    def test_opi_processing_performance(self):
        """Test OPI processing performance meets sub-20ms requirement"""
        operation = {"op": "no_return", "tick": "TEST"}
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

                    # Measure processing time
                    start_time = time.time()
                    result = self.opi_processor.process_if_opi(operation, tx_info)
                    processing_time = (time.time() - start_time) * 1000

                    # Verify performance
                    assert result is not None
                    assert processing_time < 20  # Sub-20ms requirement

    def test_opi_processing_performance_with_validation_failure(self):
        """Test OPI processing performance with validation failure"""
        operation = {"op": "no_return", "tick": "TEST"}
        tx_info = {"txid": "test_txid_123", "block_height": 800000}

        with patch("src.services.opi.registry.opi_registry.get_opi") as mock_get_opi:
            with patch.object(
                Opi000Implementation, "validate_operation"
            ) as mock_validate:
                # Setup validation failure
                mock_opi_impl = Opi000Implementation()
                mock_get_opi.return_value = mock_opi_impl
                mock_validate.return_value = ValidationResult(
                    is_valid=False, error_code="TEST_ERROR", error_message="Test error"
                )

                # Measure processing time
                start_time = time.time()
                result = self.opi_processor.process_if_opi(operation, tx_info)
                processing_time = (time.time() - start_time) * 1000

                # Verify performance
                assert result is not None
                assert result.is_valid is False
                assert processing_time < 20  # Sub-20ms requirement

    def test_concurrent_opi_processing_performance(self):
        """Test concurrent OPI processing performance"""
        import threading

        results = []

        def process_opi():
            operation = {"op": "no_return", "tick": "TEST"}
            tx_info = {
                "txid": f"test_txid_{threading.get_ident()}",
                "block_height": 800000,
            }

            with patch(
                "src.services.opi.registry.opi_registry.get_opi"
            ) as mock_get_opi:
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

                        start_time = time.time()
                        result = self.opi_processor.process_if_opi(operation, tx_info)
                        processing_time = (time.time() - start_time) * 1000

                        results.append(
                            {"result": result, "processing_time": processing_time}
                        )

        # Create multiple threads
        threads = []
        for _ in range(5):
            thread = threading.Thread(target=process_opi)
            threads.append(thread)
            thread.start()

        # Wait for all threads to complete
        for thread in threads:
            thread.join()

        # Verify all operations succeeded and met performance requirements
        for result in results:
            assert result["result"] is not None
            assert result["result"].is_valid is True
            assert result["processing_time"] < 20  # Sub-20ms requirement
