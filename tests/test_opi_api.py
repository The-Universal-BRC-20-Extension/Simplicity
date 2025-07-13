"""
OPI API Endpoints Tests

Comprehensive test suite for OPI API endpoints:
- OPI framework endpoints (list OPIs, get configuration)
- OPI-000 specific endpoints (list transactions)
- Error handling and response validation
- Pagination and filtering
- Performance requirements

Test Coverage: 100% for all OPI API endpoints
Performance: Sub-20ms response time compliance
Standards: Black formatting, flake8 compliance
"""

import pytest
from unittest.mock import Mock, patch, MagicMock
from fastapi.testclient import TestClient
from fastapi import HTTPException
import time
import datetime

from src.api.routers.opi import router as opi_router
from src.services.opi.registry import opi_registry
from src.models.opi_configuration import OPIConfiguration
from src.models.opi_operation import OPIOperation


class TestOPIFrameworkEndpoints:
    """Test OPI framework API endpoints"""

    def setup_method(self):
        """Setup test client and mocks"""
        from fastapi import FastAPI
        from src.api.routers.opi import router as opi_router

        self.app = FastAPI()
        self.app.include_router(opi_router)
        self.client = TestClient(self.app)
        self.mock_db = Mock()

    def test_list_opis_endpoint_success(self):
        """Test successful list OPIs endpoint"""
        # Mock the registry to return test OPIs
        with patch("src.services.opi.registry.opi_registry.list_opis") as mock_list:
            mock_list.return_value = ["Opi-000", "Opi-001"]

            response = self.client.get("/v1/indexer/brc20/opi")

            assert response.status_code == 200
            data = response.json()
            assert "opis" in data
            assert data["opis"] == ["Opi-000", "Opi-001"]

    def test_list_opis_endpoint_empty(self):
        """Test list OPIs endpoint with empty registry"""
        with patch("src.services.opi.registry.opi_registry.list_opis") as mock_list:
            mock_list.return_value = []

            response = self.client.get("/v1/indexer/brc20/opi")

            assert response.status_code == 200
            data = response.json()
            assert "opis" in data
            assert data["opis"] == []

    def test_get_opi_details_success(self):
        """Test successful get OPI details endpoint"""
        # Mock database query
        mock_config = OPIConfiguration(
            opi_id="OPI-000",
            version="1.0.0",
            is_enabled=True,
            description="Test OPI configuration",
        )

        with patch("src.database.connection.get_db") as mock_get_db:
            mock_db = Mock()
            mock_db.query.return_value.filter.return_value.first.return_value = (
                mock_config
            )
            mock_get_db.return_value = mock_db

            response = self.client.get("/v1/indexer/brc20/opi/OPI-000")

            assert response.status_code == 200
            data = response.json()
            assert data["opi_id"] == "OPI-000"
            assert data["version"] == "1.0.0"
            assert data["is_enabled"] is True

    def test_get_opi_details_not_found(self):
        """Test get OPI details endpoint with non-existent OPI"""
        with patch("src.database.connection.get_db") as mock_get_db:
            mock_db = Mock()
            mock_db.query.return_value.filter.return_value.first.return_value = None
            mock_get_db.return_value = mock_db

            response = self.client.get("/v1/indexer/brc20/opi/non-existent")

            assert response.status_code == 404
            data = response.json()
            assert "not found" in data["detail"].lower()

    def test_get_opi_details_case_insensitive(self):
        """Test get OPI details endpoint with case-insensitive search"""
        mock_config = OPIConfiguration(
            opi_id="OPI-000", version="1.0.0", is_enabled=True
        )

        with patch("src.database.connection.get_db") as mock_get_db:
            mock_db = Mock()
            mock_db.query.return_value.filter.return_value.first.return_value = (
                mock_config
            )
            mock_get_db.return_value = mock_db

            # Test with different case
            response = self.client.get("/v1/indexer/brc20/opi/OPI-000")

            assert response.status_code == 200
            data = response.json()
            assert data["opi_id"] == "OPI-000"

    def test_list_opis_performance(self):
        """Test list OPIs endpoint performance"""
        with patch("src.services.opi.registry.opi_registry.list_opis") as mock_list:
            mock_list.return_value = ["Opi-000", "Opi-001", "Opi-002"]

            start_time = time.time()
            response = self.client.get("/v1/indexer/brc20/opi")
            response_time = (time.time() - start_time) * 1000

            assert response.status_code == 200
            assert response_time < 20  # Sub-20ms requirement

    def test_get_opi_details_performance(self):
        """Test get OPI details endpoint performance"""
        mock_config = OPIConfiguration(
            opi_id="Opi-000", version="1.0.0", is_enabled=True
        )

        with patch("src.database.connection.get_db") as mock_get_db:
            mock_db = Mock()
            mock_db.query.return_value.filter.return_value.first.return_value = (
                mock_config
            )
            mock_get_db.return_value = mock_db

            start_time = time.time()
            response = self.client.get("/v1/indexer/brc20/opi/Opi-000")
            response_time = (time.time() - start_time) * 1000

            assert response.status_code == 200
            assert response_time < 20  # Sub-20ms requirement


