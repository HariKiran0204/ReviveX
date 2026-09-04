from __future__ import annotations

from datetime import datetime
from decimal import Decimal
from typing import Any
from uuid import UUID

from recoverai_domain.errors import IngestionError
from recoverai_domain.events import (
    EVENT_TYPE_MAP,
    DomainPaymentEvent,
    UnknownDomainEvent,
    payload_str,
)
from recoverai_providers.models import ProviderEvent


def _require_decimal(payload: dict[str, Any], amount_fallback: str | None = None) -> Decimal:
    raw = payload.get("amount", amount_fallback)
    if raw is None:
        raise IngestionError("INVALID_PROVIDER_EVENT", "amount is required to normalize this event")
    try:
        return Decimal(str(raw))
    except Exception as exc:
        raise IngestionError("INVALID_PROVIDER_EVENT", "amount must be a decimal value") from exc


def _optional_uuid(value: object) -> UUID | None:
    if value is None or value == "":
        return None
    try:
        return UUID(str(value))
    except ValueError as exc:
        raise IngestionError("INVALID_PROVIDER_EVENT", "customer_id must be a UUID") from exc


def normalize_provider_event(
    event: ProviderEvent,
    *,
    webhook_event_id: UUID,
    merchant_id: UUID,
) -> DomainPaymentEvent | UnknownDomainEvent:
    domain_type = EVENT_TYPE_MAP.get(event.event_type)
    if domain_type is None:
        return UnknownDomainEvent(
            provider=event.provider,
            provider_event_id=event.event_id,
            webhook_event_id=webhook_event_id,
            merchant_id=merchant_id,
            occurred_at=event.occurred_at,
            raw_event_type=event.event_type,
            correlation_id=event.correlation_id,
            payload_keys=sorted(event.payload.keys()),
        )

    payload = event.payload
    provider_payment_id = (
        payload_str(payload, "provider_payment_id", "payment_id") or event.provider_resource_id
    )
    if not provider_payment_id:
        raise IngestionError("INVALID_PAYMENT_REFERENCE", "provider payment id is required")

    amount = _require_decimal(payload)
    currency = payload_str(payload, "currency") or "INR"
    status = payload_str(payload, "status") or domain_type.value
    attempt_raw = payload.get("attempt_number", 1)
    try:
        attempt_number = int(attempt_raw)
    except (TypeError, ValueError) as exc:
        raise IngestionError("INVALID_PROVIDER_EVENT", "attempt_number must be an integer") from exc

    occurred_at: datetime = event.occurred_at
    return DomainPaymentEvent(
        event_type=domain_type,
        provider=event.provider,
        provider_event_id=event.event_id,
        webhook_event_id=webhook_event_id,
        merchant_id=merchant_id,
        occurred_at=occurred_at,
        provider_payment_id=provider_payment_id,
        provider_order_id=payload_str(payload, "provider_order_id", "order_id"),
        merchant_reference=event.merchant_reference,
        amount=amount,
        currency=currency,
        status=status,
        failure_code=payload_str(payload, "failure_reason", "failure_code"),
        attempt_number=attempt_number,
        customer_id=_optional_uuid(payload.get("customer_id")),
        customer_external_id=payload_str(payload, "customer_external_id"),
        correlation_id=event.correlation_id,
        payment_method=payload_str(payload, "payment_method"),
    )
