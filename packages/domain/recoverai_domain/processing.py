from __future__ import annotations

import logging
import uuid
from datetime import UTC, datetime
from decimal import Decimal

from sqlalchemy import select
from sqlalchemy.exc import IntegrityError, OperationalError
from sqlalchemy.orm import Session

from recoverai_db.enums import (
    ActorType,
    PaymentStatus,
    RecoveryCaseStatus,
    RecoveryCaseType,
    WebhookEventStatus,
)
from recoverai_db.models import Payment, PaymentAttempt, RecoveryCase, WebhookEvent
from recoverai_db.repositories import (
    CustomerRepository,
    MerchantRepository,
    PaymentRepository,
    RecoveryCaseRepository,
    WebhookEventRepository,
)
from recoverai_domain.audit import AuditEventType
from recoverai_domain.audit_write import record_audit
from recoverai_domain.errors import DomainError
from recoverai_domain.events import DomainEventType, DomainPaymentEvent, UnknownDomainEvent
from recoverai_domain.normalize import normalize_provider_event
from recoverai_domain.verification_types import FollowUpJob
from recoverai_providers.models import ProviderEvent

logger = logging.getLogger(__name__)

INTERNAL_PAYMENT_NS = uuid.UUID("3d5c8a10-6b2e-4f1a-9c3d-0e7f2a1b4c8d")
SAFE_ERROR_MAX_LEN = 500


def internal_payment_uuid(
    merchant_id: uuid.UUID, provider: str, provider_payment_id: str
) -> uuid.UUID:
    return uuid.uuid5(INTERNAL_PAYMENT_NS, f"{merchant_id}:{provider}:{provider_payment_id}")


def provider_event_from_row(row: WebhookEvent) -> ProviderEvent:
    payload = dict(row.payload or {})
    resource_id = str(
        payload.get("provider_payment_id")
        or payload.get("provider_resource_id")
        or payload.get("payment_id")
        or ""
    )
    merchant_reference = str(payload.get("merchant_reference") or str(row.merchant_id))
    occurred_at = row.received_at
    raw_occurred = payload.get("occurred_at")
    if isinstance(raw_occurred, str) and raw_occurred.strip():
        try:
            parsed = datetime.fromisoformat(raw_occurred.replace("Z", "+00:00"))
            if parsed.tzinfo is None:
                parsed = parsed.replace(tzinfo=UTC)
            occurred_at = parsed
        except ValueError:
            occurred_at = row.received_at
    return ProviderEvent(
        provider=row.provider,
        event_id=row.event_id,
        event_type=row.event_type,
        occurred_at=occurred_at,
        provider_resource_id=resource_id,
        merchant_reference=merchant_reference,
        payload=payload,
        signature_valid=row.signature_valid,
        correlation_id=row.correlation_id,
    )


