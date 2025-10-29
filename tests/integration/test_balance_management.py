from decimal import Decimal
from unittest.mock import Mock

import pytest
from sqlalchemy.orm import Session

from src.models.balance import Balance


class TestBalanceManagement:

    @pytest.fixture
    def mock_session(self):
        return Mock(spec=Session)

    def test_balance_creation(self, mock_session):
        mock_query = Mock()
        mock_query.filter_by.return_value.first.return_value = None
        mock_session.query.return_value = mock_query

        balance = Balance.get_or_create(mock_session, "test_address", "TEST")

        assert balance.address == "test_address"
        assert balance.ticker == "TEST"
        assert balance.balance == Decimal("0")

        mock_session.add.assert_called_once_with(balance)
        mock_session.flush.assert_called_once()

    def test_balance_get_existing(self, mock_session):
        existing_balance = Balance(address="test_address", ticker="TEST", balance=Decimal("100"))

        mock_query = Mock()
        mock_query.filter_by.return_value.first.return_value = existing_balance
        mock_session.query.return_value = mock_query

        balance = Balance.get_or_create(mock_session, "test_address", "TEST")

        assert balance == existing_balance
        assert balance.balance == Decimal("100")

        mock_session.add.assert_not_called()
        mock_session.flush.assert_not_called()

    def test_balance_update_mint(self):
        balance = Balance(address="test_address", ticker="TEST", balance=Decimal("100"))

        balance.add_amount("50")

        assert balance.balance == Decimal("150")

    def test_balance_update_transfer_sufficient(self):
        balance = Balance(address="test_address", ticker="TEST", balance=Decimal("100"))

        result = balance.subtract_amount("30")

        assert result is True
        assert balance.balance == Decimal("70")

    def test_balance_update_transfer_insufficient(self):
        balance = Balance(address="test_address", ticker="TEST", balance=Decimal("100"))

        result = balance.subtract_amount("150")

        assert result is False
        assert balance.balance == Decimal("100")

    def test_balance_update_transfer_exact(self):
        balance = Balance(address="test_address", ticker="TEST", balance=Decimal("100"))

        result = balance.subtract_amount("100")

        assert result is True
        assert balance.balance == Decimal("0")

    def test_balance_large_amounts(self):
        balance = Balance(address="test_address", ticker="TEST", balance=Decimal("0"))

        large_amount = "999999999999999999999999999999"
        balance.add_amount(large_amount)

        assert balance.balance == Decimal(large_amount)

        subtract_amount = "111111111111111111111111111111"
        result = balance.subtract_amount(subtract_amount)

        assert result is True
        assert isinstance(balance.balance, Decimal)
        assert balance.balance > 0

    def test_balance_zero_operations(self):
        balance = Balance(address="test_address", ticker="TEST", balance=Decimal("100"))

        balance.add_amount("0")
        assert balance.balance == Decimal("100")

        result = balance.subtract_amount("0")
        assert result is True
        assert balance.balance == Decimal("100")

    def test_get_total_supply_empty(self, mock_session):
        mock_query = Mock()
        mock_query.filter_by.return_value.scalar.return_value = None
        mock_session.query.return_value = mock_query

        total_supply = Balance.get_total_supply(mock_session, "TEST")

        assert total_supply == Decimal("0")

    def test_get_total_supply_with_balances(self, mock_session):
        mock_query = Mock()
        mock_query.filter_by.return_value.scalar.return_value = Decimal("1500")
        mock_session.query.return_value = mock_query

        total_supply = Balance.get_total_supply(mock_session, "TEST")

        assert total_supply == Decimal("1500")

    def test_balance_concurrent_access(self):
        balance = Balance(address="test_address", ticker="TEST", balance=Decimal("100"))

        balance.add_amount("50")
        balance.subtract_amount("30")

        assert balance.balance == Decimal("120")

    def test_balance_decimal_amounts_only(self):
        balance = Balance(address="test_address", ticker="TEST", balance=Decimal("0"))

        assert isinstance(balance.balance, Decimal)

        balance.add_amount("100")
        assert isinstance(balance.balance, Decimal)

        balance.subtract_amount("50")
        assert isinstance(balance.balance, Decimal)

    def test_balance_decimal_amounts(self):
        balance = Balance(address="test_address", ticker="TEST", balance=Decimal("0"))

        balance.add_amount("100.5")
        assert balance.balance == Decimal("100.5")

        result = balance.subtract_amount("50.25")
        assert result is True
        assert balance.balance == Decimal("50.25")

    def test_balance_precision_handling(self):
        balance = Balance(address="test_address", ticker="TEST", balance=Decimal("0"))

        balance.add_amount("0.000000000000000001")
        assert balance.balance == Decimal("0.000000000000000001")

        balance.add_amount("0.000000000000000002")
        assert isinstance(balance.balance, Decimal)
        assert balance.balance != Decimal("0")
