from __future__ import annotations

from datetime import UTC, datetime
from decimal import Decimal
from uuid import UUID

from sqlalchemy.orm import Session

from recoverai_api.config import Settings
from recoverai_db.models import WebhookEvent
from recoverai_db.repositories import MerchantRepository
from recoverai_domain.errors import IngestionError
from recoverai_domain.fixtures import (
    LEGACY_SIMULATOR_MERCHANT_SLUG,
    SIMULATOR_MERCHANT_SLUG,
    ensure_simulator_fixtures,
)
from recoverai_domain.ingestion import EventIngestionService, EventQueue, IngestResult
from recoverai_domain.processing import provider_event_from_row
from recoverai_providers.models import (
    CreatePaymentRequest,
    FailureReason,
    ProviderEvent,
    ProviderName,
)
from recoverai_providers.registry import get_payment_provider
from recoverai_providers.simulator.events import build_provider_event

ingestion = EventIngestionService()

KNOWN_PAYMENT_EVENT_TYPES = {
    "payment.created",
    "payment.authorized",
    "payment.captured",
    "payment.failed",
    "payment.refunded",
    "payment.cancelled",
}


_DEMO_SLUGS = {SIMULATOR_MERCHANT_SLUG, LEGACY_SIMULATOR_MERCHANT_SLUG}


def resolve_merchant_id(
    session: Session,
    *,
    merchant_id: UUID | None,
    merchant_slug: str | None,
    allow_fixture: bool,
) -> UUID:
    merchants = MerchantRepository(session)
    if merchant_id is not None:
        merchant = merchants.get_merchant(merchant_id)
        if merchant is None:
            raise IngestionError("MISSING_MERCHANT", "Merchant was not found", http_status=404)
        return merchant.id
    if merchant_slug:
        if allow_fixture and merchant_slug in _DEMO_SLUGS:
            merchant, _customer = ensure_simulator_fixtures(session)
            return merchant.id
        merchant = merchants.get_by_slug(merchant_slug)
        if merchant is None:
            raise IngestionError(
                "MISSING_MERCHANT", f"Merchant slug {merchant_slug} was not found", http_status=404
            )
        return merchant.id
    if allow_fixture:
        merchant, _customer = ensure_simulator_fixtures(session)
        return merchant.id
    raise IngestionError("MISSING_MERCHANT", "merchant_id or merchant_slug is required")


def resolve_webhook_parties(
    session: Session,
    *,
    merchant_id: UUID | None,
    merchant_slug: str | None,
    customer_id: UUID | None,
    customer_external_id: str | None,
) -> tuple[UUID, UUID | None, str | None]:
    """Simulator webhooks may omit merchant and use the demo fixture."""
    if merchant_id is None and not merchant_slug:
        merchant, customer = ensure_simulator_fixtures(session)
        return (
            merchant.id,
            customer_id or customer.id,
            customer_external_id or customer.external_id,
        )
    resolved_merchant_id = resolve_merchant_id(
        session,
        merchant_id=merchant_id,
        merchant_slug=merchant_slug,
        allow_fixture=bool(merchant_slug and merchant_slug in _DEMO_SLUGS),
    )
    return resolved_merchant_id, customer_id, customer_external_id


def resolve_simulation_parties(
    session: Session,
    *,
    merchant_id: UUID | None,
    merchant_slug: str | None,
    customer_id: UUID | None,
    customer_external_id: str | None,
) -> tuple[UUID, UUID | None, str | None]:
    """Resolve merchant/customer for demo generation without requiring seed.py."""
    demo_merchant, demo_customer = ensure_simulator_fixtures(session)
    if merchant_id is None and not merchant_slug:
        return (
            demo_merchant.id,
            customer_id or demo_customer.id,
            customer_external_id or demo_customer.external_id,
        )
    resolved_merchant_id = resolve_merchant_id(
        session,
        merchant_id=merchant_id,
        merchant_slug=merchant_slug,
        allow_fixture=merchant_slug in _DEMO_SLUGS if merchant_slug else True,
    )
    if customer_id is not None or customer_external_id:
        return resolved_merchant_id, customer_id, customer_external_id
    if resolved_merchant_id == demo_merchant.id:
        return resolved_merchant_id, demo_customer.id, demo_customer.external_id
    raise IngestionError(
        "MISSING_CUSTOMER",
        "customer_id or customer_external_id is required for a non-demo merchant",
        http_status=400,
    )


