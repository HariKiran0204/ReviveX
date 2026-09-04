from __future__ import annotations

from datetime import datetime
from decimal import Decimal
from enum import StrEnum
from typing import Any

from pydantic import BaseModel, Field


class ProviderName(StrEnum):
    SIMULATOR = "SIMULATOR"


class FailureReason(StrEnum):
    TEMPORARY_BANK_ERROR = "TEMPORARY_BANK_ERROR"
    INSUFFICIENT_FUNDS = "INSUFFICIENT_FUNDS"
    EXPIRED_CARD = "EXPIRED_CARD"
    DECLINED = "DECLINED"
    NETWORK_TIMEOUT = "NETWORK_TIMEOUT"
    MANDATE_FAILURE = "MANDATE_FAILURE"
    CUSTOMER_CANCELLED = "CUSTOMER_CANCELLED"
    UNKNOWN = "UNKNOWN"


class SimulatorEventType(StrEnum):
    PAYMENT_CREATED = "payment.created"
    PAYMENT_AUTHORIZED = "payment.authorized"
    PAYMENT_CAPTURED = "payment.captured"
    PAYMENT_FAILED = "payment.failed"
    PAYMENT_REFUNDED = "payment.refunded"
    PAYMENT_CANCELLED = "payment.cancelled"


class CustomerHistory(BaseModel):
    prior_failures: int = 0
    prior_captures: int = 0
    lifetime_value: Decimal = Decimal("0.00")


class CreateOrderRequest(BaseModel):
    merchant_reference: str
    amount: Decimal
    currency: str = "INR"
    customer_reference: str | None = None
    metadata: dict[str, Any] = Field(default_factory=dict)


class CreatePaymentRequest(BaseModel):
    merchant_reference: str
    amount: Decimal
    currency: str = "INR"
    customer_reference: str | None = None
    provider_order_id: str | None = None
    attempt_number: int = 1
    customer_history: CustomerHistory = Field(default_factory=CustomerHistory)
    intended_status: str | None = None
    failure_reason: FailureReason | None = None
    metadata: dict[str, Any] = Field(default_factory=dict)


class CreatePaymentLinkRequest(BaseModel):
    merchant_reference: str
    amount: Decimal
    currency: str = "INR"
    customer_reference: str | None = None
    description: str | None = None
    metadata: dict[str, Any] = Field(default_factory=dict)


class PaymentLinkSnapshot(BaseModel):
    provider: str
    provider_payment_link_id: str
    merchant_reference: str
    amount: Decimal
    currency: str
    status: str
    url: str
    simulated: bool = True
    metadata: dict[str, Any] = Field(default_factory=dict)


class RefundPaymentRequest(BaseModel):
    provider_payment_id: str
    amount: Decimal | None = None
    merchant_reference: str | None = None


class OrderSnapshot(BaseModel):
    provider: str
    provider_order_id: str
    merchant_reference: str
    amount: Decimal
    currency: str
    status: str
    metadata: dict[str, Any] = Field(default_factory=dict)


class PaymentSnapshot(BaseModel):
    provider: str
    provider_payment_id: str
    provider_order_id: str | None = None
    merchant_reference: str
    amount: Decimal
    currency: str
    status: str
    attempt_number: int = 1
    failure_reason: FailureReason | None = None
    payment_method: str | None = "card"
    occurred_at: datetime
    metadata: dict[str, Any] = Field(default_factory=dict)


class ProviderEvent(BaseModel):
    """Provider-neutral inbound event. Payload is opaque to the domain layer."""

    provider: str
    event_id: str
    event_type: str
    occurred_at: datetime
    provider_resource_id: str
    merchant_reference: str
    payload: dict[str, Any] = Field(default_factory=dict)
    signature_valid: bool | None = True
    correlation_id: str | None = None
