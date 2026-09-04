from __future__ import annotations

from datetime import UTC, datetime, timedelta
from uuid import UUID

from sqlalchemy import select
from sqlalchemy.orm import Session

from recoverai_db.enums import (
    ActorType,
    ApprovalStatus,
    RecoveryActionStatus,
    RecoveryActionType,
    RecoveryCaseStatus,
    RiskLevel,
)
from recoverai_db.models import Approval, Payment, RecoveryAction, RecoveryCase, RecoveryDecision
from recoverai_db.repositories import PaymentRepository
from recoverai_domain.policy_context import build_policy_context
from recoverai_domain.policy_engine import PolicyEngine
from recoverai_domain.policy_types import ProposedAction
from recoverai_domain.recovery_config import RecoverySettings, load_recovery_settings
from recoverai_domain.state_machine import coerce_status, is_terminal
from recoverai_domain.transitions import lock_recovery_case, transition_case

RETRYABLE_FAILURES = frozenset({"TEMPORARY_BANK_ERROR", "NETWORK_TIMEOUT", "INSUFFICIENT_FUNDS"})

PROCESS_STEPS: tuple[tuple[RecoveryCaseStatus, str], ...] = (
    (RecoveryCaseStatus.TRIAGED, "Case triaged with deterministic Phase 4 rules"),
    (RecoveryCaseStatus.INVESTIGATING, "Investigating failed-payment context"),
    (RecoveryCaseStatus.DIAGNOSED, "Diagnosis recorded without ML"),
    (RecoveryCaseStatus.SCORING, "Placeholder scoring started"),
    (RecoveryCaseStatus.STRATEGY_SELECTED, "Placeholder strategy selected"),
    (RecoveryCaseStatus.POLICY_CHECK, "Policy check recorded by the deterministic policy engine"),
)


