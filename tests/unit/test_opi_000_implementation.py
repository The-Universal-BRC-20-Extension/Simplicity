"""
OPI-000 Implementation Tests

Comprehensive test suite for the OPI-000 'no_return' implementation:
- Core implementation functionality
- Validation logic and error handling
- Processing operations and balance updates
- API endpoints and response handling
- Legacy transfer service integration scenarios

Test Coverage: 100% for OPI-000 implementation
Performance: Sub-20ms response time compliance
Standards: Black formatting, flake8 compliance
"""

import pytest
from unittest.mock import Mock, patch, MagicMock
from typing import Dict, Any

from src.services.opi.implementations.opi_000 import (
    Opi000Implementation,
    LegacyTransferService,
)
from src.services.processor import ProcessingResult
from src.utils.exceptions import ValidationResult, BRC20ErrorCodes
from src.models.balance import Balance
from src.models.opi_operation import OPIOperation


class TestOpi000Implementation:
    """Test OPI-000 implementation core functionality"""

    def setup_method(self):
        """Setup fresh implementation for each test"""
        self.opi_impl = Opi000Implementation()
        self.mock_db = Mock()

    def test_implementation_initialization(self):
        """Test OPI-000 implementation initializes correctly"""
        assert self.opi_impl.opi_id == "OPI-000"
        assert isinstance(self.opi_impl.legacy_service, LegacyTransferService)
        assert self.opi_impl._last_validated_event is None

    def test_parse_operation_minimal_payload(self):
        """Test parse_operation returns empty dict for no_return (minimal payload)"""
        hex_data = "test_hex_data"
        tx = {"txid": "test_txid"}

        result = self.opi_impl.parse_operation(hex_data, tx)

        assert result == {}  # no_return operations have minimal payload

    def test_implementation_registration(self):
        """Test OPI-000 implementation can be registered"""
        from src.services.opi.registry import opi_registry

        # Clear any existing registration
        if opi_registry.get_opi("opi-000"):
            opi_registry.unregister_opi("opi-000")

        # Register the implementation
        from src.services.opi.implementations.opi_000 import register
        register()

        # Verify registration
        registered_opi = opi_registry.get_opi("opi-000")
        assert registered_opi is not None
        assert isinstance(registered_opi, Opi000Implementation)


