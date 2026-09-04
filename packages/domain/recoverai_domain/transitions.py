from __future__ import annotations

from datetime import UTC, datetime
from uuid import UUID

from sqlalchemy.orm import Session

from recoverai_db.enums import ActorType, RecoveryCaseStatus
from recoverai_db.models import RecoveryCase
from recoverai_db.repositories import RecoveryCaseRepository
from recoverai_domain.audit import AuditEventType
from recoverai_domain.audit_write import record_audit
from recoverai_domain.errors import ConcurrentCaseUpdateError, DomainError, InvalidTransitionError
from recoverai_domain.state_machine import (
    AUDIT_TYPE_FOR_TARGET,
    assert_legal_transition,
    coerce_status,
    is_terminal,
)


def lock_recovery_case(session: Session, case_id: UUID) -> RecoveryCase:
    case = RecoveryCaseRepository(session).get_case_for_update(case_id)
    if case is None:
        raise DomainError("RECOVERY_CASE_NOT_FOUND", f"Recovery case {case_id} was not found")
    return case


def transition_case(
    session: Session,
    case: RecoveryCase,
    to_status: str | RecoveryCaseStatus,
    *,
    actor_type: str = ActorType.WORKER,
    correlation_id: str | None = None,
    summary: str | None = None,
    metadata: dict[str, object] | None = None,
    expected_version: int | None = None,
) -> RecoveryCase:
    target = coerce_status(to_status)
    current = coerce_status(case.status)
    if expected_version is not None and case.version != expected_version:
        raise ConcurrentCaseUpdateError(case.id)
    try:
        assert_legal_transition(current, target)
    except InvalidTransitionError as exc:
        exc.case_id = case.id
        record_audit(
            session,
            merchant_id=case.merchant_id,
            case_id=case.id,
            event_type=AuditEventType.STATE_TRANSITION_REJECTED,
            summary=(f"Rejected illegal recovery transition from {current} to {target}"),
            actor_type=actor_type,
            action="reject_transition",
            previous_state=str(current),
            new_state=str(target),
            correlation_id=correlation_id,
            metadata={
                "case_id": str(case.id),
                "merchant_id": str(case.merchant_id),
                **(metadata or {}),
            },
        )
        raise

    previous = str(current)
    case.status = str(target)
    case.version += 1
    now = datetime.now(UTC)
    if is_terminal(target):
        case.closed_at = now
    else:
        case.closed_at = None

    audit_type = AUDIT_TYPE_FOR_TARGET.get(target, AuditEventType.PAYMENT_UPDATED)
    record_audit(
        session,
        merchant_id=case.merchant_id,
        case_id=case.id,
        event_type=audit_type,
        summary=summary or f"Recovery case moved from {previous} to {target}",
        actor_type=actor_type,
        action="transition",
        previous_state=previous,
        new_state=str(target),
        correlation_id=correlation_id,
        metadata={
            "case_id": str(case.id),
            "merchant_id": str(case.merchant_id),
            "version": case.version,
            **(metadata or {}),
        },
    )
    session.flush()
    return case
