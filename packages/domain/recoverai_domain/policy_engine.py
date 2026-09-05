from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, datetime
from decimal import Decimal

from sqlalchemy.orm import Session

from recoverai_db.enums import RecoveryActionType, RiskLevel
from recoverai_db.models import PolicyEvaluation
from recoverai_domain.audit import AuditEventType
from recoverai_domain.audit_write import record_audit
from recoverai_domain.money import as_money
from recoverai_domain.policy_types import (
    AUTOMATIC_ACTIONS,
    COMMUNICATION_ACTIONS,
    RETRY_ACTIONS,
    PolicyContext,
    PolicyEvaluationResult,
    ProposedAction,
)
from recoverai_domain.recovery_config import POLICY_VERSION, RecoverySettings


@dataclass(frozen=True)
class _RuleHit:
    policy_id: str
    allowed: bool | None = None
    requires_approval: bool | None = None
    risk_level: RiskLevel | None = None
    reason: str = ""


_RISK_RANK = {RiskLevel.GREEN: 0, RiskLevel.YELLOW: 1, RiskLevel.RED: 2}


class PolicyEngine:
    """Deterministic, fail-closed policy evaluation. Tools do not embed this logic."""

    def __init__(self, settings: RecoverySettings | None = None) -> None:
        self._defaults = settings

    def evaluate_action(
        self, context: PolicyContext, proposed_action: ProposedAction
    ) -> PolicyEvaluationResult:
        settings = context.settings
        action = proposed_action.action_type
        hits: list[_RuleHit] = []

        parsed = _parse_action(action)
        if parsed is None:
            return PolicyEvaluationResult(
                allowed=False,
                requires_approval=False,
                risk_level=RiskLevel.RED,
                reason="Unknown action is rejected before execution",
                policy_ids=["closed_action_enum"],
                policy_version=settings.policy_version or POLICY_VERSION,
            )

        hits.append(_value_risk(context, parsed))
        hits.extend(_restriction_rules(context, parsed, proposed_action, settings))

        allowed = True
        requires_approval = False
        risk = RiskLevel.GREEN
        reasons: list[str] = []
        policy_ids: list[str] = []
        for hit in hits:
            policy_ids.append(hit.policy_id)
            if hit.allowed is False:
                allowed = False
            if hit.requires_approval:
                requires_approval = True
            if hit.risk_level is not None and _RISK_RANK[hit.risk_level] > _RISK_RANK[risk]:
                risk = hit.risk_level
            if hit.reason:
                reasons.append(hit.reason)

        if not allowed:
            requires_approval = False
        if not reasons:
            reasons.append("Default safe policy allowed the proposed action")

        return PolicyEvaluationResult(
            allowed=allowed,
            requires_approval=requires_approval and allowed,
            risk_level=risk,
            reason="; ".join(reasons),
            policy_ids=policy_ids,
            policy_version=settings.policy_version or POLICY_VERSION,
        )

    def evaluate_and_persist(
        self,
        session: Session,
        context: PolicyContext,
        proposed_action: ProposedAction,
        *,
        recovery_action_id: object | None = None,
        correlation_id: str | None = None,
        actor_type: str = "SYSTEM",
        actor_id: str | None = None,
    ) -> PolicyEvaluationResult:
        result = self.evaluate_action(context, proposed_action)
        persist_policy_evaluation(
            session,
            context,
            proposed_action,
            result,
            recovery_action_id=recovery_action_id,
            correlation_id=correlation_id,
            actor_type=actor_type,
            actor_id=actor_id,
        )
        return result


def persist_policy_evaluation(
    session: Session,
    context: PolicyContext,
    proposed_action: ProposedAction,
    result: PolicyEvaluationResult,
    *,
    recovery_action_id: object | None = None,
    correlation_id: str | None = None,
    actor_type: str = "SYSTEM",
    actor_id: str | None = None,
) -> PolicyEvaluation:
    now = datetime.now(UTC)
    row = PolicyEvaluation(
        merchant_id=context.case.merchant_id,
        recovery_case_id=context.case.id,
        recovery_action_id=recovery_action_id,
        policy_version=result.policy_version,
        action=proposed_action.action_type,
        risk_level=str(result.risk_level),
        allowed=result.allowed,
        requires_approval=result.requires_approval,
        reason=result.reason,
        policy_ids=list(result.policy_ids),
        evaluated_at=now,
        metadata_json={
            "correlation_id": correlation_id,
            "amount_at_risk": str(context.case.amount_at_risk),
            "discount_percent": (
                str(proposed_action.discount_percent)
                if proposed_action.discount_percent is not None
                else None
            ),
        },
    )
    session.add(row)
    session.flush()
    record_audit(
        session,
        merchant_id=context.case.merchant_id,
        case_id=context.case.id,
        event_type=AuditEventType.POLICY_EVALUATED,
        summary=f"Policy evaluated {proposed_action.action_type}: {result.reason}",
        actor_type=actor_type,
        actor_id=actor_id,
        action=proposed_action.action_type,
        correlation_id=correlation_id,
        metadata={
            "case_id": str(context.case.id),
            "merchant_id": str(context.case.merchant_id),
            "policy_version": result.policy_version,
            "allowed": result.allowed,
            "requires_approval": result.requires_approval,
            "risk_level": str(result.risk_level),
            "policy_ids": list(result.policy_ids),
            "policy_evaluation_id": str(row.id),
        },
    )
    return row


def _parse_action(action: str) -> RecoveryActionType | None:
    try:
        return RecoveryActionType(action)
    except ValueError:
        return None