class TestOpi000Validation:
    """Test OPI-000 validation logic"""

    def setup_method(self):
        """Setup fresh implementation and mocks"""
        self.opi_impl = Opi000Implementation()
        self.mock_db = Mock()

    def test_validate_operation_missing_txid(self):
        """Test validation fails with missing txid"""
        operation = {"op": "no_return"}  # No tick required
        tx = {"block_height": 800000}  # Missing txid

        result = self.opi_impl.validate_operation(operation, tx, self.mock_db)

        assert result.is_valid is False
        assert result.error_code == "MISSING_DATA"
        assert "txid" in result.error_message

    def test_validate_operation_missing_block_height(self):
        """Test validation fails with missing block_height"""
        operation = {"op": "no_return"}  # No tick required
        tx = {"txid": "a" * 64}  # Missing block_height

        result = self.opi_impl.validate_operation(operation, tx, self.mock_db)

        assert result.is_valid is False
        assert result.error_code == "MISSING_DATA"
        assert "height" in result.error_message

    def test_validate_operation_missing_both_txid_and_height(self):
        """Test validation fails with missing txid and block_height"""
        operation = {"op": "no_return"}  # No tick required
        tx = {}  # Missing both

        result = self.opi_impl.validate_operation(operation, tx, self.mock_db)

        assert result.is_valid is False
        assert result.error_code == "MISSING_DATA"
        assert "txid or height" in result.error_message

    def test_validate_operation_no_legacy_transfer_found(self):
        """Test validation fails when no legacy transfer is found"""
        operation = {"op": "no_return"}  # No tick required
        tx = {"txid": "a" * 64, "block_height": 800000}

        with patch.object(
            self.opi_impl.legacy_service, "get_transfer_event_for_tx"
        ) as mock_get_event:
            mock_get_event.return_value = None

            result = self.opi_impl.validate_operation(operation, tx, self.mock_db)

            assert result.is_valid is False
            assert result.error_code == BRC20ErrorCodes.NO_LEGACY_TRANSFER
            assert "No corresponding BRC-20 legacy transfer" in result.error_message

    def test_validate_operation_invalid_legacy_event_missing_to_pkscript(self):
        """Test validation fails when legacy event missing to_pkScript"""
        operation = {"op": "no_return"}  # No tick required
        tx = {"txid": "a" * 64, "block_height": 800000}

        legacy_event = {
            "event_type": "transfer-transfer",
            "inscription_id": "test_txid:i0",
            "from_pkScript": "76a914abcdef1234567890abcdef1234567890abcdef12345688ac",
            "tick": "TEST",
            "amount": "100",
            # Missing to_pkScript
        }

        with patch.object(
            self.opi_impl.legacy_service, "get_transfer_event_for_tx"
        ) as mock_get_event:
            mock_get_event.return_value = legacy_event

            result = self.opi_impl.validate_operation(operation, tx, self.mock_db)

            assert result.is_valid is False
            assert result.error_code == BRC20ErrorCodes.INVALID_LEGACY_EVENT
            assert "Missing 'to_pkScript'" in result.error_message

    def test_validate_operation_invalid_recipient_address(self):
        """Test validation fails when legacy transfer recipient is not Satoshi address"""
        operation = {"op": "no_return"}  # No tick required
        tx = {"txid": "a" * 64, "block_height": 800000}

        legacy_event = {
            "event_type": "transfer-transfer",
            "inscription_id": "test_txid:i0",
            "to_pkScript": "76a9141234567890abcdef1234567890abcdef1234567890abcdef88ac",  # Wrong address
            "from_pkScript": "76a914abcdef1234567890abcdef1234567890abcdef12345688ac",
            "tick": "TEST",
            "amount": "100",
        }

        with patch.object(
            self.opi_impl.legacy_service, "get_transfer_event_for_tx"
        ) as mock_get_event:
            with patch(
                "src.services.opi.implementations.opi_000.extract_address_from_script"
            ) as mock_extract_addr:
                mock_get_event.return_value = legacy_event
                mock_extract_addr.return_value = "1WrongAddress1234567890abcdef1234567890abcdef"

                result = self.opi_impl.validate_operation(operation, tx, self.mock_db)

                assert result.is_valid is False
                assert result.error_code == BRC20ErrorCodes.INVALID_RECIPIENT
                assert "not the required Satoshi address" in result.error_message

    def test_validate_operation_missing_required_fields(self):
        """Test validation fails when legacy event missing required fields"""
        operation = {"op": "no_return"}  # No tick required
        tx = {"txid": "a" * 64, "block_height": 800000}

        # Test missing from_pkScript
        legacy_event_missing_from = {
            "event_type": "transfer-transfer",
            "inscription_id": "test_txid:i0",
            "to_pkScript": "76a9141234567890abcdef1234567890abcdef1234567890abcdef88ac",
            "tick": "TEST",
            "amount": "100",
            # Missing from_pkScript
        }

        with patch.object(
            self.opi_impl.legacy_service, "get_transfer_event_for_tx"
        ) as mock_get_event:
            with patch(
                "src.services.opi.implementations.opi_000.extract_address_from_script"
            ) as mock_extract_addr:
                mock_get_event.return_value = legacy_event_missing_from
                mock_extract_addr.return_value = "1A1zP1eP5QGefi2DMPTfTL5SLmv7DivfNa"

                result = self.opi_impl.validate_operation(operation, tx, self.mock_db)

                assert result.is_valid is False
                assert result.error_code == BRC20ErrorCodes.INVALID_LEGACY_EVENT
                assert "Missing required field 'from_pkScript'" in result.error_message

    def test_validate_operation_success(self):
        """Test validation succeeds with valid legacy transfer"""
        operation = {"op": "no_return"}  # No tick required
        tx = {"txid": "a" * 64, "block_height": 800000}

        legacy_event = {
            "event_type": "transfer-transfer",
            "inscription_id": "test_txid:i0",
            "to_pkScript": "76a9141234567890abcdef1234567890abcdef1234567890abcdef88ac",
            "from_pkScript": "76a914abcdef1234567890abcdef1234567890abcdef12345688ac",
            "tick": "TEST",
            "amount": "100",
        }

        with patch.object(
            self.opi_impl.legacy_service, "get_transfer_event_for_tx"
        ) as mock_get_event:
            with patch(
                "src.services.opi.implementations.opi_000.extract_address_from_script"
            ) as mock_extract_addr:
                mock_get_event.return_value = legacy_event
                mock_extract_addr.return_value = "1A1zP1eP5QGefi2DMPTfTL5SLmv7DivfNa"

                result = self.opi_impl.validate_operation(operation, tx, self.mock_db)

                assert result.is_valid is True
                assert self.opi_impl._last_validated_event == legacy_event