def process_webhook_event(session: Session, webhook_event_id: uuid.UUID) -> dict[str, object]:
    stmt = select(WebhookEvent).where(WebhookEvent.id == webhook_event_id).with_for_update()
    row = session.scalar(stmt)
    if row is None:
        raise DomainError(
            "INVALID_PROVIDER_EVENT",
            f"Webhook event {webhook_event_id} was not found",
        )

    extra = {
        "correlation_id": row.correlation_id,
        "merchant_id": str(row.merchant_id),
        "event_id": row.event_id,
    }
    if row.status == WebhookEventStatus.PROCESSED:
        logger.info("event processed", extra={**extra, "idempotent": True})
        return {"status": "already_processed", "webhook_event_id": str(row.id), "followups": []}
    if row.status == WebhookEventStatus.DEAD_LETTER:
        return {"status": "dead_letter", "webhook_event_id": str(row.id), "followups": []}

    # RECEIVED, PROCESSING (crashed worker), and FAILED (retry) are all eligible.
    row.status = WebhookEventStatus.PROCESSING
    session.flush()

    try:
        merchant = MerchantRepository(session).get_merchant(row.merchant_id)
        if merchant is None:
            raise DomainError("MISSING_MERCHANT", "Merchant was not found for provider event")

        provider_event = provider_event_from_row(row)
        domain_event = normalize_provider_event(
            provider_event,
            webhook_event_id=row.id,
            merchant_id=row.merchant_id,
        )
        followups: list[FollowUpJob] = []
        _dispatch(session, row, domain_event, followups)
        row.status = WebhookEventStatus.PROCESSED
        row.processed_at = datetime.now(UTC)
        row.error_code = None
        row.error_message = None
        record_audit(
            session,
            merchant_id=row.merchant_id,
            event_type=AuditEventType.PROVIDER_EVENT_PROCESSED,
            summary="Provider event processed",
            actor_type=ActorType.WORKER,
            action="process",
            new_state=WebhookEventStatus.PROCESSED,
            correlation_id=row.correlation_id,
            idempotency_key=f"{row.provider}:{row.event_id}",
            metadata={"webhook_event_id": str(row.id), "event_type": row.event_type},
        )
        logger.info("event processed", extra=extra)
        return {
            "status": "processed",
            "webhook_event_id": str(row.id),
            "followups": [job.as_dict() for job in followups],
        }
    except DomainError as exc:
        if not exc.retryable:
            _mark_failure(session, row, exc, dead_letter=True)
            logger.info(
                "event failed",
                extra={**extra, "error_code": exc.code, "dead_letter": True},
            )
            return {"status": "dead_letter", "webhook_event_id": str(row.id), "followups": []}
        _mark_failure(session, row, exc)
        logger.info("event failed", extra={**extra, "error_code": exc.code})
        raise
    except Exception as exc:
        _mark_failure(session, row, exc)
        logger.info(
            "event failed",
            extra={**extra, "error_code": getattr(exc, "code", type(exc).__name__)},
        )
        raise


def _mark_failure(
    session: Session,
    row: WebhookEvent,
    exc: BaseException,
    *,
    dead_letter: bool = False,
) -> None:
    retryable = isinstance(exc, OperationalError) or (
        isinstance(exc, DomainError) and exc.retryable
    )
    code = getattr(exc, "code", type(exc).__name__)
    message = str(exc)[:SAFE_ERROR_MAX_LEN]
    row.error_code = str(code)[:64]
    row.error_message = message
    row.status = WebhookEventStatus.DEAD_LETTER if dead_letter else WebhookEventStatus.FAILED
    record_audit(
        session,
        merchant_id=row.merchant_id,
        event_type=AuditEventType.PROVIDER_EVENT_FAILED,
        summary=(
            "Provider event moved to dead letter"
            if dead_letter
            else "Provider event processing failed"
        ),
        actor_type=ActorType.WORKER,
        action="dead_letter" if dead_letter else "process_failed",
        new_state=row.status,
        correlation_id=row.correlation_id,
        metadata={
            "webhook_event_id": str(row.id),
            "error_code": str(code),
            "retryable": retryable,
        },
    )


def mark_dead_letter(session: Session, webhook_event_id: uuid.UUID, error: str) -> None:
    row = WebhookEventRepository(session).get(webhook_event_id)
    if row is None:
        return
    if row.status in {WebhookEventStatus.PROCESSED, WebhookEventStatus.DEAD_LETTER}:
        return
    row.status = WebhookEventStatus.DEAD_LETTER
    row.error_message = error[:SAFE_ERROR_MAX_LEN]
    record_audit(
        session,
        merchant_id=row.merchant_id,
        event_type=AuditEventType.PROVIDER_EVENT_FAILED,
        summary="Provider event moved to dead letter after bounded retries",
        actor_type=ActorType.WORKER,
        action="dead_letter",
        new_state=WebhookEventStatus.DEAD_LETTER,
        correlation_id=row.correlation_id,
        metadata={"webhook_event_id": str(row.id)},
    )