def _value_risk(context: PolicyContext, action: RecoveryActionType) -> _RuleHit:
    amount = as_money(context.case.amount_at_risk)
    settings = context.settings
    if action in {RecoveryActionType.ESCALATE, RecoveryActionType.DO_NOTHING}:
        return _RuleHit(
            policy_id="value_threshold",
            allowed=True,
            requires_approval=False,
            risk_level=RiskLevel.GREEN,
            reason="Human-path action does not require automatic recovery",
        )
    if amount > settings.high_value_approval_threshold:
        return _RuleHit(
            policy_id="high_value_approval_threshold",
            allowed=True,
            requires_approval=True,
            risk_level=RiskLevel.RED,
            reason="High-value action requires human approval",
        )
    if amount > settings.medium_value_approval_threshold:
        return _RuleHit(
            policy_id="medium_value_approval_threshold",
            allowed=True,
            requires_approval=True,
            risk_level=RiskLevel.YELLOW,
            reason="Medium-value action requires human approval",
        )
    return _RuleHit(
        policy_id="value_threshold",
        allowed=True,
        requires_approval=False,
        risk_level=RiskLevel.GREEN,
        reason="Low-value action may execute automatically when other rules allow",
    )


def _restriction_rules(
    context: PolicyContext,
    action: RecoveryActionType,
    proposed: ProposedAction,
    settings: RecoverySettings,
) -> list[_RuleHit]:
    hits: list[_RuleHit] = []
    if action in context.blocked_action_types or str(action) in context.blocked_action_types:
        hits.append(
            _RuleHit(
                policy_id="blocked_action_types",
                allowed=False,
                risk_level=RiskLevel.RED,
                reason=f"Action {action} is blocked by merchant policy",
            )
        )
    if not settings.automatic_recovery_enabled and action in AUTOMATIC_ACTIONS:
        hits.append(
            _RuleHit(
                policy_id="automatic_recovery_kill_switch",
                allowed=False,
                risk_level=RiskLevel.RED,
                reason="Automatic recovery is disabled by the merchant kill switch",
            )
        )
    if (context.suspicious or context.source_mismatch) and action in AUTOMATIC_ACTIONS:
        hits.append(
            _RuleHit(
                policy_id="suspicious_source_mismatch",
                allowed=False,
                risk_level=RiskLevel.RED,
                reason="Suspicious or source-mismatch cases cannot run automatic recovery",
            )
        )
    if action in RETRY_ACTIONS and context.retry_count >= settings.max_retry_attempts:
        hits.append(
            _RuleHit(
                policy_id="max_retry_attempts",
                allowed=False,
                risk_level=RiskLevel.RED,
                reason="Retry attempt limit has been reached",
            )
        )
    if action is RecoveryActionType.OFFER_DISCOUNT:
        hits.extend(_discount_rules(context, proposed, settings))
    if action in COMMUNICATION_ACTIONS:
        hits.extend(_communication_rules(context, action, settings))
    return hits


def _discount_rules(
    context: PolicyContext, proposed: ProposedAction, settings: RecoverySettings
) -> list[_RuleHit]:
    hits: list[_RuleHit] = []
    percent = proposed.discount_percent
    if percent is None:
        hits.append(
            _RuleHit(
                policy_id="max_discount_percent",
                allowed=False,
                risk_level=RiskLevel.RED,
                reason="Discount percentage is required",
            )
        )
        return hits
    if percent > settings.max_discount_percent:
        hits.append(
            _RuleHit(
                policy_id="max_discount_percent",
                allowed=False,
                risk_level=RiskLevel.RED,
                reason="Discount exceeds the maximum allowed percentage",
            )
        )
    if not context.discount_eligible:
        hits.append(
            _RuleHit(
                policy_id="discount_eligibility",
                allowed=False,
                risk_level=RiskLevel.RED,
                reason="Customer is not eligible for a discount",
            )
        )
    amount = proposed.discount_amount
    if amount is None:
        amount = (as_money(context.case.amount_at_risk) * percent) / Decimal("100")
    projected = context.discount_spent_today + amount
    if projected > settings.max_daily_discount_budget:
        hits.append(
            _RuleHit(
                policy_id="daily_discount_budget",
                allowed=False,
                risk_level=RiskLevel.RED,
                reason="Daily discount budget would be exceeded",
            )
        )
    if percent > 0:
        hits.append(
            _RuleHit(
                policy_id="discount_recorded",
                risk_level=RiskLevel.YELLOW,
                reason="Discount is bounded by percentage and daily budget",
            )
        )
    return hits


def _communication_rules(
    context: PolicyContext, action: RecoveryActionType, settings: RecoverySettings
) -> list[_RuleHit]:
    hits: list[_RuleHit] = []
    if context.customer_opted_out:
        hits.append(
            _RuleHit(
                policy_id="customer_communication_opt_out",
                allowed=False,
                risk_level=RiskLevel.RED,
                reason="Customer has opted out of recovery communications",
            )
        )
    if context.communications_last_24h >= settings.max_communications_per_day:
        hits.append(
            _RuleHit(
                policy_id="communication_frequency",
                allowed=False,
                risk_level=RiskLevel.YELLOW,
                reason="Communication frequency limit has been reached",
            )
        )
    if action is RecoveryActionType.SEND_REMINDER and _in_quiet_hours(context, settings):
        hits.append(
            _RuleHit(
                policy_id="quiet_hours",
                allowed=False,
                risk_level=RiskLevel.YELLOW,
                reason="Quiet hours currently prohibit outbound reminders",
            )
        )
    return hits


def _in_quiet_hours(context: PolicyContext, settings: RecoverySettings) -> bool:
    hour = context.now.hour
    start = settings.quiet_hours_start
    end = settings.quiet_hours_end
    if start == end:
        return False
    if start < end:
        return start <= hour < end
    return hour >= start or hour < end