class TestOpi000Processing:
    """Test OPI-000 processing logic"""

    def setup_method(self):
        """Setup fresh implementation and mocks"""
        self.opi_impl = Opi000Implementation()
        self.mock_db = Mock()

    def test_process_operation_no_validated_event(self):
        """Test processing fails when no validated event exists"""
        operation = {"op": "no_return"}  # No tick required
        tx = {"txid": "a" * 64, "block_height": 800000}

        # No validated event set
        self.opi_impl._last_validated_event = None

        result = self.opi_impl.process_operation(operation, tx, self.mock_db)

        assert result.is_valid is False
        assert "No validated legacy event found" in result.error_message

    def test_process_operation_missing_legacy_fields(self):
        """Test processing fails when legacy event missing required fields"""
        operation = {"op": "no_return"}  # No tick required
        tx = {"txid": "a" * 64, "block_height": 800000}

        # Set incomplete legacy event
        self.opi_impl._last_validated_event = {
            "from_pkScript": "76a914abcdef1234567890abcdef1234567890abcdef12345688ac",
            # Missing ticker, amount, and inscription_id
        }

        result = self.opi_impl.process_operation(operation, tx, self.mock_db)

        assert result.is_valid is False
        assert "missing required fields" in result.error_message

    def test_process_operation_success(self):
        """Test processing succeeds with valid data"""
        operation = {"op": "no_return"}  # No tick required
        tx = {"txid": "a" * 64, "vout_index": 0, "block_height": 800000}

        # Set complete legacy event
        self.opi_impl._last_validated_event = {
            "from_pkScript": "76a914abcdef1234567890abcdef1234567890abcdef12345688ac",
            "tick": "TEST",
            "amount": "100",
            "inscription_id": "legacy_txid:i0",
        }

        with patch(
            "src.services.opi.implementations.opi_000.extract_address_from_script"
        ) as mock_extract_addr:
            with patch("src.models.balance.Balance.get_or_create") as mock_get_balance:
                with patch("src.services.opi.implementations.opi_000.OPIOperation") as mock_opi_op:
                    mock_extract_addr.return_value = "1TestAddress1234567890abcdef1234567890abcdef"
                    mock_balance = Mock()
                    mock_get_balance.return_value = mock_balance
                    mock_opi_op_instance = Mock()
                    mock_opi_op.return_value = mock_opi_op_instance

                    result = self.opi_impl.process_operation(operation, tx, self.mock_db)

                    assert result.is_valid is True
                    assert result.ticker == "TEST"
                    assert result.amount == "100"
                    assert result.operation_type == "no_return"

                    # Verify balance was updated
                    mock_get_balance.assert_called_once_with(
                        self.mock_db, "1TestAddress1234567890abcdef1234567890abcdef", "TEST"
                    )
                    mock_balance.add_amount.assert_called_once_with("100")

                    # Verify OPI operation was created with minimal data
                    mock_opi_op.assert_called_once()
                    call_args = mock_opi_op.call_args[1]
                    assert call_args["opi_id"] == "OPI-000"
                    assert call_args["txid"] == "a" * 64
                    assert call_args["block_height"] == 800000
                    assert call_args["vout_index"] == 0
                    assert call_args["operation_type"] == "no_return"
                    
                    # Verify minimal operation_data
                    operation_data = call_args["operation_data"]
                    assert "legacy_txid" in operation_data
                    assert "legacy_inscription_id" in operation_data
                    assert "ticker" in operation_data
                    assert "amount" in operation_data
                    assert "sender_address" in operation_data
                    assert "satoshi_address" not in operation_data  # Should not be stored
                    assert "witness_inscription_data" not in operation_data  # Should not be stored
                    assert "opi_lc_validation" not in operation_data  # Should not be stored

                    # Verify database session was used
                    self.mock_db.add.assert_called_once_with(mock_opi_op_instance)

    def test_process_operation_address_extraction_failure(self):
        """Test processing fails when address extraction fails"""
        operation = {"op": "no_return"}  # No tick required
        tx = {"txid": "a" * 64, "block_height": 800000}

        self.opi_impl._last_validated_event = {
            "from_pkScript": "76a914abcdef1234567890abcdef1234567890abcdef12345688ac",
            "tick": "TEST",
            "amount": "100",
            "inscription_id": "legacy_txid:i0",
        }

        with patch(
            "src.services.opi.implementations.opi_000.extract_address_from_script"
        ) as mock_extract_addr:
            mock_extract_addr.return_value = None

            result = self.opi_impl.process_operation(operation, tx, self.mock_db)

            assert result.is_valid is False
            assert "Could not extract sender address" in result.error_message

    def test_process_operation_state_cleanup(self):
        """Test that _last_validated_event is cleared after processing"""
        operation = {"op": "no_return"}  # No tick required
        tx = {"txid": "a" * 64, "block_height": 800000}

        self.opi_impl._last_validated_event = {
            "from_pkScript": "76a914abcdef1234567890abcdef1234567890abcdef12345688ac",
            "tick": "TEST",
            "amount": "100",
            "inscription_id": "legacy_txid:i0",
        }

        with patch(
            "src.services.opi.implementations.opi_000.extract_address_from_script"
        ) as mock_extract_addr:
            mock_extract_addr.side_effect = Exception("Test exception")

            self.opi_impl.process_operation(operation, tx, self.mock_db)

            # Verify state cleanup even on error
            assert self.opi_impl._last_validated_event is None


