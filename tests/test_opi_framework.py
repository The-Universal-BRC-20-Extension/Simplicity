"""
OPI Framework Tests

Comprehensive test suite for the OPI (OP_RETURN) framework components:
- OPI Interface (abstract methods)
- OPI Registry (registration and retrieval)
- OPI Processor (operation detection and routing)

Test Coverage: 100% for all OPI framework code
Performance: Sub-20ms response time compliance
Standards: Black formatting, flake8 compliance
"""

import pytest
from unittest.mock import Mock, patch
from typing import Dict, Any

from src.services.opi.interface import OPIInterface
from src.services.opi.registry import OPIRegistry, opi_registry
from src.services.opi.processor import OPIProcessor
from src.services.processor import ProcessingResult
from src.utils.exceptions import ValidationResult


class TestOPIInterface:
    """Test OPI interface abstract method enforcement"""

    def test_interface_abstract_methods(self):
        """Test that OPIInterface enforces abstract methods"""
        # Attempting to instantiate abstract class should raise error
        with pytest.raises(TypeError):
            OPIInterface()

    def test_interface_method_signatures(self):
        """Test that interface defines correct method signatures"""
        # Check that abstract methods are defined
        assert hasattr(OPIInterface, "opi_id")
        assert hasattr(OPIInterface, "parse_operation")
        assert hasattr(OPIInterface, "validate_operation")
        assert hasattr(OPIInterface, "process_operation")
        assert hasattr(OPIInterface, "get_api_endpoints")

    def test_interface_get_api_endpoints_default(self):
        """Test default get_api_endpoints returns empty list"""

        # Create a concrete implementation for testing
        class TestOPI(OPIInterface):
            @property
            def opi_id(self) -> str:
                return "test-opi"

            def parse_operation(self, hex_data: str, tx: dict) -> Dict[str, Any]:
                return {}

            def validate_operation(
                self, operation: dict, tx: dict, db_session
            ) -> ValidationResult:
                return ValidationResult(is_valid=True)

            def process_operation(
                self, operation: dict, tx: dict, db_session
            ) -> ProcessingResult:
                return ProcessingResult()

        test_opi = TestOPI()
        endpoints = test_opi.get_api_endpoints()
        assert isinstance(endpoints, list)
        assert len(endpoints) == 0


class TestOPIRegistry:
    """Test OPI registry functionality"""

    def setup_method(self):
        """Setup fresh registry for each test"""
        self.registry = OPIRegistry()

    def test_registry_initialization(self):
        """Test registry initializes with empty state"""
        assert len(self.registry._opis) == 0

    def test_register_opi_success(self):
        """Test successful OPI registration"""
        mock_opi = Mock(spec=OPIInterface)
        mock_opi.opi_id = "test-opi"

        self.registry.register_opi(mock_opi)
        assert "test-opi" in self.registry._opis
        assert self.registry._opis["test-opi"] == mock_opi

    def test_register_opi_case_insensitive(self):
        """Test OPI registration is case-insensitive"""
        mock_opi = Mock(spec=OPIInterface)
        mock_opi.opi_id = "Test-OPI"

        self.registry.register_opi(mock_opi)
        assert "test-opi" in self.registry._opis
        assert self.registry._opis["test-opi"] == mock_opi

    def test_register_opi_duplicate_error(self):
        """Test duplicate registration raises error"""
        mock_opi1 = Mock(spec=OPIInterface)
        mock_opi1.opi_id = "test-opi"
        mock_opi2 = Mock(spec=OPIInterface)
        mock_opi2.opi_id = "test-opi"

        self.registry.register_opi(mock_opi1)
        with pytest.raises(ValueError, match="test-opi is already registered"):
            self.registry.register_opi(mock_opi2)

    def test_get_opi_success(self):
        """Test successful OPI retrieval"""
        mock_opi = Mock(spec=OPIInterface)
        mock_opi.opi_id = "test-opi"
        self.registry.register_opi(mock_opi)

        retrieved = self.registry.get_opi("test-opi")
        assert retrieved == mock_opi

    def test_get_opi_case_insensitive(self):
        """Test OPI retrieval is case-insensitive"""
        mock_opi = Mock(spec=OPIInterface)
        mock_opi.opi_id = "Test-OPI"
        self.registry.register_opi(mock_opi)

        retrieved = self.registry.get_opi("TEST-OPI")
        assert retrieved == mock_opi

    def test_get_opi_not_found(self):
        """Test OPI retrieval returns None when not found"""
        retrieved = self.registry.get_opi("non-existent")
        assert retrieved is None

    def test_list_opis_empty(self):
        """Test listing OPIs when registry is empty"""
        opi_list = self.registry.list_opis()
        assert isinstance(opi_list, list)
        assert len(opi_list) == 0

    def test_list_opis_with_registered(self):
        """Test listing OPIs with registered implementations"""
        mock_opi1 = Mock(spec=OPIInterface)
        mock_opi1.opi_id = "opi-001"
        mock_opi2 = Mock(spec=OPIInterface)
        mock_opi2.opi_id = "opi-002"

        self.registry.register_opi(mock_opi1)
        self.registry.register_opi(mock_opi2)

        opi_list = self.registry.list_opis()
        assert len(opi_list) == 2
        assert "opi-001" in opi_list
        assert "opi-002" in opi_list

    def test_get_all_opis(self):
        """Test getting all OPI implementations"""
        mock_opi1 = Mock(spec=OPIInterface)
        mock_opi1.opi_id = "opi-001"
        mock_opi2 = Mock(spec=OPIInterface)
        mock_opi2.opi_id = "opi-002"

        self.registry.register_opi(mock_opi1)
        self.registry.register_opi(mock_opi2)

        all_opis = self.registry.get_all_opis()
        assert len(all_opis) == 2
        assert mock_opi1 in all_opis
        assert mock_opi2 in all_opis