def _dispatch(
    session: Session,
    row: WebhookEvent,
    domain_event: DomainPaymentEvent | UnknownDomainEvent,
    followups: list[FollowUpJob],
) -> None:
    if isinstance(domain_event, UnknownDomainEvent):
        record_audit(
            session,
            merchant_id=row.merchant_id,
            event_type=AuditEventType.UNKNOWN_EVENT_IGNORED,
            summary="Unknown provider event type stored without domain side effects",
            actor_type=ActorType.WORKER,
            action="ignore_unknown",
            correlation_id=row.correlation_id,
            metadata={
                "raw_event_type": domain_event.raw_event_type,
                "payload_keys": domain_event.payload_keys,
            },
        )
        return
    if domain_event.event_type is DomainEventType.PAYMENT_FAILED:
        _handle_payment_failed(session, row, domain_event, followups)
        return
    if domain_event.event_type is DomainEventType.PAYMENT_CAPTURED:
        _handle_payment_captured(session, row, domain_event, followups)
        return
    if domain_event.event_type is DomainEventType.PAYMENT_REFUNDED:
        _handle_payment_refunded(session, row, domain_event)
        return
    if domain_event.event_type is DomainEventType.PAYMENT_CANCELLED:
        _handle_payment_status(session, row, domain_event, PaymentStatus.CANCELLED)
        return
    status = (
        PaymentStatus.AUTHORIZED
        if domain_event.event_type is DomainEventType.PAYMENT_AUTHORIZED
        else PaymentStatus.CREATED
    )
    _handle_payment_status(session, row, domain_event, status)


def _resolve_customer(session: Session, event: DomainPaymentEvent) -> uuid.UUID:
    customers = CustomerRepository(session)
    if event.customer_id is not None:
        customer = customers.get_customer(event.merchant_id, event.customer_id)
        if customer is None:
            raise DomainError("MISSING_CUSTOMER", "Customer does not belong to this merchant")
        return customer.id
    if event.customer_external_id:
        customer = customers.get_by_external_id(event.merchant_id, event.customer_external_id)
        if customer is None:
            raise DomainError("MISSING_CUSTOMER", "Customer external id was not found")
        return customer.id
    raise DomainError("MISSING_CUSTOMER", "customer_id or customer_external_id is required")


def _find_or_create_payment(
    session: Session,
    event: DomainPaymentEvent,
    *,
    status: str,
) -> tuple[Payment, str | None]:
    payments = PaymentRepository(session)
    existing = payments.get_by_provider_payment_id(
        event.merchant_id, event.provider, event.provider_payment_id
    )
    if existing is not None:
        previous = existing.status
        if not _is_status_downgrade(previous, status):
            existing.status = status
        existing.provider_order_id = event.provider_order_id or existing.provider_order_id
        if status == PaymentStatus.FAILED:
            existing.failure_code = event.failure_code or existing.failure_code
            existing.failure_reason = event.failure_code or existing.failure_reason
            existing.failed_at = event.occurred_at
        if status == PaymentStatus.CAPTURED:
            existing.captured_at = event.occurred_at
            existing.status = PaymentStatus.CAPTURED
            existing.amount = event.amount
        existing.payment_method = event.payment_method or existing.payment_method
        _add_attempt(session, existing, event, status)
        return existing, previous

    customer_id = _resolve_customer(session, event)
    payment = Payment(
        id=internal_payment_uuid(event.merchant_id, event.provider, event.provider_payment_id),
        merchant_id=event.merchant_id,
        customer_id=customer_id,
        provider=event.provider,
        provider_payment_id=event.provider_payment_id,
        provider_order_id=event.provider_order_id,
        amount=event.amount,
        provider_amount_minor=int(event.amount * 100),
        currency=event.currency,
        status=status,
        payment_method=event.payment_method,
        failure_reason=event.failure_code,
        failure_code=event.failure_code,
        captured_at=event.occurred_at if status == PaymentStatus.CAPTURED else None,
        failed_at=event.occurred_at if status == PaymentStatus.FAILED else None,
    )
    payments.add(payment)
    session.flush()
    _add_attempt(session, payment, event, status)
    return payment, None


def _add_attempt(
    session: Session, payment: Payment, event: DomainPaymentEvent, status: str
) -> None:
    number = PaymentRepository(session).next_attempt_number(payment.id)
    session.add(
        PaymentAttempt(
            payment_id=payment.id,
            attempt_number=number,
            status=status,
            amount=event.amount,
            currency=event.currency,
            failure_reason=event.failure_code,
            failure_code=event.failure_code,
            attempted_at=event.occurred_at,
        )
    )


