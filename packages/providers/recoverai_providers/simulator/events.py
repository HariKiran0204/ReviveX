from __future__ import annotations

import hashlib
from datetime import UTC, datetime

from recoverai_db.enums import PaymentStatus
from recoverai_providers.models import (
    PaymentSnapshot,
    ProviderEvent,
    ProviderName,
    SimulatorEventType,
)

_STATUS_TO_EVENT: dict[str, SimulatorEventType] = {
    PaymentStatus.CREATED: SimulatorEventType.PAYMENT_CREATED,
    PaymentStatus.AUTHORIZED: SimulatorEventType.PAYMENT_AUTHORIZED,
    PaymentStatus.CAPTURED: SimulatorEventType.PAYMENT_CAPTURED,
    PaymentStatus.FAILED: SimulatorEventType.PAYMENT_FAILED,
    PaymentStatus.REFUNDED: SimulatorEventType.PAYMENT_REFUNDED,
    PaymentStatus.CANCELLED: SimulatorEventType.PAYMENT_CANCELLED,
}


def event_type_for_status(status: str) -> str:
    mapped = _STATUS_TO_EVENT.get(status)
    if mapped is None:
        return f"payment.{status.lower()}"
    return str(mapped)


def deterministic_event_id(
    seed: int,
    provider_payment_id: str,
    event_type: str,
    attempt_number: int,
) -> str:
    material = f"{seed}:{provider_payment_id}:{event_type}:{attempt_number}"
    digest = hashlib.sha256(material.encode("utf-8")).hexdigest()[:20]
    return f"evt_sim_{digest}"


def deterministic_payment_id(seed: int, merchant_reference: str, sequence: int) -> str:
    material = f"{seed}:pay:{merchant_reference}:{sequence}"
    digest = hashlib.sha256(material.encode("utf-8")).hexdigest()[:16]
    return f"pay_sim_{digest}"


def deterministic_order_id(seed: int, merchant_reference: str, sequence: int) -> str:
    material = f"{seed}:order:{merchant_reference}:{sequence}"
    digest = hashlib.sha256(material.encode("utf-8")).hexdigest()[:16]
    return f"order_sim_{digest}"


def deterministic_payment_link_id(seed: int, merchant_reference: str, sequence: int) -> str:
    material = f"{seed}:plink:{merchant_reference}:{sequence}"
    digest = hashlib.sha256(material.encode("utf-8")).hexdigest()[:16]
    return f"plink_sim_{digest}"


def build_provider_event(
    snapshot: PaymentSnapshot,
    *,
    seed: int,
    correlation_id: str | None = None,
    extra_payload: dict[str, object] | None = None,
    occurred_at: datetime | None = None,
    event_type: str | None = None,
) -> ProviderEvent:
    resolved_type = event_type or event_type_for_status(snapshot.status)
    payload: dict[str, object] = {
        "provider_payment_id": snapshot.provider_payment_id,
        "provider_order_id": snapshot.provider_order_id,
        "amount": str(snapshot.amount),
        "currency": snapshot.currency,
        "status": snapshot.status,
        "attempt_number": snapshot.attempt_number,
        "failure_reason": str(snapshot.failure_reason)
        if snapshot.failure_reason is not None
        else None,
        "payment_method": snapshot.payment_method,
        "merchant_reference": snapshot.merchant_reference,
        "occurred_at": (occurred_at or datetime.now(UTC)).isoformat(),
    }
    if extra_payload:
        payload.update(extra_payload)
    return ProviderEvent(
        provider=ProviderName.SIMULATOR,
        event_id=deterministic_event_id(
            seed,
            snapshot.provider_payment_id,
            resolved_type,
            snapshot.attempt_number,
        ),
        event_type=resolved_type,
        occurred_at=occurred_at or datetime.now(UTC),
        provider_resource_id=snapshot.provider_payment_id,
        merchant_reference=snapshot.merchant_reference,
        payload=payload,
        signature_valid=True,
        correlation_id=correlation_id,
    )