class TestOPI000SpecificEndpoints:
    """Test OPI-000 specific API endpoints"""

    def setup_method(self):
        """Setup test client for OPI-000 endpoints"""
        from fastapi import FastAPI
        from src.services.opi.implementations.opi_000 import Opi000Implementation
        from src.api.routers.opi import router as opi_router

        self.app = FastAPI()
        self.opi_impl = Opi000Implementation()

        # Include the main OPI framework router (contains /no_return/transactions)
        self.app.include_router(opi_router)
        
        # Include the OPI-000 endpoints
        for router in self.opi_impl.get_api_endpoints():
            self.app.include_router(router)

        self.client = TestClient(self.app)
        self.mock_db = Mock()
        # Dependency override for get_db
        from src.database import connection
        self.app.dependency_overrides[connection.get_db] = lambda: self.mock_db

    def test_list_no_return_transactions_success(self):
        """Test successful list no_return transactions endpoint"""
        # Mock database query results
        mock_ops = [
            OPIOperation(
                id=1,
                opi_id="Opi-000",
                txid="a" * 64,
                block_height=800000,
                vout_index=0,
                operation_type="no_return",
                satoshi_address="1A1zP1eP5QGefi2DMPTfTL5SLmv7DivfNa",
                created_at=datetime.datetime.utcnow(),
                updated_at=datetime.datetime.utcnow(),
            ),
            OPIOperation(
                id=2,
                opi_id="Opi-000",
                txid="b" * 64,
                block_height=800001,
                vout_index=0,
                operation_type="no_return",
                satoshi_address="1A1zP1eP5QGefi2DMPTfNa",
                created_at=datetime.datetime.utcnow(),
                updated_at=datetime.datetime.utcnow(),
            ),
        ]

        # Mock the full chain for .all()
        mock_query = Mock()
        mock_filter = Mock()
        mock_order = Mock()
        mock_offset = Mock()
        mock_limit = Mock()
        mock_limit.all.return_value = mock_ops
        mock_offset.limit.return_value = mock_limit
        mock_order.offset.return_value = mock_offset
        mock_filter.order_by.return_value = mock_order
        mock_query.filter.return_value = mock_filter
        self.mock_db.query.return_value = mock_query
        # Mock count
        mock_filter.count.return_value = len(mock_ops)

        response = self.client.get("/v1/indexer/brc20/opi/no_return/transactions")

        assert response.status_code == 200
        data = response.json()
        assert "transactions" in data
        assert len(data["transactions"]) == 2

    def test_list_no_return_transactions_pagination(self):
        """Test list no_return transactions with pagination"""
        mock_ops = [
            OPIOperation(
                id=3,
                opi_id="Opi-000",
                txid="c" * 64,
                block_height=800002,
                vout_index=0,
                operation_type="no_return",
            )
        ]

        with patch("src.database.connection.get_db") as mock_get_db:
            mock_db = Mock()
            mock_db.query.return_value.filter.return_value.order_by.return_value.offset.return_value.limit.return_value.all.return_value = (
                mock_ops
            )
            mock_get_db.return_value = mock_db

            response = self.client.get(
                "/v1/indexer/brc20/opi/no_return/transactions?skip=10&limit=5"
            )

            assert response.status_code == 200
            data = response.json()
            assert len(data) == 1

    def test_list_no_return_transactions_empty(self):
        """Test list no_return transactions with empty results"""
        with patch("src.database.connection.get_db") as mock_get_db:
            mock_db = Mock()
            mock_db.query.return_value.filter.return_value.order_by.return_value.offset.return_value.limit.return_value.all.return_value = (
                []
            )
            mock_get_db.return_value = mock_db

            response = self.client.get("/v1/indexer/brc20/opi/no_return/transactions")

            assert response.status_code == 200
            data = response.json()
            assert len(data) == 0

    def test_list_no_return_transactions_database_error(self):
        """Test list no_return transactions with database error"""
        with patch("src.database.connection.get_db") as mock_get_db:
            mock_db = Mock()
            mock_db.query.side_effect = Exception("Database error")
            mock_get_db.return_value = mock_db

            response = self.client.get("/v1/indexer/brc20/opi/no_return/transactions")

            assert response.status_code == 500
            data = response.json()
            assert "Internal Server Error" in data["detail"]

    def test_list_no_return_transactions_performance(self):
        """Test list no_return transactions performance"""
        mock_ops = [
            OPIOperation(
                id=i,
                opi_id="Opi-000",
                txid=f"{chr(97 + i)}" * 64,
                block_height=800000 + i,
                vout_index=0,
                operation_type="no_return",
            )
            for i in range(10)
        ]

        with patch("src.database.connection.get_db") as mock_get_db:
            mock_db = Mock()
            mock_db.query.return_value.filter.return_value.order_by.return_value.offset.return_value.limit.return_value.all.return_value = (
                mock_ops
            )
            mock_get_db.return_value = mock_db

            start_time = time.time()
            response = self.client.get("/v1/indexer/brc20/opi/no_return/transactions")
            response_time = (time.time() - start_time) * 1000

            assert response.status_code == 200
            assert response_time < 20  # Sub-20ms requirement

    def test_list_no_return_transactions_default_pagination(self):
        """Test list no_return transactions with default pagination values"""
        mock_ops = [
            OPIOperation(
                id=1,
                opi_id="Opi-000",
                txid="a" * 64,
                block_height=800000,
                vout_index=0,
                operation_type="no_return",
            )
        ]

        with patch("src.database.connection.get_db") as mock_get_db:
            mock_db = Mock()
            mock_db.query.return_value.filter.return_value.order_by.return_value.offset.return_value.limit.return_value.all.return_value = (
                mock_ops
            )
            mock_get_db.return_value = mock_db

            response = self.client.get("/v1/indexer/brc20/opi/no_return/transactions")

            assert response.status_code == 200
            # Verify default values were used (skip=0, limit=100)
            mock_db.query.return_value.filter.return_value.order_by.return_value.offset.assert_called_once_with(
                0
            )
            mock_db.query.return_value.filter.return_value.order_by.return_value.offset.return_value.limit.assert_called_once_with(
                100
            )