class RecoveryCaseProcessor:
    """Advances DETECTED cases through the lifecycle without AI/ML/ERV."""

    def __init__(
        self,
        session: Session,
        settings: RecoverySettings | None = None,
    ) -> None:
        self._session = session
        self._settings = settings or load_recovery_settings()

    def process(
        self,
        case_id: UUID,
        *,
        correlation_id: str | None = None,
        actor_type: str = ActorType.WORKER,
    ) -> RecoveryCase:
        case = lock_recovery_case(self._session, case_id)
        return self.process_locked_case(case, correlation_id=correlation_id, actor_type=actor_type)

    def process_locked_case(
        self,
        case: RecoveryCase,
        *,
        correlation_id: str | None = None,
        actor_type: str = ActorType.WORKER,
    ) -> RecoveryCase:
        if is_terminal(case.status):
            return case
        status = coerce_status(case.status)
        if status in {
            RecoveryCaseStatus.ACTION_COMPLETED,
            RecoveryCaseStatus.VERIFYING,
            RecoveryCaseStatus.NOT_RECOVERED,
            RecoveryCaseStatus.RETRY_SCHEDULED,
            RecoveryCaseStatus.FAILED,
            RecoveryCaseStatus.ESCALATED,
            RecoveryCaseStatus.AWAITING_APPROVAL,
        }:
            return case

        self.walk_to_policy_check(case, correlation_id=correlation_id, actor_type=actor_type)
        if coerce_status(case.status) is not RecoveryCaseStatus.POLICY_CHECK:
            self._session.flush()
            return case

        action_type = self._select_action(case)
        context = build_policy_context(self._session, case, settings=self._settings)
        evaluation = PolicyEngine(self._settings).evaluate_and_persist(
            self._session,
            context,
            ProposedAction(action_type=str(action_type)),
            correlation_id=correlation_id,
            actor_type=actor_type,
        )
        if not evaluation.allowed:
            self._record_planned_action(
                case,
                action_type,
                status=RecoveryActionStatus.BLOCKED,
                risk_level=evaluation.risk_level,
                metadata={
                    "phase": 5,
                    "planned": True,
                    "executed": False,
                    "policy_version": evaluation.policy_version,
                    "reason": evaluation.reason,
                },
            )
            suspicious = "suspicious" in evaluation.reason.lower()
            mismatch = "mismatch" in evaluation.reason.lower()
            target = (
                RecoveryCaseStatus.ESCALATED
                if suspicious or mismatch
                else RecoveryCaseStatus.STOPPED
            )
            transition_case(
                self._session,
                case,
                target,
                actor_type=actor_type,
                correlation_id=correlation_id,
                summary=evaluation.reason,
                metadata={"selected_action": str(action_type), "policy_ids": evaluation.policy_ids},
            )
            self._session.flush()
            return case

        if evaluation.requires_approval:
            action = self._record_planned_action(
                case,
                action_type,
                status=RecoveryActionStatus.APPROVAL_REQUIRED,
                risk_level=evaluation.risk_level,
                metadata={
                    "phase": 5,
                    "planned": True,
                    "executed": False,
                    "tool_name": {
                        RecoveryActionType.RETRY_NOW: "retry_payment",
                        RecoveryActionType.RETRY_LATER: "schedule_retry",
                        RecoveryActionType.SEND_PAYMENT_LINK: "create_payment_link",
                        RecoveryActionType.SEND_REMINDER: "send_notification",
                        RecoveryActionType.OFFER_DISCOUNT: "offer_discount",
                        RecoveryActionType.ESCALATE: "escalate_to_human",
                        RecoveryActionType.DO_NOTHING: "pause_recovery",
                    }.get(action_type),
                    "payload": (
                        {"scheduled_for": (datetime.now(UTC) + timedelta(hours=1)).isoformat()}
                        if action_type is RecoveryActionType.RETRY_LATER
                        else {}
                    ),
                    "policy_version": evaluation.policy_version,
                },
            )
            approval = Approval(
                merchant_id=case.merchant_id,
                recovery_case_id=case.id,
                recovery_action_id=action.id if action is not None else None,
                status=ApprovalStatus.PENDING,
                requested_by="processor",
                expires_at=datetime.now(UTC)
                + timedelta(minutes=context.settings.approval_ttl_minutes),
            )
            self._session.add(approval)
            self._session.flush()
            if action is not None:
                meta = dict(action.metadata_json or {})
                meta["approval_id"] = str(approval.id)
                meta["case_fingerprint"] = {
                    "amount_at_risk": str(case.amount_at_risk),
                    "payment_id": str(case.payment_id) if case.payment_id else None,
                    "customer_id": str(case.customer_id),
                    "last_mismatch_reason": case.last_mismatch_reason,
                    "amount_recovered": str(case.amount_recovered),
                }
                meta["idempotency_key"] = action.idempotency_key
                action.metadata_json = meta
            transition_case(
                self._session,
                case,
                RecoveryCaseStatus.AWAITING_APPROVAL,
                actor_type=actor_type,
                correlation_id=correlation_id,
                summary="Policy requires human approval before execution",
                metadata={"selected_action": str(action_type), "approval_id": str(approval.id)},
            )
            self._session.flush()
            return case

        self._record_planned_action(case, action_type, risk_level=evaluation.risk_level)
        transition_case(
            self._session,
            case,
            RecoveryCaseStatus.EXECUTING,
            actor_type=actor_type,
            correlation_id=correlation_id,
            summary="Planned action recorded as ready. No financial provider call was made.",
            metadata={"selected_action": str(action_type), "executed": False},
        )
        transition_case(
            self._session,
            case,
            RecoveryCaseStatus.ACTION_COMPLETED,
            actor_type=actor_type,
            correlation_id=correlation_id,
            summary=(
                "Planned recovery action recorded as ready. No financial provider call was made."
            ),
            metadata={"selected_action": str(action_type), "action_status": "PENDING"},
        )
        self._session.flush()
        return case

    def walk_to_policy_check(
        self,
        case: RecoveryCase,
        *,
        correlation_id: str | None = None,
        actor_type: str = ActorType.WORKER,
    ) -> RecoveryCase:
        self._walk_to_policy_check(case, correlation_id=correlation_id, actor_type=actor_type)
        return case

    def _walk_to_policy_check(
        self,
        case: RecoveryCase,
        *,
        correlation_id: str | None,
        actor_type: str,
    ) -> None:
        for target, summary in PROCESS_STEPS:
            current = coerce_status(case.status)
            if current is target or _already_past(current, target):
                continue
            if current is RecoveryCaseStatus.POLICY_CHECK:
                return
            transition_case(
                self._session,
                case,
                target,
                actor_type=actor_type,
                correlation_id=correlation_id,
                summary=summary,
            )

    def _select_action(self, case: RecoveryCase) -> RecoveryActionType:
        payment: Payment | None = None
        if case.payment_id is not None:
            payment = PaymentRepository(self._session).get_payment(
                case.merchant_id, case.payment_id
            )
        failure = (payment.failure_code if payment is not None else None) or ""
        if failure in RETRYABLE_FAILURES:
            return RecoveryActionType.RETRY_LATER
        return RecoveryActionType.SEND_PAYMENT_LINK

    def _record_planned_action(
        self,
        case: RecoveryCase,
        action_type: RecoveryActionType,
        *,
        status: RecoveryActionStatus = RecoveryActionStatus.PENDING,
        risk_level: RiskLevel = RiskLevel.GREEN,
        metadata: dict[str, object] | None = None,
    ) -> RecoveryAction | None:
        idempotency_key = f"phase5:{case.id}:{action_type}:1"
        existing = self._session.scalar(
            select(RecoveryAction).where(
                RecoveryAction.merchant_id == case.merchant_id,
                RecoveryAction.idempotency_key == idempotency_key,
            )
        )
        if existing is not None:
            return existing
        action = RecoveryAction(
            merchant_id=case.merchant_id,
            recovery_case_id=case.id,
            action_type=str(action_type),
            status=str(status),
            idempotency_key=idempotency_key,
            attempt_number=1,
            risk_level=str(risk_level),
            amount=case.amount_at_risk,
            currency=case.currency,
            metadata_json=metadata
            or {
                "phase": 5,
                "planned": True,
                "executed": False,
                "rule": "phase5_deterministic",
            },
        )
        self._session.add(action)
        self._session.flush()
        self._session.add(
            RecoveryDecision(
                merchant_id=case.merchant_id,
                recovery_case_id=case.id,
                recovery_action_id=action.id,
                decision_version="phase5-policy",
                selected_action=str(action_type),
                candidate_actions={"actions": [str(action_type)]},
                expected_values={},
                policy_verdict="ALLOW" if status != RecoveryActionStatus.BLOCKED else "DENY",
                explanation=(
                    "Deterministic rule: RETRY_LATER for retryable bank/network "
                    "failures, otherwise SEND_PAYMENT_LINK. Policy engine is authoritative."
                ),
                decision_factors={"rule": "phase5_deterministic", "failure_code": True},
            )
        )
        return action


