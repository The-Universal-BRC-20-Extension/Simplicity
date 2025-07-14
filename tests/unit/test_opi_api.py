import pytest
from unittest.mock import Mock, patch, MagicMock
from fastapi.testclient import TestClient
from sqlalchemy.orm import Session
from fastapi import HTTPException

from src.api.routers.opi import router
from src.services.opi.registry import OPIRegistry
from src.models.opi_operation import OPIOperation
from src.models.opi_configuration import OPIConfiguration


class MockOPI:
    """Mock OPI implementation for testing"""
    def __init__(self, opi_id):
        self.opi_id = opi_id
    
    def validate_operation(self, operation, tx_info, db_session):
        from src.utils.exceptions import ValidationResult
        return ValidationResult(is_valid=True)
    
    def process_operation(self, operation, tx_info, db_session):
        return Mock(is_valid=True, ticker="TEST", amount="100")


class FilterMock:
    """Mock that properly handles chained database calls"""
    def __init__(self, model_class, return_count=0, return_all=None, return_first=None):
        self.model_class = model_class
        self.return_count = return_count
        self.return_all = return_all or []
        self.return_first = return_first
        self.filter_calls = []
        self.count_calls = 0
        self.all_calls = 0
        self.first_calls = 0
    
    def filter(self, *args, **kwargs):
        self.filter_calls.append((args, kwargs))
        return self
    
    def count(self):
        self.count_calls += 1
        return self.return_count
    
    def all(self):
        self.all_calls += 1
        return self.return_all
    
    def first(self):
        self.first_calls += 1
        return self.return_first
    
    def __iter__(self):
        return iter(self.return_all)
    
    def __len__(self):
        return len(self.return_all)


@pytest.fixture
def mock_db_session():
    """Mock database session with proper chaining"""
    session = Mock(spec=Session)
    
    # Mock query method to return FilterMock
    def mock_query(model_class):
        if model_class == OPIOperation:
            return FilterMock(
                model_class=OPIOperation,
                return_count=1,
                return_all=[
                    Mock(opi_id="OPI-000", operation="no_return", enabled=True)
                ]
            )
        else:
            return FilterMock(model_class=model_class, return_count=0, return_all=[])
    
    session.query = mock_query
    return session


@pytest.fixture
def mock_opi_registry():
    """Mock OPI registry with proper case handling"""
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