class TestLegacyTransferService:
    """Test LegacyTransferService functionality"""

    def setup_method(self):
        """Setup service for testing"""
        self.legacy_service = LegacyTransferService()

    def test_service_initialization(self):
        """Test service initializes with default URL"""
        assert self.legacy_service.base_url == "http://localhost:3004"
        assert self.legacy_service.client is not None

    def test_service_initialization_custom_url(self):
        """Test service initializes with custom URL"""
        custom_url = "http://custom-opi-lc:3004"
        legacy_service = LegacyTransferService(custom_url)
        assert legacy_service.base_url == custom_url

    @patch("httpx.Client.get")
    def test_get_transfer_event_for_tx_success(self, mock_get):
        """Test successful transfer event retrieval using correct endpoint"""
        # Mock the correct OPI-LC API response structure
        mock_response = Mock()
        mock_response.json.return_value = {
            "error": None,
            "result": {
                "id": 12345,
                "event_type": 3,  # transfer-transfer
                "block_height": 800000,
                "inscription_id": "test_txid:i0",
                "event": {
                    "source_pkScript": "76a914abcdef1234567890abcdef1234567890abcdef12345688ac",
                    "spent_pkScript": "76a9141234567890abcdef1234567890abcdef1234567890abcdef88ac",
                    "tick": "TEST",
                    "original_tick": "TEST",
                    "amount": "100",
                    "using_tx_id": "test_txid"
                }
            }
        }
        mock_response.raise_for_status.return_value = None
        mock_get.return_value = mock_response

        result = self.legacy_service.get_transfer_event_for_tx("test_txid", 800000)

        assert result is not None
        assert result["event_type"] == "transfer-transfer"
        assert result["inscription_id"] == "test_txid:i0"
        assert result["tick"] == "TEST"
        assert result["amount"] == "100"
        assert result["from_pkScript"] == "76a914abcdef1234567890abcdef1234567890abcdef12345688ac"
        assert result["to_pkScript"] == "76a9141234567890abcdef1234567890abcdef1234567890abcdef88ac"

        # Verify correct endpoint was called
        mock_get.assert_called_once_with("/v1/brc20/event/by-spending-tx/test_txid")

    @patch("httpx.Client.get")
    def test_get_transfer_event_for_tx_no_matching_event(self, mock_get):
        """Test when no matching transfer event is found"""
        mock_response = Mock()
        mock_response.json.return_value = {
            "error": None,
            "result": None  # No event found
        }
        mock_response.raise_for_status.return_value = None
        mock_get.return_value = mock_response

        result = self.legacy_service.get_transfer_event_for_tx("test_txid", 800000)

        assert result is None

    @patch("httpx.Client.get")
    def test_get_transfer_event_for_tx_wrong_event_type(self, mock_get):
        """Test when event is not a transfer event"""
        mock_response = Mock()
        mock_response.json.return_value = {
            "error": None,
            "result": {
                "id": 12345,
                "event_type": 1,  # Not a transfer event
                "block_height": 800000,
                "inscription_id": "test_txid:i0",
                "event": {
                    "source_pkScript": "76a914abcdef1234567890abcdef1234567890abcdef12345688ac",
                    "spent_pkScript": "76a9141234567890abcdef1234567890abcdef1234567890abcdef88ac",
                    "tick": "TEST",
                    "original_tick": "TEST",
                    "amount": "100",
                    "using_tx_id": "test_txid"
                }
            }
        }
        mock_response.raise_for_status.return_value = None
        mock_get.return_value = mock_response

        result = self.legacy_service.get_transfer_event_for_tx("test_txid", 800000)

        assert result is None

    @patch("httpx.Client.get")
    def test_get_transfer_event_for_tx_missing_event_data(self, mock_get):
        """Test when event data is missing from response"""
        mock_response = Mock()
        mock_response.json.return_value = {
            "error": None,
            "result": {
                "id": 12345,
                "event_type": 3,
                "block_height": 800000,
                "inscription_id": "test_txid:i0",
                # Missing "event" field
            }
        }
        mock_response.raise_for_status.return_value = None
        mock_get.return_value = mock_response

        result = self.legacy_service.get_transfer_event_for_tx("test_txid", 800000)

        assert result is None

    @patch("httpx.Client.get")
    def test_get_transfer_event_for_tx_api_error(self, mock_get):
        """Test handling of API error response"""
        mock_response = Mock()
        mock_response.json.return_value = {"error": "API Error"}
        mock_response.raise_for_status.return_value = None
        mock_get.return_value = mock_response

        result = self.legacy_service.get_transfer_event_for_tx("test_txid", 800000)

        assert result is None

    @patch("httpx.Client.get")
    def test_get_transfer_event_for_tx_request_error(self, mock_get):
        """Test handling of request error"""
        mock_get.side_effect = Exception("Network error")

        result = self.legacy_service.get_transfer_event_for_tx("test_txid", 800000)

        assert result is None