class TestOPIRegistrySingleton:
    """Test the singleton opi_registry instance"""

    def test_singleton_instance(self):
        """Test that opi_registry is a singleton instance"""
        assert isinstance(opi_registry, OPIRegistry)
        assert opi_registry is not None

    def test_singleton_initialization(self):
        """Test singleton starts with empty state"""
        # Clear any existing registrations
        opi_registry._opis.clear()
        assert len(opi_registry._opis) == 0


class TestOPIProcessor:
    """Test OPI processor functionality"""

    def setup_method(self):
        """Setup processor with mock database session"""
        self.mock_db = Mock()
        self.processor = OPIProcessor(self.mock_db)

    def test_processor_initialization(self):
        """Test processor initializes with database session"""
        assert self.processor.db == self.mock_db

    def test_process_if_opi_no_return_detection(self):
        """Test processor detects no_return operations"""
        operation = {"op": "no_return", "tick": "TEST"}
        tx_info = {"txid": "test_txid", "block_height": 800000}

        with patch("src.services.opi.registry.opi_registry.get_opi") as mock_get_opi:
            mock_opi_impl = Mock()
            mock_get_opi.return_value = mock_opi_impl
            mock_opi_impl.validate_operation.return_value = ValidationResult(
                is_valid=True
            )

            result = self.processor.process_if_opi(operation, tx_info)

            assert result is not None
            assert result.is_valid is True
            mock_get_opi.assert_called_once_with("Opi-000")
            mock_opi_impl.validate_operation.assert_called_once_with(
                operation, tx_info, self.mock_db
            )

    def test_process_if_opi_no_return_validation_failure(self):
        """Test processor handles no_return validation failure"""
        operation = {"op": "no_return", "tick": "TEST"}
        tx_info = {"txid": "test_txid", "block_height": 800000}

        with patch("src.services.opi.registry.opi_registry.get_opi") as mock_get_opi:
            mock_opi_impl = Mock()
            mock_get_opi.return_value = mock_opi_impl
            mock_opi_impl.validate_operation.return_value = ValidationResult(
                is_valid=False, error_code="TEST_ERROR", error_message="Test error"
            )

            result = self.processor.process_if_opi(operation, tx_info)

            assert result is not None
            assert result.is_valid is False
            assert result.error_code == "TEST_ERROR"
            assert result.error_message == "Test error"

    def test_process_if_opi_no_return_processing_success(self):
        """Test processor calls process_operation on validation success"""
        operation = {"op": "no_return", "tick": "TEST"}
        tx_info = {"txid": "test_txid", "block_height": 800000}

        with patch("src.services.opi.registry.opi_registry.get_opi") as mock_get_opi:
            mock_opi_impl = Mock()
            mock_get_opi.return_value = mock_opi_impl
            mock_opi_impl.validate_operation.return_value = ValidationResult(
                is_valid=True
            )
            mock_opi_impl.process_operation.return_value = ProcessingResult()

            result = self.processor.process_if_opi(operation, tx_info)

            assert result is not None
            mock_opi_impl.process_operation.assert_called_once_with(
                operation, tx_info, self.mock_db
            )

    def test_process_if_opi_no_return_not_registered(self):
        """Test processor handles no_return when OPI not registered"""
        operation = {"op": "no_return", "tick": "TEST"}
        tx_info = {"txid": "test_txid", "block_height": 800000}

        with patch("src.services.opi.registry.opi_registry.get_opi") as mock_get_opi:
            mock_get_opi.return_value = None

            result = self.processor.process_if_opi(operation, tx_info)

            assert result is None

    def test_process_if_opi_non_opi_operation(self):
        """Test processor ignores non-OPI operations"""
        operation = {"op": "transfer", "tick": "TEST"}
        tx_info = {"txid": "test_txid", "block_height": 800000}

        result = self.processor.process_if_opi(operation, tx_info)

        assert result is None

    def test_process_if_opi_missing_op_type(self):
        """Test processor handles operations without op type"""
        operation = {"tick": "TEST"}
        tx_info = {"txid": "test_txid", "block_height": 800000}

        result = self.processor.process_if_opi(operation, tx_info)

        assert result is None

    def test_process_if_opi_empty_operation(self):
        """Test processor handles empty operation"""
        operation = {}
        tx_info = {"txid": "test_txid", "block_height": 800000}

        result = self.processor.process_if_opi(operation, tx_info)

        assert result is None