def _already_past(current: RecoveryCaseStatus, target: RecoveryCaseStatus) -> bool:
    order = [
        RecoveryCaseStatus.DETECTED,
        RecoveryCaseStatus.TRIAGED,
        RecoveryCaseStatus.INVESTIGATING,
        RecoveryCaseStatus.DIAGNOSED,
        RecoveryCaseStatus.SCORING,
        RecoveryCaseStatus.STRATEGY_SELECTED,
        RecoveryCaseStatus.POLICY_CHECK,
        RecoveryCaseStatus.AWAITING_APPROVAL,
        RecoveryCaseStatus.EXECUTING,
        RecoveryCaseStatus.ACTION_COMPLETED,
    ]
    try:
        return order.index(current) > order.index(target)
    except ValueError:
        return False


def process_recovery_case(
    session: Session,
    case_id: UUID,
    *,
    correlation_id: str | None = None,
) -> dict[str, str]:
    case = RecoveryCaseProcessor(session).process(case_id, correlation_id=correlation_id)
    return {"status": case.status, "case_id": str(case.id), "version": str(case.version)}


def verify_recovery_case(
    session: Session,
    case_id: UUID,
    *,
    payment_id: UUID | None = None,
    webhook_event_id: UUID | None = None,
    correlation_id: str | None = None,
) -> dict[str, str | bool | list[str] | None]:
    from recoverai_domain.verification import RecoveryVerificationService

    result = RecoveryVerificationService(session).verify_case(
        case_id,
        payment_id=payment_id,
        webhook_event_id=webhook_event_id,
        correlation_id=correlation_id,
    )
    return result.to_public_dict()