def _is_status_downgrade(current: str, incoming: str) -> bool:
    if current == PaymentStatus.CAPTURED and incoming in {
        PaymentStatus.CREATED,
        PaymentStatus.AUTHORIZED,
        PaymentStatus.FAILED,
        PaymentStatus.CANCELLED,
    }:
        return True
    if current == PaymentStatus.REFUNDED and incoming != PaymentStatus.REFUNDED:
        return True
    return False


def _handle_payment_failed(
    session: Session,
    row: WebhookEvent,
    event: DomainPaymentEvent,
    followups: list[FollowUpJob],
) -> None:
    payment, previous = _find_or_create_payment(session, event, status=PaymentStatus.FAILED)
    record_audit(
        session,
        merchant_id=event.merchant_id,
        event_type=AuditEventType.PAYMENT_UPDATED,
        summary="Payment marked FAILED from provider event",
        actor_type=ActorType.WORKER,
        action="update_payment",
        previous_state=previous,
        new_state=PaymentStatus.FAILED,
        correlation_id=event.correlation_id,
        metadata={
            "payment_id": str(payment.id),
            "provider_payment_id": event.provider_payment_id,
            "provider_order_id": event.provider_order_id,
        },
    )
    _create_or_attach_recovery_case(session, row, event, payment, followups)


def _create_or_attach_recovery_case(
    session: Session,
    row: WebhookEvent,
    event: DomainPaymentEvent,
    payment: Payment,
    followups: list[FollowUpJob],
) -> None:
    cases = RecoveryCaseRepository(session)
    open_cases = cases.list_open_for_payment(event.merchant_id, payment.id)
    if open_cases:
        case = open_cases[0]
        record_audit(
            session,
            merchant_id=event.merchant_id,
            case_id=case.id,
            event_type=AuditEventType.RECOVERY_CASE_ATTACHED,
            summary="Existing open recovery case attached; no duplicate case created",
            actor_type=ActorType.WORKER,
            action="attach_case",
            new_state=case.status,
            correlation_id=event.correlation_id,
            metadata={
                "payment_id": str(payment.id),
                "source_event_id": str(row.id),
            },
        )
        logger.info(
            "case attached",
            extra={
                "correlation_id": event.correlation_id,
                "merchant_id": str(event.merchant_id),
                "event_id": event.provider_event_id,
            },
        )
        if payment.status == PaymentStatus.CAPTURED:
            _queue_verify(followups, case, payment, row.id)
        return

    case = RecoveryCase(
        merchant_id=event.merchant_id,
        customer_id=payment.customer_id,
        payment_id=payment.id,
        case_type=RecoveryCaseType.FAILED_PAYMENT,
        status=RecoveryCaseStatus.DETECTED,
        amount_at_risk=payment.amount,
        amount_recovered=Decimal("0.00"),
        currency=payment.currency,
        source_event_id=row.id,
        opened_at=datetime.now(UTC),
    )
    try:
        with session.begin_nested():
            cases.add(case)
            session.flush()
    except IntegrityError:
        session.expire_all()
        open_cases = cases.list_open_for_payment(event.merchant_id, payment.id)
        if not open_cases:
            raise
        case = open_cases[0]
        record_audit(
            session,
            merchant_id=event.merchant_id,
            case_id=case.id,
            event_type=AuditEventType.RECOVERY_CASE_ATTACHED,
            summary="Existing open recovery case attached after uniqueness conflict",
            actor_type=ActorType.WORKER,
            action="attach_case",
            new_state=case.status,
            correlation_id=event.correlation_id,
            metadata={"payment_id": str(payment.id)},
        )
        if payment.status == PaymentStatus.CAPTURED:
            _queue_verify(followups, case, payment, row.id)
        return

    record_audit(
        session,
        merchant_id=event.merchant_id,
        case_id=case.id,
        event_type=AuditEventType.RECOVERY_CASE_CREATED,
        summary="Recovery case created in DETECTED status for failed payment",
        actor_type=ActorType.WORKER,
        action="create_case",
        new_state=RecoveryCaseStatus.DETECTED,
        correlation_id=event.correlation_id,
        metadata={
            "payment_id": str(payment.id),
            "case_id": str(case.id),
            "amount_at_risk": str(payment.amount),
        },
    )
    logger.info(
        "case created",
        extra={
            "correlation_id": event.correlation_id,
            "merchant_id": str(event.merchant_id),
            "event_id": event.provider_event_id,
        },
    )
    followups.append(
        FollowUpJob(name="process_recovery_case", case_id=case.id, webhook_event_id=row.id)
    )
    if payment.status == PaymentStatus.CAPTURED:
        _queue_verify(followups, case, payment, row.id)


