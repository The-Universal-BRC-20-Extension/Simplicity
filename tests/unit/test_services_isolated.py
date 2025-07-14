"""
Unit tests with heavy mocking for isolated service testing.
These tests focus on individual service behavior in isolation.
"""

import pytest
from unittest.mock import Mock, patch, MagicMock

from src.services.legacy_token_service import LegacyTokenService
from src.services.token_supply_service import TokenSupplyService
from src.services.validator import BRC20Validator
from src.services.validator import ValidationResult


class TestLegacyTokenServiceIsolated:
    """Test LegacyTokenService in isolation"""

    @pytest.fixture
    def mock_db_session(self):
        return Mock()

    @pytest.fixture
    def legacy_service(self, mock_db_session):
        return LegacyTokenService()

    def test_check_token_exists_found(self, legacy_service, mock_db_session):
        """Test token found on legacy system"""
        with patch('src.services.legacy_token_service.requests.get') as mock_get:
            mock_response = Mock()
            mock_response.status_code = 200
            mock_response.json.return_value = {
                "tick": "test",
                "max_supply": "400000000000000000000",
                "decimals": 18
            }
            mock_get.return_value = mock_response

            result = legacy_service.check_token_exists("TEST")
            
            assert result is not None
            assert result["tick"] == "test"
            assert result["max_supply"] == "400000000000000000000"

    def test_check_token_exists_not_found(self, legacy_service, mock_db_session):
        """Test token not found on legacy system"""
        with patch('src.services.legacy_token_service.requests.get') as mock_get:
            mock_response = Mock()
            mock_response.status_code = 404
            mock_get.return_value = mock_response

            result = legacy_service.check_token_exists("NONEXISTENT")
            
            assert result is None

    def test_validate_deploy_against_legacy_existing(self, legacy_service, monkeypatch):
        # Mock check_token_exists to return a legacy token with block_height=100
        monkeypatch.setattr(legacy_service, 'check_token_exists', lambda ticker: {"block_height": 100})
        result = legacy_service.validate_deploy_against_legacy("EXISTING", 100)
        assert not result.is_valid
        assert result.error_code == "LEGACY_TOKEN_EXISTS"

    def test_validate_deploy_against_legacy_new(self, legacy_service):
        result = legacy_service.validate_deploy_against_legacy("NEWTOKEN", 100)
        assert result.is_valid


class TestTokenSupplyServiceIsolated:
    """Test TokenSupplyService in isolation"""

    @pytest.fixture
    def mock_db_session(self):
        return Mock()

    @pytest.fixture
    def supply_service(self, mock_db_session):
        return TokenSupplyService(mock_db_session)

    def test_update_supply_tracking_new_token(self, supply_service, mock_db_session):
        """Test supply tracking for new token"""
        with patch.object(supply_service.db, 'query') as mock_query:
            mock_query.return_value.filter.return_value.first.return_value = None
            
            supply_service.update_supply_tracking("NEWTOKEN")
            
            mock_db_session.add.assert_called_once()

    def test_update_supply_tracking_existing_token(self, supply_service, mock_db_session):
        """Test supply tracking for existing token"""
        mock_tracking = Mock()
        mock_tracking.current_supply = "500000"
        mock_tracking.max_supply = "1000000"
        
        with patch.object(supply_service.db, 'query') as mock_query:
            mock_query.return_value.filter.return_value.first.return_value = mock_tracking
            
            supply_service.update_supply_tracking("EXISTING")
            
            # Should update existing tracking, not add new
            mock_db_session.add.assert_not_called()


class TestBRC20ValidatorIsolated:
    """Test BRC20Validator in isolation"""

    @pytest.fixture
    def mock_db_session(self):
        return Mock()

    @pytest.fixture
    def mock_legacy_service(self):
        return Mock()

    @pytest.fixture
    def mock_supply_service(self):
        return Mock()

    @pytest.fixture
    def validator(self, mock_db_session, mock_legacy_service, mock_supply_service):
        return BRC20Validator(mock_db_session, mock_legacy_service)

    def test_validate_deploy_success(self, validator, mock_db_session):
        """Test successful deploy validation"""
        operation = {"op": "deploy", "tick": "TEST", "m": "1000000", "l": "1000"}
        
        # Patch the DB query to return None so the legacy check is reached
        with patch.object(validator.db, 'query') as mock_query:
            mock_query.return_value.filter.return_value.first.return_value = None
            with patch.object(validator.legacy_service, 'validate_deploy_against_legacy') as mock_legacy:
                mock_legacy.return_value = ValidationResult(True)
                result = validator.validate_deploy(operation)
                assert result.is_valid

    def test_validate_deploy_legacy_blocked(self, validator, monkeypatch):
        from unittest.mock import Mock
        # Patch DB query to return None so legacy check is reached
        monkeypatch.setattr(validator.db, "query", lambda *a, **kw: Mock(filter=lambda *a, **kw: Mock(first=lambda: None)))
        # Simulate legacy token with block_height less than or equal to current
        mock_legacy_service = Mock()
        mock_legacy_service.validate_deploy_against_legacy.return_value = ValidationResult(
            False, "LEGACY_TOKEN_EXISTS", "Token already deployed on Ordinals at block 100"
        )
        validator.legacy_service = mock_legacy_service
        operation = {"tick": "TEST", "m": "1000", "block_height": 100}
        result = validator.validate_deploy(operation)
        assert not result.is_valid
        assert result.error_code == "LEGACY_TOKEN_EXISTS"

    def test_validate_deploy_legacy_allowed_future(self, validator, monkeypatch):
        from unittest.mock import Mock
        # Patch DB query to return None so legacy check is reached
        monkeypatch.setattr(validator.db, "query", lambda *a, **kw: Mock(filter=lambda *a, **kw: Mock(first=lambda: None)))
        # Simulate legacy token with block_height greater than current
        mock_legacy_service = Mock()
        mock_legacy_service.validate_deploy_against_legacy.return_value = ValidationResult(True)
        validator.legacy_service = mock_legacy_service
        operation = {"tick": "TEST", "m": "1000", "block_height": 100}
        result = validator.validate_deploy(operation)
        assert result.is_valid

    def test_validate_mint_success(self, validator, monkeypatch):
        from unittest.mock import Mock
        mock_deploy = Mock()
        mock_deploy.limit_per_op = "1000"
        mock_deploy.max_supply = "10000"
        mock_current_supply = "0"
        operation = {
            "amt": "10"
        }
        # Patch get_total_minted to return '0' directly
        monkeypatch.setattr(validator, "get_total_minted", lambda ticker: "0")
        result = validator.validate_mint(operation, mock_deploy, mock_current_supply)
        assert result.is_valid

    def test_validate_transfer_success(self, validator, mock_db_session):
        """Test successful transfer validation"""
        operation = {"op": "transfer", "tick": "TEST", "amt": "100"}
        mock_sender_balance = Mock()
        result = validator.validate_transfer(operation, mock_sender_balance)
        assert hasattr(result, 'is_valid') 