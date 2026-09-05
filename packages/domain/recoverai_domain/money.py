from __future__ import annotations

from decimal import ROUND_HALF_EVEN, Decimal

MONEY_QUANTUM = Decimal("0.01")
ZERO = Decimal("0.00")


def as_money(value: Decimal) -> Decimal:
    if not isinstance(value, Decimal):
        raise TypeError("money values must be Decimal")
    quantized = value.quantize(MONEY_QUANTUM, rounding=ROUND_HALF_EVEN)
    if quantized < ZERO:
        raise ValueError("money values must be >= 0")
    return quantized


def signed_money(value: Decimal) -> Decimal:
    """Quantize a financial value that may be negative (for example ERV)."""
    if not isinstance(value, Decimal):
        raise TypeError("money values must be Decimal")
    return value.quantize(MONEY_QUANTUM, rounding=ROUND_HALF_EVEN)