def _queue_verify(
    followups: list[FollowUpJob],
    case: RecoveryCase,
    payment: Payment,
    webhook_event_id: uuid.UUID,
) -> None:
    followups.append(
        FollowUpJob(
            name="verify_recovery_case",
            case_id=case.id,
            payment_id=payment.id,
            webhook_event_id=webhook_event_id,
        )
    )


def _candidate_cases(session: Session, payment: Payment) -> list[RecoveryCase]:
    repo = RecoveryCaseRepository(session)
    by_id: dict[uuid.UUID, RecoveryCase] = {}
    for case in repo.list_open_for_payment(payment.merchant_id, payment.id):
        by_id[case.id] = case
    for case in repo.list_open_for_customer(payment.merchant_id, payment.customer_id):
        if case.closed_at is None:
            by_id[case.id] = case
    return list(by_id.values())


def _handle_payment_captured(
    session: Session,
    row: WebhookEvent,
    event: DomainPaymentEvent,
    followups: list[FollowUpJob],
) -> None:
    payment, previous = _find_or_create_payment(session, event, status=PaymentStatus.CAPTURED)
    candidates = _candidate_cases(session, payment)
    primary = candidates[0] if candidates else None
    record_audit(
        session,
        merchant_id=event.merchant_id,
        case_id=primary.id if primary else None,
        event_type=AuditEventType.PAYMENT_UPDATED,
        summary=(
            "Payment marked CAPTURED from provider event. "
            "Recovery verification queued asynchronously."
        ),
        actor_type=ActorType.WORKER,
        action="update_payment",
        previous_state=previous,
        new_state=PaymentStatus.CAPTURED,
        correlation_id=event.correlation_id,
        metadata={
            "payment_id": str(payment.id),
            "provider_payment_id": event.provider_payment_id,
            "open_recovery_case_id": str(primary.id) if primary else None,
            "verification_queued": bool(candidates),
        },
    )
    for case in candidates:
        _queue_verify(followups, case, payment, row.id)


def _handle_payment_refunded(
    session: Session, row: WebhookEvent, event: DomainPaymentEvent
) -> None:
    del row
    payment, previous = _find_or_create_payment(session, event, status=PaymentStatus.REFUNDED)
    record_audit(
        session,
        merchant_id=event.merchant_id,
        event_type=AuditEventType.PAYMENT_UPDATED,
        summary="Payment marked REFUNDED from provider event. Refund policy is not implemented.",
        actor_type=ActorType.WORKER,
        action="update_payment",
        previous_state=previous,
        new_state=PaymentStatus.REFUNDED,
        correlation_id=event.correlation_id,
        metadata={"payment_id": str(payment.id), "provider_payment_id": event.provider_payment_id},
    )


def _handle_payment_status(
    session: Session,
    row: WebhookEvent,
    event: DomainPaymentEvent,
    status: str,
) -> None:
    del row
    payment, previous = _find_or_create_payment(session, event, status=status)
    record_audit(
        session,
        merchant_id=event.merchant_id,
        event_type=AuditEventType.PAYMENT_UPDATED,
        summary=f"Payment marked {status} from provider event",
        actor_type=ActorType.WORKER,
        action="update_payment",
        previous_state=previous,
        new_state=status,
        correlation_id=event.correlation_id,
        metadata={"payment_id": str(payment.id), "provider_payment_id": event.provider_payment_id},
    )