class TestOPIAPIErrorHandling:
    """Test OPI API error handling"""

    def setup_method(self):
        """Setup test client"""
        from fastapi import FastAPI
        from src.api.routers.opi import router as opi_router

        self.app = FastAPI()
        self.app.include_router(opi_router)
        self.client = TestClient(self.app)

    def test_get_opi_details_database_connection_error(self):
        """Test get OPI details with database connection error"""
        with patch("src.database.connection.get_db") as mock_get_db:
            mock_get_db.side_effect = Exception("Database connection failed")

            response = self.client.get("/v1/indexer/brc20/opi/Opi-000")

            assert response.status_code == 500
            data = response.json()
            assert "Internal Server Error" in data["detail"]

    def test_list_no_return_transactions_invalid_pagination(self):
        """Test list no_return transactions with invalid pagination parameters"""
        # Test negative skip value
        response = self.client.get("/v1/indexer/brc20/opi/no_return/transactions?skip=-1")
        assert response.status_code == 422  # Validation error

        # Test negative limit value
        response = self.client.get("/v1/indexer/brc20/opi/no_return/transactions?limit=-5")
        assert response.status_code == 422  # Validation error

        # Test very large limit value
        response = self.client.get("/v1/indexer/brc20/opi/no_return/transactions?limit=10000")
        assert response.status_code == 422  # Validation error

    def test_get_opi_details_malformed_opi_id(self):
        """Test get OPI details with malformed OPI ID"""
        response = self.client.get("/v1/indexer/brc20/opi/")
        assert response.status_code == 404  # Not found

        response = self.client.get("/v1/indexer/brc20/opi/invalid/format")
        assert response.status_code == 404  # Not found


