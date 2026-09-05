from __future__ import annotations

from dataclasses import dataclass, field
from decimal import Decimal
from enum import StrEnum
from uuid import UUID

from pydantic import BaseModel, Field


class MismatchReason(StrEnum):
    MERCHANT_MISMATCH = "MERCHANT_MISMATCH"
    CUSTOMER_MISMATCH = "CUSTOMER_MISMATCH"
    ORDER_MISMATCH = "ORDER_MISMATCH"
    PAYMENT_MISMATCH = "PAYMENT_MISMATCH"
    AMOUNT_MISMATCH = "AMOUNT_MISMATCH"
    CURRENCY_MISMATCH = "CURRENCY_MISMATCH"
    OUTSIDE_RECOVERY_WINDOW = "OUTSIDE_RECOVERY_WINDOW"
    ALREADY_COUNTED = "ALREADY_COUNTED"
    DUPLICATE_EVENT = "DUPLICATE_EVENT"
    NOT_CAPTURED = "NOT_CAPTURED"
    UNKNOWN = "UNKNOWN"


class RecoveryMatchResult(BaseModel):
    matched: bool
    case_id: UUID
    payment_id: UUID | None = None
    amount_recovered: Decimal = Field(default=Decimal("0.00"))
    currency: str = "INR"
    reasons: list[str] = Field(default_factory=list)
    mismatch_reason: MismatchReason | None = None
    remaining_exposure: Decimal = Field(default=Decimal("0.00"))
    capped_overpayment: Decimal = Field(default=Decimal("0.00"))

    def to_public_dict(self) -> dict[str, str | bool | list[str] | None]:
        payload: dict[str, str | bool | list[str] | None] = {
            "matched": self.matched,
            "case_id": str(self.case_id),
            "amount_recovered": str(self.amount_recovered),
            "currency": self.currency,
        }
        if self.payment_id is not None:
            payload["payment_id"] = str(self.payment_id)
        if self.matched:
            payload["reasons"] = list(self.reasons)
        else:
            payload["mismatch_reason"] = str(self.mismatch_reason) if self.mismatch_reason else None
        return payload


@dataclass(frozen=True)
class FollowUpJob:
    name: str
    case_id: UUID
    payment_id: UUID | None = None
    webhook_event_id: UUID | None = None
    extra: dict[str, str] = field(default_factory=dict)

    def as_dict(self) -> dict[str, str]:
        payload = {"name": self.name, "case_id": str(self.case_id)}
        if self.payment_id is not None:
            payload["payment_id"] = str(self.payment_id)
        if self.webhook_event_id is not None:
            payload["webhook_event_id"] = str(self.webhook_event_id)
        payload.update(self.extra)
        return payload
