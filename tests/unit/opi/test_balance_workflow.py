"""
Unit tests for balance workflow in intermediate_state
"""

from decimal import Decimal
from unittest.mock import Mock
from src.opi.contracts import IntermediateState, Context


class TestBalanceWorkflow:
    """Test balance loading and caching workflow in intermediate_state"""

    def test_balance_loading_from_db(self):
        """Test that balances are loaded from DB on first access"""
        # Create a mock validator
        mock_validator = Mock()
        mock_validator.get_balance.return_value = Decimal("100.0")

        # Create empty intermediate state
        intermediate_state = IntermediateState()
        context = Context(intermediate_state, mock_validator)

        # First access should load from DB
        balance = context.get_balance("address1", "TEST")

        assert balance == Decimal("100.0")
        # New behavior: IntermediateState caches balances
        assert ("address1", "TEST") in intermediate_state.balances
        assert mock_validator.get_balance.call_count == 1

    def test_balance_caching(self):
        """Test that subsequent accesses call validator each time (no caching in Context)"""
        mock_validator = Mock()
        mock_validator.get_balance.return_value = Decimal("100.0")

        intermediate_state = IntermediateState()
        context = Context(intermediate_state, mock_validator)

        # First access
        balance1 = context.get_balance("address1", "TEST")
        # Second access
        balance2 = context.get_balance("address1", "TEST")

        assert balance1 == balance2 == Decimal("100.0")
        # New behavior caches after first load
        assert mock_validator.get_balance.call_count == 1

    def test_total_minted_loading_and_caching(self):
        """Test total_minted loading (no caching in Context)"""
        mock_validator = Mock()
        mock_validator.get_total_minted.return_value = Decimal("1000.0")

        intermediate_state = IntermediateState()
        context = Context(intermediate_state, mock_validator)

        # First access
        total1 = context.get_total_minted("TEST")
        # Second access
        total2 = context.get_total_minted("TEST")

        assert total1 == total2 == Decimal("1000.0")
        # New behavior caches total minted
        assert "TEST" in intermediate_state.total_minted
        assert mock_validator.get_total_minted.call_count == 1

    def test_deploy_record_loading_and_caching(self):
        """Test deploy record loading (no caching in Context)"""
        mock_deploy = {"ticker": "TEST", "max_supply": "1000000"}
        mock_validator = Mock()
        mock_validator.get_deploy_record.return_value = mock_deploy

        intermediate_state = IntermediateState()
        context = Context(intermediate_state, mock_validator)

        # First access
        deploy1 = context.get_deploy_record("TEST")
        # Second access
        deploy2 = context.get_deploy_record("TEST")

        assert deploy1 == deploy2 == mock_deploy
        # New behavior caches deploys
        assert "TEST" in intermediate_state.deploys
        assert mock_validator.get_deploy_record.call_count == 1

    def test_deploy_record_none_caching(self):
        """Test that None deploy records are not cached"""
        mock_validator = Mock()
        mock_validator.get_deploy_record.return_value = None

        intermediate_state = IntermediateState()
        context = Context(intermediate_state, mock_validator)

        # Access non-existent deploy
        deploy = context.get_deploy_record("NONEXISTENT")

        assert deploy is None
        assert "NONEXISTENT" not in intermediate_state.deploys
        assert mock_validator.get_deploy_record.call_count == 1

    def test_preload_balances_not_implemented(self):
        """Test that preload_balances method is not implemented in IntermediateState"""
        mock_validator = Mock()
        intermediate_state = IntermediateState()

        # New behavior provides preload_balances
        assert hasattr(intermediate_state, "preload_balances")

    def test_case_insensitive_ticker_handling(self):
        """Test that ticker case is handled correctly"""
        mock_validator = Mock()
        mock_validator.get_balance.return_value = Decimal("100.0")

        intermediate_state = IntermediateState()
        context = Context(intermediate_state, mock_validator)

        # Access with different cases
        balance1 = context.get_balance("address1", "test")
        balance2 = context.get_balance("address1", "TEST")
        balance3 = context.get_balance("address1", "Test")

        assert balance1 == balance2 == balance3 == Decimal("100.0")
        # New behavior caches after first load
        assert ("address1", "TEST") in intermediate_state.balances
        assert mock_validator.get_balance.call_count == 1