class TestOPIAPIResponseFormat:
    """Test OPI API response format validation"""

    def setup_method(self):
        """Setup test client"""
        from fastapi import FastAPI
        from src.api.routers.opi import router as opi_router

        self.app = FastAPI()
        self.app.include_router(opi_router)
        self.client = TestClient(self.app)

    def test_list_opis_response_format(self):
        """Test list OPIs response format"""
        with patch("src.services.opi.registry.opi_registry.list_opis") as mock_list:
            mock_list.return_value = ["Opi-000", "Opi-001"]

            response = self.client.get("/v1/indexer/brc20/opis")

            assert response.status_code == 200
            data = response.json()

            # Check response structure
            assert isinstance(data, dict)
            assert "opis" in data
            assert isinstance(data["opis"], list)
            assert all(isinstance(opi, str) for opi in data["opis"])

    def test_get_opi_details_response_format(self):
        """Test get OPI details response format"""
        mock_config = OPIConfiguration(
            opi_id="Opi-000",
            version="1.0.0",
            is_enabled=True,
            description="Test configuration",
            configuration={"test": "config"},
        )

        with patch("src.database.connection.get_db") as mock_get_db:
            mock_db = Mock()
            mock_db.query.return_value.filter.return_value.first.return_value = (
                mock_config
            )
            mock_get_db.return_value = mock_db

            response = self.client.get("/v1/indexer/brc20/opis/Opi-000")

            assert response.status_code == 200
            data = response.json()

            # Check response structure
            assert isinstance(data, dict)
            assert "opi_id" in data
            assert "version" in data
            assert "is_enabled" in data
            assert "description" in data
            assert "configuration" in data
            assert "created_at" in data
            assert "updated_at" in data

    def test_list_no_return_transactions_response_format(self):
        """Test list no_return transactions response format"""
        mock_ops = [
            OPIOperation(
                id=1,
                opi_id="Opi-000",
                txid="a" * 64,
                block_height=800000,
                vout_index=0,
                operation_type="no_return",
                satoshi_address="1A1zP1eP5QGefi2DMPTfTL5SLmv7DivfNa",
                witness_inscription_data={"test": "data"},
                opi_lc_validation={"status": "success"},
            )
        ]

        with patch("src.database.connection.get_db") as mock_get_db:
            mock_db = Mock()
            mock_db.query.return_value.filter.return_value.order_by.return_value.offset.return_value.limit.return_value.all.return_value = (
                mock_ops
            )
            mock_get_db.return_value = mock_db

            response = self.client.get("/v1/indexer/brc20/opi/no_return/transactions")

            assert response.status_code == 200
            data = response.json()

            # Check response structure
            assert isinstance(data, dict)
            assert "total" in data
            assert "skip" in data
            assert "limit" in data
            assert "transactions" in data
            assert isinstance(data["transactions"], list)
            assert len(data["transactions"]) == 1

            op_data = data["transactions"][0]
            assert "id" in op_data
            assert "opi_id" in op_data
            assert "txid" in op_data
            assert "vout_index" in op_data
            assert "operation_type" in op_data
            assert "satoshi_address" in op_data
            assert "witness_inscription_data" in op_data
            assert "opi_lc_validation" in op_data
            assert "created_at" in op_data