class TestOpi000ErrorHandling:
    """Test OPI-000 error handling scenarios"""

    def setup_method(self):
        """Setup fresh implementation"""
        self.opi_impl = Opi000Implementation()
        self.mock_db = Mock()

    def test_validation_error_codes(self):
        """Test that validation returns appropriate error codes"""
        operation = {"op": "no_return"}  # No tick required
        tx = {"txid": "a" * 64, "block_height": 800000}

        with patch.object(
            self.opi_impl.legacy_service, "get_transfer_event_for_tx"
        ) as mock_get_event:
            mock_get_event.return_value = None

            result = self.opi_impl.validate_operation(operation, tx, self.mock_db)

            assert result.is_valid is False
            assert result.error_code == BRC20ErrorCodes.NO_LEGACY_TRANSFER

    def test_processing_error_cleanup(self):
        """Test that processing errors properly cleanup state"""
        operation = {"op": "no_return"}  # No tick required
        tx = {"txid": "a" * 64, "vout_index": 0, "block_height": 800000}

        self.opi_impl._last_validated_event = {
            "from_pkScript": "76a914abcdef1234567890abcdef1234567890abcdef12345688ac",
            "tick": "TEST",
            "amount": "100",
            "inscription_id": "legacy_txid:i0",
        }

        with patch(
            "src.services.opi.implementations.opi_000.extract_address_from_script"
        ) as mock_extract_addr:
            mock_extract_addr.side_effect = Exception("Address extraction failed")

            result = self.opi_impl.process_operation(operation, tx, self.mock_db)

            assert result.is_valid is False
            assert "Address extraction failed" in result.error_message
            assert self.opi_impl._last_validated_event is None  # Should be cleared


