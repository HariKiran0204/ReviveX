from __future__ import annotations

from datetime import datetime
from decimal import Decimal
from enum import StrEnum
from typing import Any
from uuid import UUID

from pydantic import BaseModel, Field


class DomainEventType(StrEnum):
    PAYMENT_FAILED = "PAYMENT_FAILED"
    PAYMENT_CAPTURED = "PAYMENT_CAPTURED"
    PAYMENT_REFUNDED = "PAYMENT_REFUNDED"
    PAYMENT_CANCELLED = "PAYMENT_CANCELLED"
    PAYMENT_AUTHORIZED = "PAYMENT_AUTHORIZED"
    PAYMENT_CREATED = "PAYMENT_CREATED"
    UNKNOWN = "UNKNOWN"


class DomainPaymentEvent(BaseModel):
    event_type: DomainEventType
    provider: str
    provider_event_id: str
    webhook_event_id: UUID
    merchant_id: UUID
    occurred_at: datetime
    provider_payment_id: str
    provider_order_id: str | None = None
    merchant_reference: str
    amount: Decimal
    currency: str = "INR"
    status: str
    failure_code: str | None = None
    attempt_number: int = 1
    customer_id: UUID | None = None
    customer_external_id: str | None = None
    correlation_id: str | None = None
    payment_method: str | None = None


class PaymentFailedEvent(DomainPaymentEvent):
    event_type: DomainEventType = DomainEventType.PAYMENT_FAILED


class PaymentCapturedEvent(DomainPaymentEvent):
    event_type: DomainEventType = DomainEventType.PAYMENT_CAPTURED


class PaymentRefundedEvent(DomainPaymentEvent):
    event_type: DomainEventType = DomainEventType.PAYMENT_REFUNDED


class PaymentCancelledEvent(DomainPaymentEvent):
    event_type: DomainEventType = DomainEventType.PAYMENT_CANCELLED


class UnknownDomainEvent(BaseModel):
    event_type: DomainEventType = DomainEventType.UNKNOWN
    provider: str
    provider_event_id: str
    webhook_event_id: UUID
    merchant_id: UUID
    occurred_at: datetime
    raw_event_type: str
    correlation_id: str | None = None
    payload_keys: list[str] = Field(default_factory=list)


NormalizedEvent = (
    PaymentFailedEvent
    | PaymentCapturedEvent
    | PaymentRefundedEvent
    | PaymentCancelledEvent
    | DomainPaymentEvent
    | UnknownDomainEvent
)

EVENT_TYPE_MAP: dict[str, DomainEventType] = {
    "payment.failed": DomainEventType.PAYMENT_FAILED,
    "payment.captured": DomainEventType.PAYMENT_CAPTURED,
    "payment.refunded": DomainEventType.PAYMENT_REFUNDED,
    "payment.cancelled": DomainEventType.PAYMENT_CANCELLED,
    "payment.authorized": DomainEventType.PAYMENT_AUTHORIZED,
    "payment.created": DomainEventType.PAYMENT_CREATED,
    "PAYMENT_FAILED": DomainEventType.PAYMENT_FAILED,
    "PAYMENT_CAPTURED": DomainEventType.PAYMENT_CAPTURED,
    "PAYMENT_REFUNDED": DomainEventType.PAYMENT_REFUNDED,
    "PAYMENT_CANCELLED": DomainEventType.PAYMENT_CANCELLED,
}


def payload_str(payload: dict[str, Any], *keys: str) -> str | None:
    for key in keys:
        value = payload.get(key)
        if value is not None and str(value).strip():
            return str(value)
    return None