def webhook_to_provider_event(
    *,
    event_id: str | None,
    event_type: str,
    merchant_id: UUID,
    provider_resource_id: str | None = None,
    provider_payment_id: str | None = None,
    provider_order_id: str | None = None,
    merchant_reference: str | None = None,
    customer_id: UUID | None = None,
    customer_external_id: str | None = None,
    amount: Decimal | None = None,
    currency: str = "INR",
    status: str | None = None,
    failure_reason: str | None = None,
    attempt_number: int = 1,
    payment_method: str | None = "card",
    correlation_id: str | None = None,
    payload: dict[str, object] | None = None,
    occurred_at: datetime | None = None,
) -> ProviderEvent:
    if not event_type or not event_type.strip():
        raise IngestionError("INVALID_PROVIDER_EVENT", "event_type is required")
    if event_id is None or not event_id.strip():
        raise IngestionError("INVALID_PROVIDER_EVENT", "event_id is required")
    resource_id = provider_resource_id or provider_payment_id
    if resource_id is None and event_type.strip() in KNOWN_PAYMENT_EVENT_TYPES:
        raise IngestionError("INVALID_PAYMENT_REFERENCE", "provider_resource_id is required")

    merged: dict[str, object] = dict(payload or {})
    merged.update(
        {
            "provider_payment_id": resource_id,
            "provider_order_id": provider_order_id,
            "amount": str(amount) if amount is not None else merged.get("amount"),
            "currency": currency,
            "status": status,
            "failure_reason": failure_reason,
            "attempt_number": attempt_number,
            "payment_method": payment_method,
            "customer_id": str(customer_id) if customer_id else None,
            "customer_external_id": customer_external_id,
            "merchant_id": str(merchant_id),
            "merchant_reference": merchant_reference or str(merchant_id),
            "occurred_at": (occurred_at or datetime.now(UTC)).isoformat(),
        }
    )
    cleaned = {key: value for key, value in merged.items() if value is not None}
    if (
        event_type in {"payment.failed", "payment.captured", "payment.refunded"}
        and "amount" not in cleaned
    ):
        raise IngestionError("INVALID_PROVIDER_EVENT", "amount is required")

    return ProviderEvent(
        provider=ProviderName.SIMULATOR,
        event_id=event_id.strip(),
        event_type=event_type.strip(),
        occurred_at=occurred_at or datetime.now(UTC),
        provider_resource_id=resource_id or "",
        merchant_reference=str(cleaned.get("merchant_reference") or merchant_id),
        payload=cleaned,
        signature_valid=True,
        correlation_id=correlation_id,
    )


def ingest_simulated_payment(
    session: Session,
    queue: EventQueue,
    *,
    merchant_id: UUID,
    customer_id: UUID | None,
    customer_external_id: str | None,
    amount: Decimal,
    currency: str,
    seed: int,
    event_type: str,
    failure_reason: str | None,
    intended_status: str | None,
    attempt_number: int,
    correlation_id: str | None,
    provider_payment_id: str | None = None,
) -> IngestResult:
    failure: FailureReason | None = None
    if failure_reason:
        try:
            failure = FailureReason(failure_reason)
        except ValueError as exc:
            raise IngestionError("INVALID_PROVIDER_EVENT", "Unknown failure_reason") from exc

    provider = get_payment_provider(ProviderName.SIMULATOR, seed=seed)
    snapshot = provider.create_payment(
        CreatePaymentRequest(
            merchant_reference=str(merchant_id),
            amount=amount,
            currency=currency,
            customer_reference=str(customer_id or customer_external_id or ""),
            attempt_number=attempt_number,
            intended_status=intended_status,
            failure_reason=failure,
        )
    )
    if provider_payment_id:
        snapshot = snapshot.model_copy(update={"provider_payment_id": provider_payment_id})
    extra: dict[str, object] = {"merchant_id": str(merchant_id)}
    if customer_id is not None:
        extra["customer_id"] = str(customer_id)
    if customer_external_id:
        extra["customer_external_id"] = customer_external_id
    event = build_provider_event(
        snapshot,
        seed=seed,
        correlation_id=correlation_id,
        extra_payload=extra,
        event_type=event_type,
    )
    return ingestion.ingest(
        session,
        event,
        merchant_id=merchant_id,
        queue=queue,
        request_id=correlation_id,
    )


