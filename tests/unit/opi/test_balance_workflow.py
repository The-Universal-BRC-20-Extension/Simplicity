"""
Unit tests for balance workflow in intermediate_state
"""

import pytest
from decimal import Decimal
from unittest.mock import Mock, patch
from src.opi.contracts import IntermediateState, Context


class TestBalanceWorkflow:
    """Test balance loading and caching workflow in intermediate_state"""

    def test_balance_loading_from_db(self):
        """Test that balances are automatically loaded from DB on first access"""
        # Create a mock validator
        mock_validator = Mock()
        mock_validator.get_balance.return_value = Decimal("100.0")

        # Create empty intermediate state
        intermediate_state = IntermediateState()
        context = Context(intermediate_state, mock_validator)

        # First access should load from DB
        balance = context.get_balance("address1", "TEST")

        assert balance == Decimal("100.0")
        assert ("address1", "TEST") in intermediate_state.balances
        assert intermediate_state.balances[("address1", "TEST")] == Decimal("100.0")
        assert mock_validator.get_balance.call_count == 1

    def test_balance_caching(self):
        """Test that subsequent accesses use cached values"""
        mock_validator = Mock()
        mock_validator.get_balance.return_value = Decimal("100.0")

        intermediate_state = IntermediateState()
        context = Context(intermediate_state, mock_validator)

        # First access
        balance1 = context.get_balance("address1", "TEST")
        # Second access
        balance2 = context.get_balance("address1", "TEST")

        assert balance1 == balance2 == Decimal("100.0")
        assert mock_validator.get_balance.call_count == 1  # Should only be called once

    def test_total_minted_loading_and_caching(self):
        """Test total_minted loading and caching"""
        mock_validator = Mock()
        mock_validator.get_total_minted.return_value = Decimal("1000.0")

        intermediate_state = IntermediateState()
        context = Context(intermediate_state, mock_validator)

        # First access
        total1 = context.get_total_minted("TEST")
        # Second access
        total2 = context.get_total_minted("TEST")

        assert total1 == total2 == Decimal("1000.0")
        assert "TEST" in intermediate_state.total_minted
        assert intermediate_state.total_minted["TEST"] == Decimal("1000.0")
        assert mock_validator.get_total_minted.call_count == 1

    def test_deploy_record_loading_and_caching(self):
        """Test deploy record loading and caching"""
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
        assert "TEST" in intermediate_state.deploys
        assert intermediate_state.deploys["TEST"] == mock_deploy
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

    def test_preload_balances(self):
        """Test preload_balances method"""
        mock_validator = Mock()
        mock_validator.get_balance.return_value = Decimal("50.0")

        intermediate_state = IntermediateState()

        # Preload balances
        intermediate_state.preload_balances(["addr1", "addr2"], ["TEST", "COIN"], mock_validator)

        # Check that all combinations are loaded
        expected_keys = [("addr1", "TEST"), ("addr1", "COIN"), ("addr2", "TEST"), ("addr2", "COIN")]

        for key in expected_keys:
            assert key in intermediate_state.balances
            assert intermediate_state.balances[key] == Decimal("50.0")

        assert mock_validator.get_balance.call_count == 4

    def test_preload_balances_skips_existing(self):
        """Test that preload_balances skips already existing balances"""
        mock_validator = Mock()
        mock_validator.get_balance.return_value = Decimal("50.0")

        intermediate_state = IntermediateState()

        # Manually set one balance
        intermediate_state.balances[("addr1", "TEST")] = Decimal("100.0")

        # Preload balances
        intermediate_state.preload_balances(["addr1", "addr2"], ["TEST", "COIN"], mock_validator)

        # Check that existing balance was not overwritten
        assert intermediate_state.balances[("addr1", "TEST")] == Decimal("100.0")

        # Check that other balances were loaded
        assert ("addr1", "COIN") in intermediate_state.balances
        assert ("addr2", "TEST") in intermediate_state.balances
        assert ("addr2", "COIN") in intermediate_state.balances

        # Should only call validator for 3 new balances (not the existing one)
        assert mock_validator.get_balance.call_count == 3

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
        assert ("address1", "TEST") in intermediate_state.balances
        assert mock_validator.get_balance.call_count == 1  # Should only be called once