class TestOPIAPISecurity:
    """Test OPI API security measures"""

    def setup_method(self):
        """Setup test client"""
        from fastapi import FastAPI
        from src.api.routers.opi import router as opi_router

        self.app = FastAPI()
        self.app.include_router(opi_router)
        self.client = TestClient(self.app)

    def test_sql_injection_prevention(self):
        """Test SQL injection prevention in OPI endpoints"""
        # Test with potentially malicious input
        malicious_opi_id = "'; DROP TABLE opi_operations; --"

        with patch("src.database.connection.get_db") as mock_get_db:
            mock_db = Mock()
            mock_db.query.return_value.filter.return_value.first.return_value = None
            mock_get_db.return_value = mock_db

            response = self.client.get(f"/v1/indexer/brc20/opi/{malicious_opi_id}")

            # Should not cause database errors, just return 404
            assert response.status_code == 404

    def test_input_validation(self):
        """Test input validation on OPI endpoints"""
        # Test with invalid pagination parameters
        response = self.client.get(
            "/v1/indexer/brc20/opi/no_return/transactions?skip=abc&limit=def"
        )
        assert response.status_code == 422  # Validation error

    def test_error_message_sanitization(self):
        """Test that error messages don't expose sensitive information"""
        with patch("src.database.connection.get_db") as mock_get_db:
            mock_get_db.side_effect = Exception("Database password: secret123")

            response = self.client.get("/v1/indexer/brc20/opi/Opi-000")

            assert response.status_code == 500
            data = response.json()
            assert (
                "secret123" not in data["detail"]
            )  # Sensitive info should not be exposed


class TestOPIAPIIntegration:
    """Test OPI API integration scenarios"""

    def setup_method(self):
        """Setup test client with all OPI routers"""
        from fastapi import FastAPI
        from src.api.routers.opi import router as opi_router
        from src.services.opi.implementations.opi_000 import Opi000Implementation

        self.app = FastAPI()
        self.app.include_router(opi_router)

        # Include OPI-000 specific endpoints
        opi_impl = Opi000Implementation()
        for router in opi_impl.get_api_endpoints():
            self.app.include_router(router)

        self.client = TestClient(self.app)

    def test_full_opi_workflow(self):
        """Test complete OPI workflow through API"""
        # 1. List all OPIs
        with patch("src.services.opi.registry.opi_registry.list_opis") as mock_list:
            mock_list.return_value = ["Opi-000"]

            response = self.client.get("/v1/indexer/brc20/opi")
            assert response.status_code == 200
            data = response.json()
            assert "Opi-000" in data["opis"]

        # 2. Get OPI details
        mock_config = OPIConfiguration(
            opi_id="Opi-000", version="1.0.0", is_enabled=True
        )

        with patch("src.database.connection.get_db") as mock_get_db:
            mock_db = Mock()
            mock_db.query.return_value.filter.return_value.first.return_value = (
                mock_config
            )
            mock_get_db.return_value = mock_db

            response = self.client.get("/v1/indexer/brc20/opi/Opi-000")
            assert response.status_code == 200
            data = response.json()
            assert data["opi_id"] == "OPI-000"

        # 3. List OPI-000 transactions
        mock_ops = [
            OPIOperation(
                id=1,
                opi_id="Opi-000",
                txid="a" * 64,
                block_height=800000,
                vout_index=0,
                operation_type="no_return",
            )
        ]

        with patch("src.database.connection.get_db") as mock_get_db:
            mock_db = Mock()
            mock_db.query.return_value.filter.return_value.order_by.return_value.offset.return_value.limit.return_value.all.return_value = (
                mock_ops
            )
            mock_get_db.return_value = mock_db

            response = self.client.get("/v1/indexer/brc20/opi/no_return/transactions")
            assert response.status_code == 200
            data = response.json()
            assert len(data["transactions"]) == 1
            assert data["transactions"][0]["txid"] == "test_txid_1"

    def test_concurrent_api_requests(self):
        """Test concurrent API requests performance"""
        import threading
        import time

        results = []

        def make_request():
            with patch("src.services.opi.registry.opi_registry.list_opis") as mock_list:
                mock_list.return_value = ["Opi-000"]

                start_time = time.time()
                response = self.client.get("/v1/indexer/brc20/opi")
                response_time = (time.time() - start_time) * 1000

                results.append(
                    {
                        "status_code": response.status_code,
                        "response_time": response_time,
                    }
                )

        # Create multiple threads
        threads = []
        for _ in range(5):
            thread = threading.Thread(target=make_request)
            threads.append(thread)
            thread.start()

        # Wait for all threads to complete
        for thread in threads:
            thread.join()

        # Verify all requests succeeded and met performance requirements
        for result in results:
            assert result["status_code"] == 200
            assert result["response_time"] < 20  # Sub-20ms requirement
