"""Data validation utilities."""

from decimal import Decimal
from typing import Any


def is_amount_equal(a: Decimal, b: Decimal, tolerance: Decimal = Decimal("0.01")) -> bool:
    """Check if two amounts are equal within tolerance.

    Args:
        a: First amount
        b: Second amount
        tolerance: Maximum difference to consider equal (default $0.01)

    Returns:
        True if amounts are equal within tolerance
    """
    return abs(a - b) <= tolerance


def parse_amount(value: Any) -> Decimal:
    """Parse a value into a Decimal amount.

    Args:
        value: Value to parse (string, int, float, Decimal)

    Returns:
        Decimal amount

    Raises:
        ValueError: If value cannot be parsed
    """
    if value is None or value == "":
        return Decimal("0")

    try:
        return Decimal(str(value))
    except Exception as e:
        raise ValueError(f"Cannot parse amount: {value}") from e


def normalize_payee(payee: str) -> str:
    """Normalize payee name for consistency.

    Args:
        payee: Raw payee string

    Returns:
        Normalized payee string
    """
    if not payee:
        return ""

    # Strip whitespace
    payee = payee.strip()

    # Basic normalization (can be extended)
    return payee


def parse_tags(tags_str: str) -> list[str]:
    """Parse tags string into list of tags.

    Supports both space-separated and comma-separated tags.

    Args:
        tags_str: Tags string

    Returns:
        List of individual tags
    """
    if not tags_str:
        return []

    # Try comma separation first
    if "," in tags_str:
        tags = [t.strip() for t in tags_str.split(",")]
    else:
        # Fall back to space separation
        tags = [t.strip() for t in tags_str.split()]

    return [t for t in tags if t]


def format_tags(tags: list[str]) -> str:
    """Format list of tags into string.

    Args:
        tags: List of tags

    Returns:
        Space-separated tags string
    """
    return " ".join(tags)
