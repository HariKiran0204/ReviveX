from __future__ import annotations

import logging
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Any, Protocol
from uuid import UUID

from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from recoverai_db.enums import ActorType, WebhookEventStatus
from recoverai_db.models import WebhookEvent
from recoverai_db.repositories import MerchantRepository, WebhookEventRepository
from recoverai_domain.audit import AuditEventType
from recoverai_domain.audit_write import record_audit
from recoverai_domain.errors import IngestionError
from recoverai_providers.models import ProviderEvent, ProviderName

logger = logging.getLogger(__name__)


class EventQueue(Protocol):
    def enqueue_process_provider_event(self, webhook_event_id: UUID) -> None: ...

    def enqueue_process_recovery_case(self, case_id: UUID) -> None: ...

    def enqueue_verify_recovery_case(
        self,
        case_id: UUID,
        payment_id: UUID | None = None,
        webhook_event_id: UUID | None = None,
    ) -> None: ...


class ImmediateEventQueue:
    """Records jobs. Tests may process them explicitly; the API must not run them inline."""

    def __init__(self) -> None:
        self.enqueued: list[UUID] = []
        self.process_cases: list[UUID] = []
        self.verify_cases: list[tuple[UUID, UUID | None, UUID | None]] = []

    def enqueue_process_provider_event(self, webhook_event_id: UUID) -> None:
        self.enqueued.append(webhook_event_id)

    def enqueue_process_recovery_case(self, case_id: UUID) -> None:
        self.process_cases.append(case_id)

    def enqueue_verify_recovery_case(
        self,
        case_id: UUID,
        payment_id: UUID | None = None,
        webhook_event_id: UUID | None = None,
    ) -> None:
        self.verify_cases.append((case_id, payment_id, webhook_event_id))


@dataclass(frozen=True)
class IngestResult:
    webhook_event_id: UUID
    event_id: str
    status: str
    duplicate: bool
    queued: bool
    merchant_id: UUID
    correlation_id: str | None


def _safe_payload(payload: dict[str, Any]) -> dict[str, Any]:
    blocked = {"authorization", "signature", "secret", "api_key", "key_secret", "webhook_secret"}
    return {key: value for key, value in payload.items() if key.lower() not in blocked}


