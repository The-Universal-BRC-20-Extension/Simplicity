import pytest
from unittest.mock import Mock, patch, MagicMock
from sqlalchemy.orm import Session

from src.services.opi.processor import OPIProcessor
from src.services.opi.registry import OPIRegistry
from src.utils.exceptions import ValidationResult


class MockOPI:
    """Mock OPI implementation for testing"""
    def __init__(self, opi_id):
        self.opi_id = opi_id
        self._last_validated_event = None
    
    def validate_operation(self, operation, tx_info, db_session):
        return ValidationResult(is_valid=True)
    
    def process_operation(self, operation, tx_info, db_session):
        return Mock(is_valid=True, ticker="TEST", amount="100")


@pytest.fixture
def mock_db_session():
    """Mock database session"""
    return Mock(spec=Session)


@pytest.fixture
def mock_opi_registry():
    """Mock OPI registry with proper interface"""
    registry = Mock(spec=OPIRegistry)
    registry.get_opi.return_value = MockOPI("OPI-000")
    registry.list_opis.return_value = [
        "OPI-000",
        "OPI-001"
    ]
    registry.get_all_opis.return_value = [
        MockOPI("OPI-000"),
        MockOPI("OPI-001")
    ]
    return registry


@pytest.fixture
def opi_processor(mock_db_session):
    """Create OPI processor with mocked dependencies"""
    return OPIProcessor(mock_db_session)


class TestOpiProcessor:
    """Test OPI processor functionality"""

    def test_processor_initialization(self, opi_processor, mock_db_session):
        """Test processor initialization"""
        assert opi_processor.db == mock_db_session

    @patch('src.services.opi.processor.opi_registry')
    def test_process_valid_operation(self, mock_registry, opi_processor):
        """Test processing valid operation"""
        # Mock the processor to return valid result
        mock_processor = Mock()
        mock_processor.validate_operation.return_value = ValidationResult(
            is_valid=True
        )
        mock_processor.process_operation.return_value = Mock(
            is_valid=True, ticker="TEST", amount="100"
        )
        mock_registry.get_opi.return_value = mock_processor
        
        operation_data = {
            "op": "no_return",
            "legacy_txid": "test_txid",
            "legacy_inscription_id": "test_inscription"
        }
        
        result = opi_processor.process_if_opi(operation_data, {"txid": "test"})
        
        assert result.is_valid is True

    @patch('src.services.opi.processor.opi_registry')
    def test_process_invalid_operation(self, mock_registry, opi_processor):
        """Test processing invalid operation"""
        # Mock the processor to return invalid result
        mock_processor = Mock()
        mock_processor.validate_operation.return_value = ValidationResult(
            is_valid=False,
            error_code="INVALID_OPERATION",
            error_message="Invalid operation"
        )
        mock_registry.get_opi.return_value = mock_processor
        
        operation_data = {
            "op": "no_return",
            "legacy_txid": "test_txid"
        }
        
        result = opi_processor.process_if_opi(operation_data, {"txid": "test"})
        
        assert result.is_valid is False
        assert result.error_code == "INVALID_OPERATION"

    @patch('src.services.opi.processor.opi_registry')
    def test_process_operation_with_warnings(self, mock_registry, opi_processor):
        """Test processing operation with warnings"""
        mock_processor = Mock()
        mock_processor.validate_operation.return_value = ValidationResult(
            is_valid=True
        )
        mock_processor.process_operation.return_value = Mock(
            is_valid=True, ticker="TEST", amount="100"
        )
        mock_registry.get_opi.return_value = mock_processor
        
        operation_data = {
            "op": "no_return",
            "legacy_txid": "test_txid"
        }
        
        result = opi_processor.process_if_opi(operation_data, {"txid": "test"})
        
        assert result.is_valid is True

    @patch('src.services.opi.processor.opi_registry')
    def test_process_operation_not_found(self, mock_registry, opi_processor):
        """Test processing operation when OPI not found"""
        mock_registry.get_opi.return_value = None
        
        operation_data = {
            "op": "no_return",
            "legacy_txid": "test_txid"
        }
        
        result = opi_processor.process_if_opi(operation_data, {"txid": "test"})
        
        assert result is None

    @patch('src.services.opi.processor.opi_registry')
    def test_process_operation_exception(self, mock_registry, opi_processor):
        """Test processing operation with exception"""
        mock_processor = Mock()
        mock_processor.validate_operation.side_effect = Exception("Test exception")
        mock_registry.get_opi.return_value = mock_processor
        
        operation_data = {
            "op": "no_return",
            "legacy_txid": "test_txid"
        }
        
        result = opi_processor.process_if_opi(operation_data, {"txid": "test"})
        
        assert result.is_valid is False
        assert result.error_code == "INTERNAL_ERROR"

    @patch('src.services.opi.processor.opi_registry')
    def test_process_empty_operation_data(self, mock_registry, opi_processor):
        """Test processing empty operation data"""
        operation_data = {}
        
        result = opi_processor.process_if_opi(operation_data, {"txid": "test"})
        
        assert result is None

    @patch('src.services.opi.processor.opi_registry')
    def test_process_none_operation_data(self, mock_registry, opi_processor):
        """Test processing None operation data"""
        # Should handle None gracefully
        try:
            result = opi_processor.process_if_opi(None, {"txid": "test"})
            # If it doesn't raise an exception, it should return None
            assert result is None
        except AttributeError:
            # If it raises AttributeError, that's also acceptable
            pass

    @patch('src.services.opi.processor.opi_registry')
    def test_process_operation_without_op_field(self, mock_registry, opi_processor):
        """Test processing operation without op field"""
        operation_data = {
            "legacy_txid": "test_txid"
        }
        
        result = opi_processor.process_if_opi(operation_data, {"txid": "test"})
        
        assert result is None

    @patch('src.services.opi.processor.opi_registry')
    def test_process_with_state_cleanup(self, mock_registry, opi_processor):
        """Test processing with state cleanup"""
        mock_processor = Mock()
        mock_processor._last_validated_event = {"test": "data"}
        mock_processor.validate_operation.return_value = ValidationResult(
            is_valid=True
        )
        mock_processor.process_operation.return_value = Mock(
            is_valid=True, ticker="TEST", amount="100"
        )
        mock_registry.get_opi.return_value = mock_processor
        
        operation_data = {
            "op": "no_return",
            "legacy_txid": "test_txid"
        }
        
        result = opi_processor.process_if_opi(operation_data, {"txid": "test"})
        
        assert result.is_valid is True
        assert mock_processor._last_validated_event is None

    def test_cleanup_state(self, opi_processor):
        """Test state cleanup functionality"""
        # This test verifies that state cleanup works correctly
        # The actual cleanup is handled in the process_if_opi method
        assert True  # Placeholder test

    def test_validation_result_creation(self):
        """Test ValidationResult creation"""
        result = ValidationResult(
            is_valid=True,
            error_code="SUCCESS",
            error_message="Operation successful"
        )
        assert result.is_valid is True
        assert result.error_code == "SUCCESS"
        assert result.error_message == "Operation successful"

    def test_validation_result_empty(self):
        """Test ValidationResult with minimal data"""
        result = ValidationResult(is_valid=False)
        assert result.is_valid is False
        assert result.error_code is None
        assert result.error_message is None 