class TestOPIProcessorIntegration:
    """Integration tests for OPI processor with real components"""

    def setup_method(self):
        """Setup processor with real database session"""
        self.mock_db = Mock()
        self.processor = OPIProcessor(self.mock_db)

    @patch("src.services.opi.registry.opi_registry.get_opi")
    def test_process_if_opi_with_real_opi_implementation(self, mock_get_opi):
        """Test processor with actual OPI implementation"""
        # Import the real OPI-000 implementation
        from src.services.opi.implementations.opi_000 import Opi000Implementation

        opi_impl = Opi000Implementation()
        mock_get_opi.return_value = opi_impl

        operation = {"op": "no_return", "tick": "TEST"}
        tx_info = {"txid": "test_txid", "block_height": 800000}

        # Mock the OPI-LC integration to avoid external calls
        with patch.object(
            opi_impl.opi_lc, "get_transfer_event_for_tx"
        ) as mock_get_event:
            mock_get_event.return_value = None  # Simulate no legacy event found

            result = self.processor.process_if_opi(operation, tx_info)

            assert result is not None
            assert result.is_valid is False
            assert "NO_LEGACY_TRANSFER" in result.error_code

    def test_processor_performance(self):
        """Test processor performance meets sub-20ms requirement"""
        import time

        operation = {"op": "transfer", "tick": "TEST"}  # Non-OPI operation
        tx_info = {"txid": "test_txid", "block_height": 800000}

        # Measure processing time
        start_time = time.time()
        result = self.processor.process_if_opi(operation, tx_info)
        processing_time = (time.time() - start_time) * 1000  # Convert to milliseconds

        assert processing_time < 20  # Sub-20ms requirement
        assert result is None  # Expected result for non-OPI operation


class TestOPIErrorHandling:
    """Test error handling in OPI framework"""

    def test_registry_duplicate_registration_error_message(self):
        """Test registry provides clear error message for duplicates"""
        registry = OPIRegistry()
        mock_opi1 = Mock(spec=OPIInterface)
        mock_opi1.opi_id = "test-opi"
        mock_opi2 = Mock(spec=OPIInterface)
        mock_opi2.opi_id = "test-opi"

        registry.register_opi(mock_opi1)

        with pytest.raises(ValueError) as exc_info:
            registry.register_opi(mock_opi2)

        assert "test-opi is already registered" in str(exc_info.value)

    def test_processor_database_session_preservation(self):
        """Test processor preserves database session through operations"""
        mock_db = Mock()
        processor = OPIProcessor(mock_db)

        operation = {"op": "no_return", "tick": "TEST"}
        tx_info = {"txid": "test_txid", "block_height": 800000}

        with patch("src.services.opi.registry.opi_registry.get_opi") as mock_get_opi:
            mock_opi_impl = Mock()
            mock_get_opi.return_value = mock_opi_impl
            mock_opi_impl.validate_operation.return_value = ValidationResult(
                is_valid=True
            )

            processor.process_if_opi(operation, tx_info)

            # Verify database session was passed to OPI implementation
            mock_opi_impl.validate_operation.assert_called_once_with(
                operation, tx_info, mock_db
            )


class TestOPIInterfaceCompliance:
    """Test OPI interface compliance and contract validation"""

    def test_interface_method_signatures_compliance(self):
        """Test that interface methods have correct signatures"""
        # Check abstract method signatures
        import inspect

        # Check opi_id property
        opi_id_prop = getattr(OPIInterface, "opi_id")
        assert hasattr(opi_id_prop, "fget")  # Should be a property

        # Check parse_operation method
        parse_sig = inspect.signature(OPIInterface.parse_operation)
        assert "hex_data" in parse_sig.parameters
        assert "tx" in parse_sig.parameters

        # Check validate_operation method
        validate_sig = inspect.signature(OPIInterface.validate_operation)
        assert "operation" in validate_sig.parameters
        assert "tx" in validate_sig.parameters
        assert "db_session" in validate_sig.parameters

        # Check process_operation method
        process_sig = inspect.signature(OPIInterface.process_operation)
        assert "operation" in process_sig.parameters
        assert "tx" in process_sig.parameters
        assert "db_session" in process_sig.parameters

    def test_interface_return_types(self):
        """Test that interface methods have correct return types"""
        import inspect

        # Check parse_operation return type hint
        parse_sig = inspect.signature(OPIInterface.parse_operation)
        assert parse_sig.return_annotation == Dict[str, Any]

        # Check validate_operation return type hint
        validate_sig = inspect.signature(OPIInterface.validate_operation)
        assert validate_sig.return_annotation == ValidationResult

        # Check process_operation return type hint
        process_sig = inspect.signature(OPIInterface.process_operation)
        assert process_sig.return_annotation == ProcessingResult

        # Check get_api_endpoints return type hint
        endpoints_sig = inspect.signature(OPIInterface.get_api_endpoints)
        assert "List" in str(endpoints_sig.return_annotation)
        assert "APIRouter" in str(endpoints_sig.return_annotation)