class EventIngestionService:
    def ingest(
        self,
        session: Session,
        event: ProviderEvent,
        *,
        merchant_id: UUID,
        queue: EventQueue,
        request_id: str | None = None,
    ) -> IngestResult:
        self._validate(event)
        merchant = MerchantRepository(session).get_merchant(merchant_id)
        if merchant is None:
            raise IngestionError("MISSING_MERCHANT", "Merchant was not found", http_status=404)

        correlation_id = event.correlation_id or request_id
        repo = WebhookEventRepository(session)
        existing = repo.get_by_provider_event_id(event.provider, event.event_id)
        if existing is not None:
            return self._handle_duplicate(
                session, existing, queue=queue, correlation_id=correlation_id
            )

        payload = _safe_payload(event.payload)
        if "occurred_at" not in payload:
            payload["occurred_at"] = event.occurred_at.isoformat()
        row = WebhookEvent(
            merchant_id=merchant_id,
            provider=event.provider or ProviderName.SIMULATOR,
            event_id=event.event_id,
            event_type=event.event_type,
            signature_valid=event.signature_valid,
            status=WebhookEventStatus.RECEIVED,
            payload=payload,
            received_at=datetime.now(UTC),
            correlation_id=correlation_id,
        )
        try:
            with session.begin_nested():
                repo.add(row)
                session.flush()
        except IntegrityError:
            session.expire_all()
            duplicate = repo.get_by_provider_event_id(event.provider, event.event_id)
            if duplicate is None:
                raise
            return self._handle_duplicate(
                session, duplicate, queue=queue, correlation_id=correlation_id
            )

        record_audit(
            session,
            merchant_id=merchant_id,
            event_type=AuditEventType.PROVIDER_EVENT_RECEIVED,
            summary="Provider event received and queued for processing",
            actor_type=ActorType.SYSTEM,
            action="ingest",
            new_state=WebhookEventStatus.RECEIVED,
            correlation_id=correlation_id,
            idempotency_key=f"{event.provider}:{event.event_id}",
            metadata={
                "provider": event.provider,
                "event_id": event.event_id,
                "event_type": event.event_type,
                "webhook_event_id": str(row.id),
            },
        )
        logger.info(
            "event received",
            extra={
                "correlation_id": correlation_id,
                "merchant_id": str(merchant_id),
                "event_id": event.event_id,
            },
        )
        queued = False
        try:
            queue.enqueue_process_provider_event(row.id)
            queued = True
            logger.info(
                "event queued",
                extra={
                    "correlation_id": correlation_id,
                    "merchant_id": str(merchant_id),
                    "event_id": event.event_id,
                },
            )
        except Exception:
            logger.exception(
                "event queue failed",
                extra={
                    "correlation_id": correlation_id,
                    "merchant_id": str(merchant_id),
                    "event_id": event.event_id,
                },
            )
        return IngestResult(
            webhook_event_id=row.id,
            event_id=event.event_id,
            status=WebhookEventStatus.RECEIVED,
            duplicate=False,
            queued=queued,
            merchant_id=merchant_id,
            correlation_id=correlation_id,
        )

    def _handle_duplicate(
        self,
        session: Session,
        existing: WebhookEvent,
        *,
        queue: EventQueue,
        correlation_id: str | None,
    ) -> IngestResult:
        should_requeue = existing.status in {
            WebhookEventStatus.RECEIVED,
            WebhookEventStatus.PROCESSING,
            WebhookEventStatus.FAILED,
        }
        record_audit(
            session,
            merchant_id=existing.merchant_id,
            event_type=AuditEventType.DUPLICATE_EVENT_IGNORED,
            summary="Duplicate provider event ignored; no additional side effects",
            actor_type=ActorType.SYSTEM,
            action="ingest_duplicate",
            new_state=existing.status,
            correlation_id=correlation_id or existing.correlation_id,
            idempotency_key=f"{existing.provider}:{existing.event_id}",
            metadata={
                "provider": existing.provider,
                "event_id": existing.event_id,
                "webhook_event_id": str(existing.id),
                "existing_status": existing.status,
                "requeued": should_requeue,
            },
        )
        logger.info(
            "event duplicated",
            extra={
                "correlation_id": correlation_id or existing.correlation_id,
                "merchant_id": str(existing.merchant_id),
                "event_id": existing.event_id,
            },
        )
        queued = False
        if should_requeue:
            try:
                queue.enqueue_process_provider_event(existing.id)
                queued = True
            except Exception:
                logger.exception(
                    "event queue failed",
                    extra={
                        "correlation_id": correlation_id or existing.correlation_id,
                        "merchant_id": str(existing.merchant_id),
                        "event_id": existing.event_id,
                    },
                )
        return IngestResult(
            webhook_event_id=existing.id,
            event_id=existing.event_id,
            status=existing.status,
            duplicate=True,
            queued=queued,
            merchant_id=existing.merchant_id,
            correlation_id=correlation_id or existing.correlation_id,
        )

    def _validate(self, event: ProviderEvent) -> None:
        if not event.event_id or not event.event_id.strip():
            raise IngestionError("INVALID_PROVIDER_EVENT", "event_id is required")
        if not event.event_type or not event.event_type.strip():
            raise IngestionError("INVALID_PROVIDER_EVENT", "event_type is required")
        if not event.provider_resource_id and not event.payload.get("provider_payment_id"):
            if event.event_type in {"payment.failed", "payment.captured", "payment.refunded"}:
                raise IngestionError(
                    "INVALID_PAYMENT_REFERENCE",
                    "provider_resource_id is required for payment events",
                )
