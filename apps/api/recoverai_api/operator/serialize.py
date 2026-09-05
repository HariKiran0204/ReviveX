from __future__ import annotations

from datetime import datetime
from decimal import Decimal
from typing import Any
from uuid import UUID

from recoverai_domain.agents.security import strip_secrets


def money(value: Decimal | None) -> str | None:
    if value is None:
        return None
    return f"{value:.2f}"


def iso(value: datetime | None) -> str | None:
    if value is None:
        return None
    return value.isoformat()


def as_str(value: UUID | None) -> str | None:
    if value is None:
        return None
    return str(value)


def public_json(payload: dict[str, Any] | None) -> dict[str, Any] | None:
    if payload is None:
        return None
    return strip_secrets(payload)
