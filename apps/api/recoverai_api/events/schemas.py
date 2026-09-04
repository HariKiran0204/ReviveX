from __future__ import annotations

from datetime import datetime
from decimal import Decimal
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field


class SimulatorWebhookRequest(BaseModel):
    event_id: str | None = None
    event_type: str
    occurred_at: datetime | None = None
    provider_resource_id: str | None = None
    provider_payment_id: str | None = None
    provider_order_id: str | None = None
    merchant_slug: str | None = None
    merchant_id: UUID | None = None
    merchant_reference: str | None = None
    customer_id: UUID | None = None
    customer_external_id: str | None = None
    amount: Decimal | None = None
    currency: str = "INR"
    status: str | None = None
    failure_reason: str | None = None
    attempt_number: int = 1
    payment_method: str | None = "card"
    correlation_id: str | None = None
    payload: dict[str, object] = Field(default_factory=dict)


class IngestAcknowledgement(BaseModel):
    accepted: bool
    duplicate: bool
    queued: bool
    event_id: str
    webhook_event_id: UUID
    status: str
    merchant_id: UUID
    correlation_id: str | None = None


class SimulationEventRequest(BaseModel):
    event_type: str = "payment.failed"
    failure_reason: str | None = "TEMPORARY_BANK_ERROR"
    amount: Decimal = Decimal("499.00")
    currency: str = "INR"
    merchant_slug: str | None = None
    merchant_id: UUID | None = None
    customer_id: UUID | None = None
    customer_external_id: str | None = None
    seed: int | None = None
    intended_status: str | None = None
    attempt_number: int = 1
    correlation_id: str | None = None


class SimulationScenarioRequest(BaseModel):
    scenario: str
    seed: int | None = None
    merchant_slug: str | None = None
    amount: Decimal | None = None


class EventSummary(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: UUID
    merchant_id: UUID
    provider: str
    event_id: str
    event_type: str
    status: str
    received_at: datetime
    processed_at: datetime | None
    correlation_id: str | None
    error_code: str | None = None


class EventListResponse(BaseModel):
    events: list[EventSummary]
