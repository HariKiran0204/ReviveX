from __future__ import annotations

from datetime import UTC, datetime
from uuid import UUID

from sqlalchemy import select
from sqlalchemy.orm import Session

from recoverai_db.enums import ActorType, ApprovalStatus, RecoveryActionStatus, RecoveryCaseStatus
from recoverai_db.models import Approval, IdempotencyKey, RecoveryAction
from recoverai_domain.audit import AuditEventType
from recoverai_domain.audit_write import record_audit
from recoverai_domain.errors import ToolValidationError
from recoverai_domain.recovery_config import RecoverySettings, load_recovery_settings
from recoverai_domain.state_machine import coerce_status
from recoverai_domain.tools.execution import ToolExecutionResult, ToolExecutionService
from recoverai_domain.tools.idempotency import fail_idempotent_operation
from recoverai_domain.transitions import lock_recovery_case, transition_case
from recoverai_providers.base import PaymentProvider


class ApprovalService:
    def __init__(
        self,
        session: Session,
        *,
        settings: RecoverySettings | None = None,
        provider: PaymentProvider | None = None,
    ) -> None:
        self._session = session
        self._settings = settings or load_recovery_settings()
        self._provider = provider

    def approve_action(
        self,
        case_id: UUID,
        action_id: UUID,
        *,
        actor_id: str | None = "demo-operator",
        actor_type: str = ActorType.USER,
        correlation_id: str | None = None,
        merchant_id: UUID | None = None,
    ) -> ToolExecutionResult:
        case = lock_recovery_case(self._session, case_id)
        if merchant_id is not None and case.merchant_id != merchant_id:
            raise ToolValidationError(
                "MERCHANT_MISMATCH", "Case does not belong to the given merchant"
            )
        action = self._load_action(case.merchant_id, action_id)
        approval = self._pending_approval(case.id, action.id)
        self._expire_if_needed(approval)
        if approval.status == ApprovalStatus.EXPIRED:
            raise ToolValidationError("APPROVAL_EXPIRED", "Approval has expired and cannot execute")
        if approval.status != ApprovalStatus.PENDING:
            raise ToolValidationError("APPROVAL_NOT_PENDING", f"Approval is {approval.status}")
        if action.status not in {
            RecoveryActionStatus.APPROVAL_REQUIRED,
            RecoveryActionStatus.APPROVED,
            RecoveryActionStatus.PENDING,
        }:
            raise ToolValidationError(
                "ACTION_NOT_APPROVABLE",
                f"Action in status {action.status} cannot be approved",
            )

        approval.status = ApprovalStatus.APPROVED
        approval.decided_by = actor_id
        approval.decided_at = datetime.now(UTC)
        action.status = RecoveryActionStatus.APPROVED
        record_audit(
            self._session,
            merchant_id=case.merchant_id,
            case_id=case.id,
            event_type=AuditEventType.APPROVAL_APPROVED,
            summary="Operator approved recovery action; re-entering ToolExecutionService",
            actor_type=actor_type,
            actor_id=actor_id,
            action=action.action_type,
            correlation_id=correlation_id,
            idempotency_key=action.idempotency_key,
            metadata={
                "case_id": str(case.id),
                "merchant_id": str(case.merchant_id),
                "approval_id": str(approval.id),
                "action_id": str(action.id),
            },
        )
        self._session.flush()
        meta = action.metadata_json or {}
        tool_name = str(meta.get("tool_name") or "")
        payload = meta.get("payload") if isinstance(meta.get("payload"), dict) else {}
        return ToolExecutionService(
            self._session, settings=self._settings, provider=self._provider
        ).execute(
            case.id,
            tool_name=tool_name or None,
            action=action.action_type,
            payload=payload,
            idempotency_key=action.idempotency_key,
            merchant_id=case.merchant_id,
            actor_type=actor_type,
            actor_id=actor_id,
            correlation_id=correlation_id,
            existing_action_id=action.id,
            approval_id=approval.id,
            approved_execution=True,
        )

    def reject_action(
        self,
        case_id: UUID,
        action_id: UUID,
        *,
        actor_id: str | None = "demo-operator",
        actor_type: str = ActorType.USER,
        reason: str | None = None,
        merchant_id: UUID | None = None,
        correlation_id: str | None = None,
    ) -> dict[str, str]:
        case = lock_recovery_case(self._session, case_id)
        if merchant_id is not None and case.merchant_id != merchant_id:
            raise ToolValidationError(
                "MERCHANT_MISMATCH", "Case does not belong to the given merchant"
            )
        action = self._load_action(case.merchant_id, action_id)
        approval = self._pending_approval(case.id, action.id)
        self._expire_if_needed(approval)
        approval.status = ApprovalStatus.REJECTED
        approval.decided_by = actor_id
        approval.decided_at = datetime.now(UTC)
        approval.decision_reason = reason or "Rejected by operator"
        action.status = RecoveryActionStatus.CANCELLED
        key_row = self._session.scalar(
            select(IdempotencyKey).where(
                IdempotencyKey.merchant_id == case.merchant_id,
                IdempotencyKey.key == action.idempotency_key,
            )
        )
        if key_row is not None:
            fail_idempotent_operation(key_row, error_code="APPROVAL_REJECTED")
        record_audit(
            self._session,
            merchant_id=case.merchant_id,
            case_id=case.id,
            event_type=AuditEventType.APPROVAL_REJECTED,
            summary=approval.decision_reason or "Approval rejected",
            actor_type=actor_type,
            actor_id=actor_id,
            action=action.action_type,
            correlation_id=correlation_id,
            idempotency_key=action.idempotency_key,
            metadata={
                "case_id": str(case.id),
                "merchant_id": str(case.merchant_id),
                "approval_id": str(approval.id),
                "action_id": str(action.id),
            },
        )
        record_audit(
            self._session,
            merchant_id=case.merchant_id,
            case_id=case.id,
            event_type=AuditEventType.ACTION_CANCELLED,
            summary="Pending action cancelled after approval rejection",
            actor_type=actor_type,
            actor_id=actor_id,
            action=action.action_type,
            correlation_id=correlation_id,
            idempotency_key=action.idempotency_key,
            metadata={"case_id": str(case.id), "merchant_id": str(case.merchant_id)},
        )
        if coerce_status(case.status) is RecoveryCaseStatus.AWAITING_APPROVAL:
            transition_case(
                self._session,
                case,
                RecoveryCaseStatus.ESCALATED,
                actor_type=actor_type,
                correlation_id=correlation_id,
                summary="Approval rejected; case escalated without claiming recovery",
            )
        self._session.flush()
        return {
            "status": "REJECTED",
            "action_id": str(action.id),
            "approval_id": str(approval.id),
            "case_status": case.status,
        }

    def cancel_action(
        self,
        case_id: UUID,
        action_id: UUID,
        *,
        actor_id: str | None = "demo-operator",
        reason: str | None = None,
        merchant_id: UUID | None = None,
        correlation_id: str | None = None,
    ) -> dict[str, str]:
        return self.reject_action(
            case_id,
            action_id,
            actor_id=actor_id,
            reason=reason or "Cancelled by merchant operator",
            merchant_id=merchant_id,
            correlation_id=correlation_id,
        )

    def _load_action(self, merchant_id: UUID, action_id: UUID) -> RecoveryAction:
        action = self._session.get(RecoveryAction, action_id)
        if action is None or action.merchant_id != merchant_id:
            raise ToolValidationError("ACTION_NOT_FOUND", "Recovery action was not found")
        return action

    def _pending_approval(self, case_id: UUID, action_id: UUID) -> Approval:
        approval = self._session.scalar(
            select(Approval)
            .where(
                Approval.recovery_case_id == case_id,
                Approval.recovery_action_id == action_id,
            )
            .order_by(Approval.created_at.desc())
        )
        if approval is None:
            raise ToolValidationError("APPROVAL_NOT_FOUND", "No approval exists for this action")
        return approval

    def _expire_if_needed(self, approval: Approval) -> None:
        if (
            approval.status == ApprovalStatus.PENDING
            and approval.expires_at is not None
            and approval.expires_at <= datetime.now(UTC)
        ):
            approval.status = ApprovalStatus.EXPIRED
            self._session.flush()
