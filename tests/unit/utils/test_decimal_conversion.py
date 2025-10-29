"""
Unit tests for decimal conversion utilities
"""

from decimal import Decimal
from src.utils.decimal_conversion import (
    to_decimal,
    to_string,
    normalize_decimal,
    validate_decimal_amount,
    format_decimal_for_db,
    format_decimal_for_api,
    migrate_string_to_decimal,
    migrate_decimal_to_string,
)


class TestDecimalConversion:

    def test_to_decimal_with_string(self):
        assert to_decimal("123.456") == Decimal("123.456")
        assert to_decimal("0") == Decimal("0")
        assert to_decimal("") == Decimal("0")
        assert to_decimal(None) is None

    def test_to_decimal_with_decimal(self):
        decimal_value = Decimal("123.456")
        assert to_decimal(decimal_value) == decimal_value

    def test_to_string_with_decimal(self):
        assert to_string(Decimal("123.456")) == "123.456"
        assert to_string(Decimal("0")) == "0"
        assert to_string(None) is None

    def test_to_string_with_string(self):
        assert to_string("123.456") == "123.456"

    def test_normalize_decimal(self):
        assert normalize_decimal(Decimal("123.456789")) == Decimal("123.45678900")
        assert normalize_decimal("123.456") == Decimal("123.45600000")
        assert normalize_decimal(None) is None

    def test_validate_decimal_amount(self):
        assert validate_decimal_amount(Decimal("123.456")) is True
        assert validate_decimal_amount("123.456") is True
        assert validate_decimal_amount(Decimal("0")) is False
        assert validate_decimal_amount("-123.456") is False
        assert validate_decimal_amount(None) is False
        assert validate_decimal_amount("invalid") is False

    def test_format_decimal_for_db(self):
        assert format_decimal_for_db(Decimal("123.456789")) == Decimal("123.45678900")
        assert format_decimal_for_db("123.456") == Decimal("123.45600000")

    def test_format_decimal_for_api(self):
        assert format_decimal_for_api(Decimal("123.456789")) == "123.456789"
        assert format_decimal_for_api(Decimal("123.456000")) == "123.456"

    def test_migrate_string_to_decimal(self):
        assert migrate_string_to_decimal("123.456") == Decimal("123.456")
        assert migrate_string_to_decimal("") == Decimal("0")
        assert migrate_string_to_decimal("invalid") == Decimal("0")

    def test_migrate_decimal_to_string(self):
        assert migrate_decimal_to_string(Decimal("123.456789")) == "123.456789"
        assert migrate_decimal_to_string(Decimal("0")) == "0"
        assert migrate_decimal_to_string(None) == "0"

    def test_edge_cases(self):
        # Large numbers
        large_decimal = Decimal("999999999999999999.12345678")
        assert to_decimal(str(large_decimal)) == large_decimal

        # Zero handling
        assert to_decimal("0") == Decimal("0")
        assert to_decimal("0.0") == Decimal("0.0")

        # None handling
        assert to_decimal(None) is None
        assert to_string(None) is None
