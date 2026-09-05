from __future__ import annotations

from decimal import Decimal
from typing import Any

from sqlalchemy import Numeric

MONEY_PRECISION = Numeric(18, 2)
JsonDict = dict[str, Any]


def validate_non_negative_money(value: Decimal, field_name: str) -> Decimal:
    if value < 0:
        raise ValueError(f"{field_name} must be non-negative")
    return value
