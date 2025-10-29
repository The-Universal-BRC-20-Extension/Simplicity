"""
Safe amount handling utilities for BRC-20 operations.
All amounts are handled as Decimal to prevent integer overflow and ensure precision.
"""

import re
from decimal import Decimal, getcontext
from typing import Union

getcontext().prec = 50


def is_valid_amount(amount: Union[str, Decimal]) -> bool:
    """Validate that amount is a positive number (integer or decimal)"""
    if isinstance(amount, Decimal):
        return amount > 0

    if not isinstance(amount, str):
        return False

    if not re.match(r"^[0-9]+(\.[0-9]+)?$", amount):
        return False

    try:
        amount_float = float(amount)
        return amount_float > 0
    except ValueError:
        return False


def add_amounts(a: Union[str, Decimal], b: Union[str, Decimal]) -> Decimal:
    """Safely add two amounts"""
    a_decimal = Decimal(str(a)) if not isinstance(a, Decimal) else a
    b_decimal = Decimal(str(b)) if not isinstance(b, Decimal) else b

    if not is_valid_amount(a_decimal) and a_decimal != Decimal("0"):
        raise ValueError(f"Invalid amount: {a}")
    if not is_valid_amount(b_decimal) and b_decimal != Decimal("0"):
        raise ValueError(f"Invalid amount: {b}")

    result = a_decimal + b_decimal
    return result


def subtract_amounts(a: Union[str, Decimal], b: Union[str, Decimal]) -> Decimal:
    """Safely subtract two amounts

    Raises:
        ValueError: If amounts are invalid or result is negative
    """
    a_decimal = Decimal(str(a)) if not isinstance(a, Decimal) else a
    b_decimal = Decimal(str(b)) if not isinstance(b, Decimal) else b

    if not is_valid_amount(a_decimal) and a_decimal != Decimal("0"):
        raise ValueError(f"Invalid amount: {a}")
    if not is_valid_amount(b_decimal) and b_decimal != Decimal("0"):
        raise ValueError(f"Invalid amount: {b}")

    if a_decimal < b_decimal:
        raise ValueError(f"Insufficient amount: {a} - {b} would be negative")

    result = a_decimal - b_decimal
    return result


def compare_amounts(a: Union[str, Decimal], b: Union[str, Decimal]) -> int:
    a_decimal = Decimal(str(a)) if not isinstance(a, Decimal) else a
    b_decimal = Decimal(str(b)) if not isinstance(b, Decimal) else b

    if not is_valid_amount(a_decimal) and a_decimal != Decimal("0"):
        raise ValueError(f"Invalid amount: {a}")
    if not is_valid_amount(b_decimal) and b_decimal != Decimal("0"):
        raise ValueError(f"Invalid amount: {b}")

    if a_decimal < b_decimal:
        return -1
    elif a_decimal > b_decimal:
        return 1
    else:
        return 0


def is_amount_greater_than(a: str, b: str) -> bool:
    """Check if amount a > b"""
    return compare_amounts(a, b) > 0


def is_amount_greater_equal(a: str, b: str) -> bool:
    """Check if amount a >= b"""
    return compare_amounts(a, b) >= 0


def is_amount_less_than(a: str, b: str) -> bool:
    """Check if amount a < b"""
    return compare_amounts(a, b) < 0


def is_amount_less_equal(a: str, b: str) -> bool:
    return compare_amounts(a, b) <= 0


def is_amount_equal(a: str, b: str) -> bool:
    """Check if amount a == b"""
    return compare_amounts(a, b) == 0


def normalize_amount(amount: Union[str, Decimal]) -> str:
    if isinstance(amount, Decimal):
        return format(amount, "f").rstrip("0").rstrip(".")

    if not isinstance(amount, str):
        raise ValueError("Amount must be string or Decimal")

    normalized = amount.lstrip("0") or "0"

    if not re.match(r"^[0-9]+$", normalized):
        raise ValueError(f"Invalid amount format: {amount}")

    return normalized


"""Compatibility functions for backward compatibility"""


def add_amounts_str(a: str, b: str) -> str:
    result = add_amounts(a, b)
    return format(result, "f").rstrip("0").rstrip(".")


def subtract_amounts_str(a: str, b: str) -> str:
    result = subtract_amounts(a, b)
    return format(result, "f").rstrip("0").rstrip(".")


def compare_amounts_str(a: str, b: str) -> int:
    return compare_amounts(a, b)
