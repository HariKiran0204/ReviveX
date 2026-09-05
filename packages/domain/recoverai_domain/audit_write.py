from __future__ import annotations

from datetime import UTC, datetime
from typing import Any
from uuid import UUID

from sqlalchemy.orm import Session

from recoverai_db.enums import ActorType
from recoverai_db.models import AuditEvent
from recoverai_db.repositories import AuditEventRepository
from recoverai_domain.audit import AuditEventType


def record_audit(
    session: Session,
    *,
    merchant_id: UUID,
    event_type: AuditEventType | str,
    summary: str,
    case_id: UUID | None = None,
    actor_type: str = ActorType.SYSTEM,
    actor_id: str | None = None,
    action: str | None = None,
    previous_state: str | None = None,
    new_state: str | None = None,
    correlation_id: str | None = None,
    idempotency_key: str | None = None,
    metadata: dict[str, Any] | None = None,
) -> AuditEvent:
    event = AuditEvent(
        merchant_id=merchant_id,
        case_id=case_id,
        actor_type=actor_type,
        actor_id=actor_id,
        event_type=str(event_type),
        action=action,
        previous_state=previous_state,
        new_state=new_state,
        summary=summary,
        metadata_json=metadata,
        correlation_id=correlation_id,
        idempotency_key=idempotency_key,
        created_at=datetime.now(UTC),
    )
    AuditEventRepository(session).add(event)
    return event