class TestOpiApi:
    """Test OPI API endpoints"""

    @patch('src.api.routers.opi.get_db')
    @patch('src.api.routers.opi.opi_registry')
    def test_list_opis_success(self, mock_registry, mock_get_db, client, mock_db_session, mock_opi_registry):
        """Test successful listing of OPIs"""
        mock_get_db.return_value = mock_db_session
        mock_registry.list_opis.return_value = ["OPI-000", "OPI-001"]
        
        response = client.get("/v1/indexer/brc20/opi")
        
        assert response.status_code == 200
        data = response.json()
        assert "opis" in data
        assert len(data["opis"]) == 2
        assert "OPI-000" in data["opis"]
        assert "OPI-001" in data["opis"]

    def test_get_opi_info_success(self, client, db_session):
        """Test successful retrieval of specific OPI info"""
        # Ensure OPI-000 is registered in registry
        from src.services.opi.implementations.opi_000 import Opi000Implementation
        from src.services.opi.registry import opi_registry
        opi_registry.register_opi(Opi000Implementation())
        
        # Create required OPIConfiguration in database using real DB
        from src.models.opi_configuration import OPIConfiguration
        opi_config = OPIConfiguration(
            opi_id="OPI-000",
            is_enabled=True,
            version="1.0",
            description="No Return Operations",
            configuration={"enabled": True}
        )
        db_session.add(opi_config)
        db_session.commit()

        response = client.get("/v1/indexer/brc20/opi/OPI-000")
        assert response.status_code == 200

    @patch('src.api.routers.opi.get_db')
    @patch('src.api.routers.opi.opi_registry')
    def test_get_opi_info_not_found(self, mock_registry, mock_get_db, client, mock_db_session, mock_opi_registry):
        """Test OPI not found"""
        mock_get_db.return_value = mock_db_session
        mock_registry.get_opi.return_value = None
        
        response = client.get("/v1/indexer/brc20/opi/INVALID-OPI")
        assert response.status_code == 404
        data = response.json()
        assert "not found" in data["detail"].lower()

    def test_get_opi_operations_success(self, client, db_session):
        """Test successful retrieval of OPI operations"""
        # Ensure OPI-000 is registered in registry
        from src.services.opi.implementations.opi_000 import Opi000Implementation
        from src.services.opi.registry import opi_registry
        opi_registry.register_opi(Opi000Implementation())
        
        # Create required OPIConfiguration in database using real DB
        from src.models.opi_configuration import OPIConfiguration
        opi_config = OPIConfiguration(
            opi_id="OPI-000",
            is_enabled=True,
            version="1.0",
            description="No Return Operations",
            configuration={"enabled": True}
        )
        db_session.add(opi_config)
        db_session.commit()

        response = client.get("/v1/indexer/brc20/opi/OPI-000")
        assert response.status_code == 200

    @patch('src.api.routers.opi.get_db')
    @patch('src.api.routers.opi.opi_registry')
    def test_get_opi_operations_not_found(self, mock_registry, mock_get_db, client, mock_db_session, mock_opi_registry):
        """Test OPI operations not found"""
        mock_get_db.return_value = mock_db_session
        mock_registry.get_opi.return_value = None
        
        response = client.get("/v1/indexer/brc20/opi/NONEXISTENT")
        assert response.status_code == 404
        data = response.json()
        assert "not found" in data["detail"].lower()

    def test_get_opi_operations_empty(self, client, db_session):
        """Test empty OPI operations"""
        # Ensure OPI-000 is registered in registry
        from src.services.opi.implementations.opi_000 import Opi000Implementation
        from src.services.opi.registry import opi_registry
        opi_registry.register_opi(Opi000Implementation())
        
        # Create required OPIConfiguration in database using real DB
        from src.models.opi_configuration import OPIConfiguration
        opi_config = OPIConfiguration(
            opi_id="OPI-000",
            is_enabled=True,
            version="1.0",
            description="No Return Operations",
            configuration={"enabled": True}
        )
        db_session.add(opi_config)
        db_session.commit()

        response = client.get("/v1/indexer/brc20/opi/OPI-000")
        assert response.status_code == 200

    @patch('src.api.routers.opi.get_db')
    @patch('src.api.routers.opi.opi_registry')
    def test_get_legacy_transfers_success(self, mock_registry, mock_get_db, client, mock_db_session, mock_opi_registry):
        """Test successful retrieval of legacy transfers"""
        mock_get_db.return_value = mock_db_session
        mock_registry.get_opi.return_value = MockOPI("OPI-000")
        
        response = client.get("/v1/indexer/brc20/opi/no_return/transactions")
        
        assert response.status_code == 200
        data = response.json()
        assert "total" in data
        assert "transactions" in data

    @patch('src.api.routers.opi.get_db')
    @patch('src.api.routers.opi.opi_registry')
    def test_get_legacy_transfers_not_found(self, mock_registry, mock_get_db, client, mock_db_session, mock_opi_registry):
        """Test legacy transfers not found"""
        mock_get_db.return_value = mock_db_session
        mock_registry.get_opi.return_value = None
        
        response = client.get("/v1/indexer/brc20/opi/no_return/transfers/" + "b" * 64)
        assert response.status_code == 404
        data = response.json()
        assert "no_return operation found" in data["detail"].lower()

    @patch('src.api.routers.opi.get_db')
    @patch('src.api.routers.opi.opi_registry')
    def test_get_legacy_transfers_empty(self, mock_registry, mock_get_db, client, mock_db_session, mock_opi_registry):
        """Test empty legacy transfers"""
        mock_get_db.return_value = mock_db_session
        mock_registry.get_opi.return_value = MockOPI("OPI-000")
        
        # Mock empty database results
        mock_query = Mock()
        mock_query.filter.return_value = mock_query
        mock_query.all.return_value = []
        mock_db_session.query.return_value = mock_query
        
        response = client.get("/v1/indexer/brc20/opi/no_return/transactions")
        
        assert response.status_code == 200
        data = response.json()
        assert data["total"] == 0
        assert len(data["transactions"]) == 0

    def test_case_sensitivity_handling(self, client, db_session):
        """Test case sensitivity handling"""
        # Ensure OPI-000 is registered in registry
        from src.services.opi.implementations.opi_000 import Opi000Implementation
        from src.services.opi.registry import opi_registry
        opi_registry.register_opi(Opi000Implementation())
        
        # Create required OPIConfiguration in database using real DB
        from src.models.opi_configuration import OPIConfiguration
        opi_config = OPIConfiguration(
            opi_id="OPI-000",
            is_enabled=True,
            version="1.0",
            description="No Return Operations",
            configuration={"enabled": True}
        )
        db_session.add(opi_config)
        db_session.commit()

        # Test with different case variations
        response = client.get("/v1/indexer/brc20/opi/opi-000")
        assert response.status_code == 200

    @patch('src.api.routers.opi.get_db')
    @patch('src.api.routers.opi.opi_registry')
    def test_api_error_handling(self, mock_registry, mock_get_db, client, mock_db_session, mock_opi_registry):
        """Test API error handling"""
        mock_get_db.return_value = mock_db_session
        mock_registry.get_opi.side_effect = Exception("Database error")
        
        response = client.get("/v1/indexer/brc20/opi/OPI-000")
        assert response.status_code == 500
        data = response.json()
        assert "database error" in data["detail"].lower() 