def run_scenario(
    session: Session,
    queue: EventQueue,
    *,
    scenario: str,
    settings: Settings,
    merchant_slug: str | None,
    seed: int | None,
    amount: Decimal | None,
) -> list[IngestResult]:
    resolved_seed = seed if seed is not None else settings.simulation_seed
    merchant_id, customer_id, customer_external_id = resolve_simulation_parties(
        session,
        merchant_id=None,
        merchant_slug=merchant_slug,
        customer_id=None,
        customer_external_id=None,
    )
    resolved_amount = amount or Decimal("499.00")
    key = scenario.strip().upper()

    def emit(
        *,
        event_type: str,
        intended_status: str,
        failure_reason: str | None,
        event_seed: int,
        provider_payment_id: str | None = None,
    ) -> IngestResult:
        return ingest_simulated_payment(
            session,
            queue,
            merchant_id=merchant_id,
            customer_id=customer_id,
            customer_external_id=customer_external_id,
            amount=resolved_amount,
            currency="INR",
            seed=event_seed,
            event_type=event_type,
            failure_reason=failure_reason,
            intended_status=intended_status,
            attempt_number=1,
            correlation_id=None,
            provider_payment_id=provider_payment_id,
        )

    if key in {"A", "SCENARIO_A"}:
        return [
            emit(
                event_type="payment.failed",
                intended_status="FAILED",
                failure_reason="TEMPORARY_BANK_ERROR",
                event_seed=resolved_seed,
            )
        ]
    if key in {"B", "SCENARIO_B"}:
        first = emit(
            event_type="payment.failed",
            intended_status="FAILED",
            failure_reason="TEMPORARY_BANK_ERROR",
            event_seed=resolved_seed,
        )
        row = session.get(WebhookEvent, first.webhook_event_id)
        if row is None:
            raise IngestionError("INVALID_PROVIDER_EVENT", "Scenario B source event missing")
        second = ingestion.ingest(
            session,
            provider_event_from_row(row),
            merchant_id=merchant_id,
            queue=queue,
        )
        return [first, second]
    if key in {"C", "SCENARIO_C"}:
        failed = emit(
            event_type="payment.failed",
            intended_status="FAILED",
            failure_reason="TEMPORARY_BANK_ERROR",
            event_seed=resolved_seed,
        )
        row = session.get(WebhookEvent, failed.webhook_event_id)
        provider_payment_id = None
        if row is not None:
            raw = row.payload.get("provider_payment_id")
            provider_payment_id = str(raw) if raw else None
        captured = emit(
            event_type="payment.captured",
            intended_status="CAPTURED",
            failure_reason=None,
            event_seed=resolved_seed + 1,
            provider_payment_id=provider_payment_id,
        )
        return [failed, captured]
    if key in {"E", "SCENARIO_E"}:
        return [
            emit(
                event_type="payment.unknown_custom_type",
                intended_status="FAILED",
                failure_reason="UNKNOWN",
                event_seed=resolved_seed,
            )
        ]
    if key in {"G", "VALID_RECOVERY"}:
        failed = emit(
            event_type="payment.failed",
            intended_status="FAILED",
            failure_reason="TEMPORARY_BANK_ERROR",
            event_seed=resolved_seed,
        )
        row = session.get(WebhookEvent, failed.webhook_event_id)
        provider_payment_id = None
        provider_order_id = None
        if row is not None:
            raw = row.payload.get("provider_payment_id")
            provider_payment_id = str(raw) if raw else None
            order_raw = row.payload.get("provider_order_id")
            provider_order_id = str(order_raw) if order_raw else None
        captured = _ingest_explicit(
            session,
            queue,
            merchant_id=merchant_id,
            customer_id=customer_id,
            amount=resolved_amount,
            event_id=f"evt_valid_capture_{resolved_seed}",
            provider_payment_id=provider_payment_id or f"pay_sim_valid_{resolved_seed}",
            provider_order_id=provider_order_id,
            event_type="payment.captured",
            status="CAPTURED",
        )
        return [failed, captured]
    if key in {"H", "WRONG_ORDER"}:
        failed = _ingest_explicit(
            session,
            queue,
            merchant_id=merchant_id,
            customer_id=customer_id,
            amount=resolved_amount,
            event_id=f"evt_wrong_order_fail_{resolved_seed}",
            provider_payment_id=f"pay_sim_order_a_{resolved_seed}",
            provider_order_id=f"order_sim_a_{resolved_seed}",
            event_type="payment.failed",
            status="FAILED",
            failure_reason="TEMPORARY_BANK_ERROR",
        )
        captured = _ingest_explicit(
            session,
            queue,
            merchant_id=merchant_id,
            customer_id=customer_id,
            amount=resolved_amount,
            event_id=f"evt_wrong_order_cap_{resolved_seed}",
            provider_payment_id=f"pay_sim_order_b_{resolved_seed}",
            provider_order_id=f"order_sim_b_{resolved_seed}",
            event_type="payment.captured",
            status="CAPTURED",
        )
        return [failed, captured]
    if key in {"I", "WRONG_CUSTOMER"}:
        from recoverai_domain.fixtures import ensure_alt_simulator_customer

        alt = ensure_alt_simulator_customer(session)
        failed = _ingest_explicit(
            session,
            queue,
            merchant_id=merchant_id,
            customer_id=customer_id,
            amount=resolved_amount,
            event_id=f"evt_wrong_cust_fail_{resolved_seed}",
            provider_payment_id=f"pay_sim_cust_a_{resolved_seed}",
            provider_order_id=f"order_sim_cust_a_{resolved_seed}",
            event_type="payment.failed",
            status="FAILED",
            failure_reason="DECLINED",
        )
        captured = _ingest_explicit(
            session,
            queue,
            merchant_id=merchant_id,
            customer_id=alt.id,
            amount=resolved_amount,
            event_id=f"evt_wrong_cust_cap_{resolved_seed}",
            provider_payment_id=f"pay_sim_cust_b_{resolved_seed}",
            provider_order_id=f"order_sim_cust_a_{resolved_seed}",
            event_type="payment.captured",
            status="CAPTURED",
        )
        return [failed, captured]
    if key in {"J", "WRONG_MERCHANT"}:
        from recoverai_domain.fixtures import ensure_alt_simulator_merchant

        alt_merchant, alt_customer = ensure_alt_simulator_merchant(session)
        failed = _ingest_explicit(
            session,
            queue,
            merchant_id=merchant_id,
            customer_id=customer_id,
            amount=resolved_amount,
            event_id=f"evt_wrong_merch_fail_{resolved_seed}",
            provider_payment_id=f"pay_sim_merch_a_{resolved_seed}",
            provider_order_id=f"order_sim_merch_a_{resolved_seed}",
            event_type="payment.failed",
            status="FAILED",
            failure_reason="DECLINED",
        )
        captured = _ingest_explicit(
            session,
            queue,
            merchant_id=alt_merchant.id,
            customer_id=alt_customer.id,
            amount=resolved_amount,
            event_id=f"evt_wrong_merch_cap_{resolved_seed}",
            provider_payment_id=f"pay_sim_merch_b_{resolved_seed}",
            provider_order_id=f"order_sim_merch_a_{resolved_seed}",
            event_type="payment.captured",
            status="CAPTURED",
        )
        return [failed, captured]
    if key in {"K", "PARTIAL_CAPTURE"}:
        failed = _ingest_explicit(
            session,
            queue,
            merchant_id=merchant_id,
            customer_id=customer_id,
            amount=resolved_amount,
            event_id=f"evt_partial_fail_{resolved_seed}",
            provider_payment_id=f"pay_sim_partial_{resolved_seed}",
            provider_order_id=f"order_sim_partial_{resolved_seed}",
            event_type="payment.failed",
            status="FAILED",
            failure_reason="INSUFFICIENT_FUNDS",
        )
        captured = _ingest_explicit(
            session,
            queue,
            merchant_id=merchant_id,
            customer_id=customer_id,
            amount=resolved_amount / 2,
            event_id=f"evt_partial_cap_{resolved_seed}",
            provider_payment_id=f"pay_sim_partial_{resolved_seed}",
            provider_order_id=f"order_sim_partial_{resolved_seed}",
            event_type="payment.captured",
            status="CAPTURED",
        )
        return [failed, captured]
    if key in {"L", "DUPLICATE_CAPTURE"}:
        failed = _ingest_explicit(
            session,
            queue,
            merchant_id=merchant_id,
            customer_id=customer_id,
            amount=resolved_amount,
            event_id=f"evt_dupcap_fail_{resolved_seed}",
            provider_payment_id=f"pay_sim_dupcap_{resolved_seed}",
            provider_order_id=f"order_sim_dupcap_{resolved_seed}",
            event_type="payment.failed",
            status="FAILED",
            failure_reason="NETWORK_TIMEOUT",
        )
        first = _ingest_explicit(
            session,
            queue,
            merchant_id=merchant_id,
            customer_id=customer_id,
            amount=resolved_amount,
            event_id=f"evt_dupcap_ok_{resolved_seed}",
            provider_payment_id=f"pay_sim_dupcap_{resolved_seed}",
            provider_order_id=f"order_sim_dupcap_{resolved_seed}",
            event_type="payment.captured",
            status="CAPTURED",
        )
        second = _ingest_explicit(
            session,
            queue,
            merchant_id=merchant_id,
            customer_id=customer_id,
            amount=resolved_amount,
            event_id=f"evt_dupcap_again_{resolved_seed}",
            provider_payment_id=f"pay_sim_dupcap_{resolved_seed}",
            provider_order_id=f"order_sim_dupcap_{resolved_seed}",
            event_type="payment.captured",
            status="CAPTURED",
        )
        return [failed, first, second]
    if key in {"M", "DELAYED_CAPTURE"}:
        failed = _ingest_explicit(
            session,
            queue,
            merchant_id=merchant_id,
            customer_id=customer_id,
            amount=resolved_amount,
            event_id=f"evt_delay_fail_{resolved_seed}",
            provider_payment_id=f"pay_sim_delay_{resolved_seed}",
            provider_order_id=f"order_sim_delay_{resolved_seed}",
            event_type="payment.failed",
            status="FAILED",
            failure_reason="TEMPORARY_BANK_ERROR",
        )
        from datetime import timedelta

        captured = _ingest_explicit(
            session,
            queue,
            merchant_id=merchant_id,
            customer_id=customer_id,
            amount=resolved_amount,
            event_id=f"evt_delay_cap_{resolved_seed}",
            provider_payment_id=f"pay_sim_delay_{resolved_seed}",
            provider_order_id=f"order_sim_delay_{resolved_seed}",
            event_type="payment.captured",
            status="CAPTURED",
            occurred_at=datetime.now(UTC) + timedelta(hours=200),
        )
        return [failed, captured]
    if key in {"N", "CAPTURE_BEFORE_CASE"}:
        captured = _ingest_explicit(
            session,
            queue,
            merchant_id=merchant_id,
            customer_id=customer_id,
            amount=resolved_amount,
            event_id=f"evt_before_cap_{resolved_seed}",
            provider_payment_id=f"pay_sim_before_{resolved_seed}",
            provider_order_id=f"order_sim_before_{resolved_seed}",
            event_type="payment.captured",
            status="CAPTURED",
        )
        failed = _ingest_explicit(
            session,
            queue,
            merchant_id=merchant_id,
            customer_id=customer_id,
            amount=resolved_amount,
            event_id=f"evt_before_fail_{resolved_seed}",
            provider_payment_id=f"pay_sim_before_{resolved_seed}",
            provider_order_id=f"order_sim_before_{resolved_seed}",
            event_type="payment.failed",
            status="FAILED",
            failure_reason="TEMPORARY_BANK_ERROR",
        )
        return [captured, failed]
    if key in {"O", "ALREADY_COUNTED"}:
        return run_scenario(
            session,
            queue,
            scenario="G",
            settings=settings,
            merchant_slug=merchant_slug,
            seed=seed,
            amount=amount,
        )
    raise IngestionError(
        "INVALID_PROVIDER_EVENT",
        "Unknown scenario. Supported: A, B, C, E, G-O. "
        "D is a malformed webhook body. F is processed by running the worker job twice.",
    )


def _ingest_explicit(
    session: Session,
    queue: EventQueue,
    *,
    merchant_id: UUID,
    customer_id: UUID | None,
    amount: Decimal,
    event_id: str,
    provider_payment_id: str,
    provider_order_id: str | None,
    event_type: str,
    status: str,
    failure_reason: str | None = None,
    occurred_at: datetime | None = None,
) -> IngestResult:
    event = webhook_to_provider_event(
        event_id=event_id,
        event_type=event_type,
        merchant_id=merchant_id,
        provider_resource_id=provider_payment_id,
        provider_order_id=provider_order_id,
        customer_id=customer_id,
        amount=amount,
        currency="INR",
        status=status,
        failure_reason=failure_reason,
        occurred_at=occurred_at,
    )
    return ingestion.ingest(
        session,
        event,
        merchant_id=merchant_id,
        queue=queue,
    )