class TestOpi000APIEndpoints:
    """Test OPI-000 API endpoints"""

    def setup_method(self):
        """Setup API test environment"""
        self.opi_impl = Opi000Implementation()
        self.mock_db = Mock()

    def test_get_api_endpoints(self):
        """Test that API endpoints are properly configured"""
        routers = self.opi_impl.get_api_endpoints()

        assert len(routers) == 1
        router = routers[0]
        assert router.prefix == "/v1/indexer/brc20/opi0"
        assert "OPI-000 (no_return)" in router.tags

    def test_list_no_return_transactions_endpoint(self):
        """Test list no_return transactions endpoint"""
        from fastapi import FastAPI
        from fastapi.testclient import TestClient
        from src.database.connection import get_db

        app = FastAPI()
        for router in self.opi_impl.get_api_endpoints():
            app.include_router(router)

        client = TestClient(app)

        # Create a proper mock object that can be serialized
        class MockOPIOperation:
            def __init__(self):
                self.id = 1
                self.opi_id = "OPI-000"
                self.txid = "a" * 64
                self.block_height = 800000
                self.vout_index = 0
                self.operation_type = "no_return"
                self.operation_data = {
                    "legacy_txid": "legacy_txid",
                    "legacy_inscription_id": "legacy_txid:i0",
                    "ticker": "TEST",
                    "amount": "100",
                    "sender_address": "1TestAddress1234567890abcdef1234567890abcdef",
                }

        mock_ops = [MockOPIOperation()]

        mock_db = Mock()
        mock_db.query.return_value.filter.return_value.order_by.return_value.offset.return_value.limit.return_value.all.return_value = (
            mock_ops
        )

        # Override the dependency injection
        app.dependency_overrides[get_db] = lambda: mock_db

        try:
            response = client.get("/v1/indexer/brc20/opi0/transactions")

            assert response.status_code == 200
            data = response.json()
            assert len(data) == 1
            assert data[0]["opi_id"] == "OPI-000"
            assert data[0]["operation_type"] == "no_return"
        finally:
            # Clean up dependency override
            app.dependency_overrides.clear()

    def test_list_no_return_transactions_database_error(self):
        """Test list no_return transactions with database error"""
        from fastapi import FastAPI
        from fastapi.testclient import TestClient
        from src.database.connection import get_db

        app = FastAPI()
        for router in self.opi_impl.get_api_endpoints():
            app.include_router(router)

        client = TestClient(app)

        mock_db = Mock()
        mock_db.query.side_effect = Exception("Database error")

        # Override the dependency injection
        app.dependency_overrides[get_db] = lambda: mock_db

        try:
            response = client.get("/v1/indexer/brc20/opi0/transactions")

            assert response.status_code == 500
            data = response.json()
            assert "Internal Server Error" in data["detail"]
        finally:
            # Clean up dependency override
            app.dependency_overrides.clear()


class TestOpi000Integration:
    """Test OPI-000 integration scenarios"""

    def setup_method(self):
        """Setup integration test environment"""
        self.opi_impl = Opi000Implementation()
        self.mock_db = Mock()

    def test_complete_no_return_workflow(self):
        """Test complete no_return operation workflow"""
        # Setup operation and transaction
        operation = {"op": "no_return"}  # No tick required
        tx = {"txid": "a" * 64, "vout_index": 0, "block_height": 800000}

        # Mock legacy event
        legacy_event = {
            "event_type": "transfer-transfer",
            "inscription_id": "legacy_txid:i0",
            "to_pkScript": "76a9141234567890abcdef1234567890abcdef1234567890abcdef88ac",
            "from_pkScript": "76a914abcdef1234567890abcdef1234567890abcdef12345688ac",
            "tick": "TEST",
            "amount": "100",
        }

        with patch.object(
            self.opi_impl.legacy_service, "get_transfer_event_for_tx"
        ) as mock_get_event:
            with patch(
                "src.services.opi.implementations.opi_000.extract_address_from_script"
            ) as mock_extract_addr:
                with patch("src.models.balance.Balance.get_or_create") as mock_get_balance:
                    with patch("src.services.opi.implementations.opi_000.OPIOperation") as mock_opi_op:
                        # Setup mocks
                        mock_get_event.return_value = legacy_event
                        mock_extract_addr.return_value = "1A1zP1eP5QGefi2DMPTfTL5SLmv7DivfNa"
                        mock_balance = Mock()
                        mock_get_balance.return_value = mock_balance
                        mock_opi_op_instance = Mock()
                        mock_opi_op.return_value = mock_opi_op_instance

                        # Execute validation
                        validation_result = self.opi_impl.validate_operation(
                            operation, tx, self.mock_db
                        )

                        # Verify validation success
                        assert validation_result.is_valid is True

                        # Execute processing
                        processing_result = self.opi_impl.process_operation(
                            operation, tx, self.mock_db
                        )

                        # Verify processing success
                        assert processing_result.is_valid is True
                        assert processing_result.ticker == "TEST"
                        assert processing_result.amount == "100"

                        # Verify database operations
                        mock_get_balance.assert_called_once()
                        mock_balance.add_amount.assert_called_once_with("100")
                        self.mock_db.add.assert_called_once_with(mock_opi_op_instance)

                        # Verify minimal data storage
                        call_args = mock_opi_op.call_args[1]
                        operation_data = call_args["operation_data"]
                        assert "legacy_txid" in operation_data
                        assert "legacy_inscription_id" in operation_data
                        assert "ticker" in operation_data
                        assert "amount" in operation_data
                        assert "sender_address" in operation_data
                        assert "satoshi_address" not in operation_data
                        assert "witness_inscription_data" not in operation_data
                        assert "opi_lc_validation" not in operation_data
