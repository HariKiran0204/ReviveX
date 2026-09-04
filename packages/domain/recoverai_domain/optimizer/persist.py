from __future__ import annotations

from datetime import UTC, datetime
from typing import Any
from uuid import UUID

from sqlalchemy.orm import Session

from recoverai_db.models import RecoveryDecision
from recoverai_domain.audit import AuditEventType
from recoverai_domain.audit_write import record_audit
from recoverai_domain.optimizer.types import OptimizationResult


def persist_optimization_decision(
    session: Session,
    result: OptimizationResult,
    *,
    merchant_id: UUID,
    correlation_id: str | None = None,
) -> RecoveryDecision:
    """Insert a new recovery_decisions row. Never updates historical decisions."""
    now = datetime.now(UTC)
    expected_values = {item.action: str(item.expected_value) for item in result.candidate_actions}
    row = RecoveryDecision(
        merchant_id=merchant_id,
        recovery_case_id=result.case_id,
        model_version=result.model_version,
        agent_version=None,
        decision_version=result.optimizer_version,
        selected_action=result.selected_action or "NONE",
        candidate_actions={
            "optimizer_version": result.optimizer_version,
            "actions": [item.to_public_dict() for item in result.candidate_actions],
        },
        expected_values=expected_values,
        selected_expected_value=result.selected_expected_value,
        policy_verdict=_policy_verdict(result),
        explanation=result.selection_reason,
        decision_factors=_decision_factors(result, now),
    )
    session.add(row)
    session.flush()
    record_audit(
        session,
        merchant_id=merchant_id,
        case_id=result.case_id,
        event_type=AuditEventType.ERV_OPTIMIZATION_RECORDED,
        summary=result.selection_reason,
        action=result.selected_action,
        correlation_id=correlation_id,
        metadata={
            "decision_id": str(row.id),
            "optimizer_version": result.optimizer_version,
            "model_version": result.model_version,
            "selected_expected_value": (
                str(result.selected_expected_value)
                if result.selected_expected_value is not None
                else None
            ),
            "prediction_source": result.prediction_source,
        },
    )
    return row


def _policy_verdict(result: OptimizationResult) -> str:
    if result.selected_action is None:
        return "NONE"
    selected = next(
        (item for item in result.candidate_actions if item.action == result.selected_action),
        None,
    )
    if selected is None:
        return "NONE"
    if not selected.allowed:
        return "DENY"
    if selected.requires_approval:
        return "APPROVAL_REQUIRED"
    return "ALLOW"


def _decision_factors(result: OptimizationResult, now: datetime) -> dict[str, Any]:
    return {
        "optimizer_version": result.optimizer_version,
        "feature_version": result.feature_version,
        "prediction_source": result.prediction_source,
        "requires_approval": result.requires_approval,
        "recorded_at": now.isoformat(),
        "expected_vs_actual": {
            "expected_recovery_is_probabilistic": True,
            "actual_recovery_owned_by": "RecoveryVerificationService",
        },
    }
