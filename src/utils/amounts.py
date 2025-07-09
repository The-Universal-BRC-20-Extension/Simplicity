"""
Safe amount handling utilities for BRC-20 operations.
All amounts are handled as strings to prevent integer overflow.
"""

import re


def is_valid_amount(amount_str: str) -> bool:
    """
    Validate that amount is a positive number (integer or decimal)

    Args:
        amount_str: String representation of amount

    Returns:
        bool: True if valid, False otherwise
    """
    if not isinstance(amount_str, str):
        return False

    # Allow integers and decimals (no scientific notation)
    if not re.match(r"^[0-9]+(\.[0-9]+)?$", amount_str):
        return False

    # Check if it's positive (not zero)
    try:
        amount = float(amount_str)
        return amount > 0
    except ValueError:
        return False


def add_amounts(a: str, b: str) -> str:
    """
    Safely add two string amounts

    Args:
        a: First amount as string
        b: Second amount as string

    Returns:
        str: Sum as string

    Raises:
        ValueError: If amounts are invalid
    """
    if not is_valid_amount(a) and a != "0":
        raise ValueError(f"Invalid amount: {a}")
    if not is_valid_amount(b) and b != "0":
        raise ValueError(f"Invalid amount: {b}")

    # Use Decimal for precise arithmetic
    from decimal import Decimal, getcontext

    # Set precision high enough for large numbers
    getcontext().prec = 50

    result = Decimal(a) + Decimal(b)

    # Format without scientific notation
    return format(result, "f")


def subtract_amounts(a: str, b: str) -> str:
    """
    Safely subtract two string amounts (a - b)

    Args:
        a: Amount to subtract from
        b: Amount to subtract

    Returns:
        str: Difference as string

    Raises:
        ValueError: If amounts are invalid or result is negative
    """
    if not is_valid_amount(a) and a != "0":
        raise ValueError(f"Invalid amount: {a}")
    if not is_valid_amount(b) and b != "0":
        raise ValueError(f"Invalid amount: {b}")

    # Use Decimal for precise arithmetic
    from decimal import Decimal, getcontext

    # Set precision high enough for large numbers
    getcontext().prec = 50

    a_dec = Decimal(a)
    b_dec = Decimal(b)

    if a_dec < b_dec:
        raise ValueError(f"Insufficient amount: {a} - {b} would be negative")

    result = a_dec - b_dec
    return format(result, "f")


def compare_amounts(a: str, b: str) -> int:
    """
    Compare two string amounts

    Args:
        a: First amount
        b: Second amount

    Returns:
        int: -1 if a < b, 0 if a == b, 1 if a > b

    Raises:
        ValueError: If amounts are invalid
    """
    if not is_valid_amount(a) and a != "0":
        raise ValueError(f"Invalid amount: {a}")
    if not is_valid_amount(b) and b != "0":
        raise ValueError(f"Invalid amount: {b}")

    # Use Decimal for precise comparison
    from decimal import Decimal

    a_dec = Decimal(a)
    b_dec = Decimal(b)

    if a_dec < b_dec:
        return -1
    elif a_dec > b_dec:
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
    """Check if amount a <= b"""
    return compare_amounts(a, b) <= 0


def is_amount_equal(a: str, b: str) -> bool:
    """Check if amount a == b"""
    return compare_amounts(a, b) == 0


def normalize_amount(amount_str: str) -> str:
    """
    Normalize amount string (remove leading zeros)

    Args:
        amount_str: Amount string

    Returns:
        str: Normalized amount
    """
    if not isinstance(amount_str, str):
        raise ValueError("Amount must be string")

    # Remove leading zeros but keep at least one digit
    normalized = amount_str.lstrip("0") or "0"

    # Validate the result
    if not re.match(r"^[0-9]+$", normalized):
        raise ValueError(f"Invalid amount format: {amount_str}")

    return normalized
