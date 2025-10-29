"""
Decimal conversion utilities for BRC-20 amounts.
Provides conversion functions between String and Decimal representations.
"""

from decimal import Decimal, getcontext
from typing import Union, Optional

getcontext().prec = 50

# Default scale for BRC-20 amounts (8 decimal places)
DEFAULT_SCALE = 8


def to_decimal(amount: Union[str, Decimal, None]) -> Optional[Decimal]:
    if amount is None:
        return None

    if isinstance(amount, Decimal):
        return amount

    if isinstance(amount, str):
        amount = amount.strip()
        if not amount or amount == "":
            return Decimal("0")
        try:
            return Decimal(amount)
        except (ValueError, TypeError, OverflowError, Exception):
            return None

    try:
        return Decimal(str(amount))
    except (ValueError, TypeError, OverflowError, Exception):
        return None


def to_string(amount: Union[str, Decimal, None]) -> Optional[str]:
    if amount is None:
        return None

    if isinstance(amount, str):
        return amount

    if isinstance(amount, Decimal):
        return format(amount, f".{DEFAULT_SCALE}f").rstrip("0").rstrip(".")

    return str(amount)


def normalize_decimal(amount: Union[str, Decimal, None]) -> Optional[Decimal]:
    decimal_amount = to_decimal(amount)
    if decimal_amount is None:
        return None

    # Round to proper scale
    return decimal_amount.quantize(Decimal(f'0.{"0" * DEFAULT_SCALE}'))


def validate_decimal_amount(amount: Union[str, Decimal, None]) -> bool:
    try:
        decimal_amount = to_decimal(amount)
        if decimal_amount is None:
            return False
        return decimal_amount > 0
    except (ValueError, TypeError, OverflowError, Exception):
        return False


def format_decimal_for_db(amount: Union[str, Decimal, None]) -> Optional[Decimal]:
    return normalize_decimal(amount)


def format_decimal_for_api(amount: Union[str, Decimal, None]) -> Optional[str]:
    return to_string(amount)


"""Migration helper functions"""


def migrate_string_to_decimal(amount_str: str) -> Decimal:
    if not amount_str or amount_str == "":
        return Decimal("0")

    try:
        return Decimal(amount_str)
    except (ValueError, TypeError, OverflowError, Exception):
        return Decimal("0")


def migrate_decimal_to_string(amount_decimal: Decimal) -> str:
    if amount_decimal is None:
        return "0"

    return format(amount_decimal, f".{DEFAULT_SCALE}f").rstrip("0").rstrip(".")
