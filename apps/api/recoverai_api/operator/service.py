from __future__ import annotations

from datetime import datetime
from decimal import Decimal
from typing import Any
from uuid import UUID

from sqlalchemy import func, select
from sqlalchemy.orm import Session, aliased
from sqlalchemy.orm.attributes import flag_modified

from recoverai_api.operator.merchant import resolve_merchant
from recoverai_api.operator.schemas import PolicySettingsBody
from recoverai_api.operator.serialize import as_str, iso, money, public_json
from recoverai_db.enums import (
    ApprovalStatus,
    RecoveryActionStatus,
    RecoveryCaseStatus,
)
from recoverai_db.models import (
    AgentRun,
    Approval,
    Customer,
    Merchant,
    ModelPrediction,
    Payment,
    PolicyEvaluation,
    RecoveryAction,
    RecoveryCase,
    RecoveryDecision,
    ToolCall,
)
from recoverai_db.repositories import (
    AuditEventRepository,
    CustomerRepository,
    ModelPredictionRepository,
    ModelVersionRepository,
    PaymentRepository,
    RecoveryCaseRepository,
)
from recoverai_domain.errors import DomainError
from recoverai_domain.optimizer.config import LEGAL_ACTIONS
from recoverai_domain.recovery_config import load_recovery_settings
from recoverai_eval.models.versioning import load_bundle, read_production_pointer

METRIC_LABELS = {
    "revenue_at_risk": "ACTUAL amount remaining at risk on open cases",
    "revenue_recovered": ("ACTUAL verified recovery credited by RecoveryVerificationService"),
    "expected_recovery": "EXPECTED recovery from latest ERV decisions (not verified)",
}


class OperatorError(DomainError):
    def __init__(self, code: str, message: str) -> None:
        super().__init__(code, message, retryable=False)


def _latest_decision_subquery(merchant_id: UUID) -> Any:
    return (
        select(
            RecoveryDecision.recovery_case_id.label("cid"),
            func.max(RecoveryDecision.created_at).label("ts"),
        )
        .where(RecoveryDecision.merchant_id == merchant_id)
        .group_by(RecoveryDecision.recovery_case_id)
        .subquery()
    )


def _latest_prediction_subquery(merchant_id: UUID) -> Any:
    return (
        select(
            ModelPrediction.recovery_case_id.label("cid"),
            func.max(ModelPrediction.created_at).label("ts"),
        )
        .where(ModelPrediction.merchant_id == merchant_id)
        .group_by(ModelPrediction.recovery_case_id)
        .subquery()
    )


def _case_row(
    case: RecoveryCase,
    customer: Customer | None,
    payment: Payment | None,
    decision: RecoveryDecision | None,
    prediction: ModelPrediction | None,
) -> dict[str, Any]:
    selected = decision.selected_action if decision is not None else None
    probability = None
    if prediction is not None:
        probability = f"{prediction.probability:.6f}"
    return {
        "id": str(case.id),
        "merchant_id": str(case.merchant_id),
        "customer": {
            "id": str(case.customer_id),
            "full_name": customer.full_name if customer is not None else None,
            "email": customer.email if customer is not None else None,
            "external_id": customer.external_id if customer is not None else None,
        },
        "amount_at_risk": money(case.amount_at_risk),
        "amount_recovered": money(case.amount_recovered),
        "currency": case.currency,
        "case_type": case.case_type,
        "failure_reason": payment.failure_reason if payment is not None else None,
        "status": case.status,
        "recovery_probability": probability,
        "recommended_action": selected if selected not in {None, "NONE"} else None,
        "expected_recovery": money(decision.selected_expected_value) if decision else None,
        "created_at": iso(case.created_at),
        "opened_at": iso(case.opened_at),
        "closed_at": iso(case.closed_at),
    }


def command_center_metrics(
    session: Session,
    *,
    merchant_id: UUID | None,
    merchant_slug: str | None,
) -> dict[str, Any]:
    merchant = resolve_merchant(
        session, merchant_id=merchant_id, merchant_slug=merchant_slug, required=False
    )
    if merchant is None:
        return {
            "merchant": None,
            "partial": True,
            "revenue_at_risk": "0.00",
            "revenue_recovered": "0.00",
            "expected_recovery": "0.00",
            "recovery_rate": None,
            "active_cases": 0,
            "pending_approvals": 0,
            "failed_actions": 0,
            "policy_blocks": 0,
            "currency": "INR",
            "labels": METRIC_LABELS,
        }
    mid = merchant.id
    open_at_risk = session.scalar(
        select(
            func.coalesce(func.sum(RecoveryCase.amount_at_risk - RecoveryCase.amount_recovered), 0)
        ).where(
            RecoveryCase.merchant_id == mid,
            RecoveryCase.closed_at.is_(None),
        )
    )
    recovered = session.scalar(
        select(func.coalesce(func.sum(RecoveryCase.amount_recovered), 0)).where(
            RecoveryCase.merchant_id == mid
        )
    )
    latest = _latest_decision_subquery(mid)
    expected = session.scalar(
        select(func.coalesce(func.sum(RecoveryDecision.selected_expected_value), 0))
        .select_from(RecoveryDecision)
        .join(
            latest,
            (RecoveryDecision.recovery_case_id == latest.c.cid)
            & (RecoveryDecision.created_at == latest.c.ts),
        )
        .where(RecoveryDecision.merchant_id == mid)
    )
    recovered_count = (
        session.scalar(
            select(func.count())
            .select_from(RecoveryCase)
            .where(
                RecoveryCase.merchant_id == mid,
                RecoveryCase.status == RecoveryCaseStatus.RECOVERED,
            )
        )
        or 0
    )
    closed_count = (
        session.scalar(
            select(func.count())
            .select_from(RecoveryCase)
            .where(
                RecoveryCase.merchant_id == mid,
                RecoveryCase.status.in_(
                    [
                        RecoveryCaseStatus.RECOVERED,
                        RecoveryCaseStatus.NOT_RECOVERED,
                        RecoveryCaseStatus.STOPPED,
                    ]
                ),
            )
        )
        or 0
    )
    recovery_rate = None
    if closed_count:
        recovery_rate = round(float(recovered_count) / float(closed_count), 6)
    active = (
        session.scalar(
            select(func.count())
            .select_from(RecoveryCase)
            .where(RecoveryCase.merchant_id == mid, RecoveryCase.closed_at.is_(None))
        )
        or 0
    )
    pending = (
        session.scalar(
            select(func.count())
            .select_from(Approval)
            .where(Approval.merchant_id == mid, Approval.status == ApprovalStatus.PENDING)
        )
        or 0
    )
    failed_actions = (
        session.scalar(
            select(func.count())
            .select_from(RecoveryAction)
            .where(
                RecoveryAction.merchant_id == mid,
                RecoveryAction.status == RecoveryActionStatus.FAILED,
            )
        )
        or 0
    )
    policy_blocks = (
        session.scalar(
            select(func.count())
            .select_from(PolicyEvaluation)
            .where(PolicyEvaluation.merchant_id == mid, PolicyEvaluation.allowed.is_(False))
        )
        or 0
    )
    return {
        "merchant": {"id": str(merchant.id), "name": merchant.name, "slug": merchant.slug},
        "partial": False,
        "revenue_at_risk": money(Decimal(str(open_at_risk or 0))),
        "revenue_recovered": money(Decimal(str(recovered or 0))),
        "expected_recovery": money(Decimal(str(expected or 0))),
        "recovery_rate": recovery_rate,
        "active_cases": int(active),
        "pending_approvals": int(pending),
        "failed_actions": int(failed_actions),
        "policy_blocks": int(policy_blocks),
        "currency": "INR",
        "labels": METRIC_LABELS,
    }


def list_cases(
    session: Session,
    *,
    merchant_id: UUID | None,
    merchant_slug: str | None,
    status: str | None,
    case_type: str | None,
    min_amount: Decimal | None,
    max_amount: Decimal | None,
    sort: str,
    direction: str,
    page: int,
    page_size: int,
) -> dict[str, Any]:
    merchant = resolve_merchant(session, merchant_id=merchant_id, merchant_slug=merchant_slug)
    assert merchant is not None
    offset = (page - 1) * page_size
    cases, total = RecoveryCaseRepository(session).page_cases(
        merchant.id,
        status=status,
        case_type=case_type,
        min_amount=min_amount,
        max_amount=max_amount,
        sort=sort,
        direction=direction,
        offset=offset,
        limit=page_size,
    )
    if not cases:
        return {
            "merchant_id": str(merchant.id),
            "items": [],
            "page": page,
            "page_size": page_size,
            "total": total,
        }
    ids = [row.id for row in cases]
    customers = {
        row.id: row
        for row in session.scalars(
            select(Customer).where(Customer.id.in_({case.customer_id for case in cases}))
        )
    }
    payments = {
        row.id: row
        for row in session.scalars(
            select(Payment).where(
                Payment.id.in_({case.payment_id for case in cases if case.payment_id})
            )
        )
    }
    latest = _latest_decision_subquery(merchant.id)
    Dec = aliased(RecoveryDecision)
    decisions = {
        row.recovery_case_id: row
        for row in session.scalars(
            select(Dec)
            .join(latest, (Dec.recovery_case_id == latest.c.cid) & (Dec.created_at == latest.c.ts))
            .where(Dec.recovery_case_id.in_(ids))
        )
    }
    pred_latest = _latest_prediction_subquery(merchant.id)
    Pred = aliased(ModelPrediction)
    predictions = {
        row.recovery_case_id: row
        for row in session.scalars(
            select(Pred)
            .join(
                pred_latest,
                (Pred.recovery_case_id == pred_latest.c.cid)
                & (Pred.created_at == pred_latest.c.ts),
            )
            .where(Pred.recovery_case_id.in_(ids))
        )
    }
    items = [
        _case_row(
            case,
            customers.get(case.customer_id),
            payments.get(case.payment_id) if case.payment_id else None,
            decisions.get(case.id),
            predictions.get(case.id),
        )
        for case in cases
    ]
    return {
        "merchant_id": str(merchant.id),
        "items": items,
        "page": page,
        "page_size": page_size,
        "total": total,
    }


def _require_case(
    session: Session, case_id: UUID, merchant: Merchant | None = None
) -> RecoveryCase:
    case = RecoveryCaseRepository(session).get_case_unscoped(case_id)
    if case is None:
        raise OperatorError("RECOVERY_CASE_NOT_FOUND", "Recovery case was not found")
    if merchant is not None and case.merchant_id != merchant.id:
        raise OperatorError("MERCHANT_MISMATCH", "Case does not belong to the given merchant")
    return case


def get_case_detail(session: Session, case_id: UUID, merchant: Merchant | None) -> dict[str, Any]:
    case = _require_case(session, case_id, merchant)
    customer = CustomerRepository(session).get_customer(case.merchant_id, case.customer_id)
    payment = None
    if case.payment_id is not None:
        payment = PaymentRepository(session).get_payment(case.merchant_id, case.payment_id)
    decision = session.scalar(
        select(RecoveryDecision)
        .where(RecoveryDecision.recovery_case_id == case.id)
        .order_by(RecoveryDecision.created_at.desc())
        .limit(1)
    )
    predictions = ModelPredictionRepository(session).list_for_case(case.id)
    actions = list(
        session.scalars(
            select(RecoveryAction)
            .where(RecoveryAction.recovery_case_id == case.id)
            .order_by(RecoveryAction.created_at.desc())
        )
    )
    approvals = list(
        session.scalars(
            select(Approval)
            .where(Approval.recovery_case_id == case.id)
            .order_by(Approval.created_at.desc())
        )
    )
    policy_rows = list(
        session.scalars(
            select(PolicyEvaluation)
            .where(PolicyEvaluation.recovery_case_id == case.id)
            .order_by(PolicyEvaluation.evaluated_at.desc())
            .limit(20)
        )
    )
    selected_action = None
    if decision is not None and decision.selected_action not in {None, "NONE"}:
        selected_action = decision.selected_action
    pending = next((row for row in approvals if row.status == ApprovalStatus.PENDING), None)
    return {
        "case": _case_row(
            case, customer, payment, decision, predictions[0] if predictions else None
        ),
        "customer": {
            "id": as_str(customer.id) if customer else None,
            "full_name": customer.full_name if customer else None,
            "email": customer.email if customer else None,
            "phone": customer.phone if customer else None,
            "external_id": customer.external_id if customer else None,
            "lifetime_value": money(customer.lifetime_value) if customer else None,
        },
        "payment": None
        if payment is None
        else {
            "id": str(payment.id),
            "status": payment.status,
            "amount": money(payment.amount),
            "currency": payment.currency,
            "failure_reason": payment.failure_reason,
            "failure_code": payment.failure_code,
            "payment_method": payment.payment_method,
            "provider": payment.provider,
            "provider_payment_id": payment.provider_payment_id,
            "provider_order_id": payment.provider_order_id,
            "captured_at": iso(payment.captured_at),
            "failed_at": iso(payment.failed_at),
        },
        "verification": {
            "verified_payment_id": as_str(case.verified_payment_id),
            "last_mismatch_reason": case.last_mismatch_reason,
            "amount_recovered": money(case.amount_recovered),
            "amount_at_risk": money(case.amount_at_risk),
        },
        "selected_action": selected_action,
        "policy_verdict": decision.policy_verdict if decision else None,
        "approval": _approval_dict(pending) if pending else None,
        "approvals": [_approval_dict(row) for row in approvals],
        "actions": [_action_dict(row) for row in actions],
        "policy_evaluations": [_policy_eval_dict(row) for row in policy_rows],
        "predictions": [
            {
                "action": row.action,
                "probability": f"{row.probability:.6f}",
                "model_version": row.model_version,
                "source": row.source,
            }
            for row in predictions
        ],
        "decision": _decision_dict(decision) if decision else None,
    }


def get_case_decision(session: Session, case_id: UUID, merchant: Merchant | None) -> dict[str, Any]:
    case = _require_case(session, case_id, merchant)
    decision = session.scalar(
        select(RecoveryDecision)
        .where(RecoveryDecision.recovery_case_id == case.id)
        .order_by(RecoveryDecision.created_at.desc())
        .limit(1)
    )
    agent_run = session.scalar(
        select(AgentRun)
        .where(
            AgentRun.recovery_case_id == case.id,
            AgentRun.agent_name.in_(
                ["orchestrator", "diagnosis", "strategy", "decision_explainer"]
            ),
        )
        .order_by(AgentRun.created_at.desc())
        .limit(1)
    )
    orchestrator = session.scalar(
        select(AgentRun)
        .where(AgentRun.recovery_case_id == case.id, AgentRun.agent_name == "orchestrator")
        .order_by(AgentRun.created_at.desc())
        .limit(1)
    )
    source = "DETERMINISTIC_FALLBACK"
    diagnosis: dict[str, Any] | None = None
    explanation = decision.explanation if decision else None
    evidence: list[str] = []
    confidence = None
    if orchestrator is not None and isinstance(orchestrator.output_summary, dict):
        output = orchestrator.output_summary
        diagnosis = output.get("diagnosis") if isinstance(output.get("diagnosis"), dict) else None
        expl = output.get("explanation")
        if isinstance(expl, dict):
            explanation = str(expl.get("reason") or explanation or "")
            source = str(expl.get("source") or source)
        if diagnosis is not None:
            source = str(diagnosis.get("source") or source)
            confidence = diagnosis.get("confidence")
            raw_ev = diagnosis.get("evidence")
            if isinstance(raw_ev, list):
                evidence = [str(item) for item in raw_ev]
        fallbacks = output.get("fallbacks")
        if isinstance(fallbacks, list) and fallbacks:
            source = "DETERMINISTIC_FALLBACK"
        elif diagnosis and diagnosis.get("source") == "LLM":
            source = "LLM"
    elif agent_run is not None and isinstance(agent_run.decision_factors, dict):
        source = str(agent_run.decision_factors.get("source") or source)
    candidates: list[Any] = []
    if decision is not None and isinstance(decision.candidate_actions, dict):
        raw = decision.candidate_actions.get("actions")
        if isinstance(raw, list):
            candidates = raw
    return {
        "case_id": str(case.id),
        "source": source,
        "source_label": "LLM" if source == "LLM" else "DETERMINISTIC FALLBACK",
        "diagnosis": None
        if diagnosis is None
        else {
            "root_cause": diagnosis.get("root_cause"),
            "confidence": confidence,
            "evidence": evidence,
            "recoverability": diagnosis.get("recoverability"),
        },
        "confidence": confidence,
        "evidence": evidence,
        "candidate_actions": candidates,
        "model_probabilities": [
            {
                "action": row.action,
                "probability": f"{row.probability:.6f}",
                "source": row.source,
                "model_version": row.model_version,
            }
            for row in ModelPredictionRepository(session).list_for_case(case.id)
        ],
        "selected_action": decision.selected_action if decision else None,
        "expected_values": decision.expected_values if decision else {},
        "policy_result": decision.policy_verdict if decision else None,
        "explanation": explanation,
        "decision": _decision_dict(decision) if decision else None,
    }


def list_agent_runs(session: Session, case_id: UUID, merchant: Merchant | None) -> dict[str, Any]:
    case = _require_case(session, case_id, merchant)
    rows = list(
        session.scalars(
            select(AgentRun)
            .where(AgentRun.recovery_case_id == case.id)
            .order_by(AgentRun.started_at.asc())
        )
    )
    return {
        "case_id": str(case.id),
        "items": [
            {
                "id": str(row.id),
                "agent_name": row.agent_name,
                "agent_version": row.agent_version,
                "status": row.status,
                "source": (row.decision_factors or {}).get("source")
                if isinstance(row.decision_factors, dict)
                else None,
                "input_summary": public_json(row.input_summary),
                "output_summary": public_json(row.output_summary),
                "error_message": row.error_message,
                "started_at": iso(row.started_at),
                "completed_at": iso(row.completed_at),
                "latency_ms": row.latency_ms,
            }
            for row in rows
        ],
    }


def list_tool_calls(session: Session, case_id: UUID, merchant: Merchant | None) -> dict[str, Any]:
    case = _require_case(session, case_id, merchant)
    rows = list(
        session.scalars(
            select(ToolCall)
            .where(ToolCall.recovery_case_id == case.id)
            .order_by(ToolCall.created_at.asc())
        )
    )
    return {
        "case_id": str(case.id),
        "items": [
            {
                "id": str(row.id),
                "tool_name": row.tool_name,
                "tool_version": row.tool_version,
                "status": row.status,
                "request_payload": public_json(row.request_payload),
                "response_payload": public_json(row.response_payload),
                "idempotency_key": row.idempotency_key,
                "correlation_id": row.correlation_id,
                "error_code": row.error_code,
                "error_message": row.error_message,
                "latency_ms": row.latency_ms,
                "created_at": iso(row.created_at),
            }
            for row in rows
        ],
    }


def case_timeline(
    session: Session,
    case_id: UUID,
    merchant: Merchant | None,
    *,
    since: datetime | None,
) -> dict[str, Any]:
    case = _require_case(session, case_id, merchant)
    rows = AuditEventRepository(session).list_for_case_since(case.merchant_id, case.id, since=since)
    return {
        "case_id": str(case.id),
        "cursor": iso(rows[-1].created_at) if rows else iso(since),
        "items": [_audit_dict(row) for row in rows],
    }


def list_audit_events(
    session: Session,
    *,
    merchant_id: UUID | None,
    merchant_slug: str | None,
    case_id: UUID | None,
    event_type: str | None,
    actor_id: str | None,
    since: datetime | None,
    until: datetime | None,
    page: int,
    page_size: int,
) -> dict[str, Any]:
    merchant = resolve_merchant(session, merchant_id=merchant_id, merchant_slug=merchant_slug)
    assert merchant is not None
    rows, total = AuditEventRepository(session).page_events(
        merchant.id,
        case_id=case_id,
        event_type=event_type,
        actor_id=actor_id,
        since=since,
        until=until,
        offset=(page - 1) * page_size,
        limit=page_size,
    )
    return {
        "items": [_audit_dict(row) for row in rows],
        "page": page,
        "page_size": page_size,
        "total": total,
    }


def list_approvals(
    session: Session,
    *,
    merchant_id: UUID | None,
    merchant_slug: str | None,
    status: str | None,
    page: int,
    page_size: int,
) -> dict[str, Any]:
    merchant = resolve_merchant(session, merchant_id=merchant_id, merchant_slug=merchant_slug)
    assert merchant is not None
    stmt = select(Approval).where(Approval.merchant_id == merchant.id)
    count_stmt = (
        select(func.count()).select_from(Approval).where(Approval.merchant_id == merchant.id)
    )
    if status:
        stmt = stmt.where(Approval.status == status)
        count_stmt = count_stmt.where(Approval.status == status)
    total = int(session.scalar(count_stmt) or 0)
    rows = list(
        session.scalars(
            stmt.order_by(Approval.created_at.desc())
            .offset((page - 1) * page_size)
            .limit(page_size)
        )
    )
    case_ids = {row.recovery_case_id for row in rows}
    cases = (
        {
            item.id: item
            for item in session.scalars(select(RecoveryCase).where(RecoveryCase.id.in_(case_ids)))
        }
        if case_ids
        else {}
    )
    customers = (
        {
            item.id: item
            for item in session.scalars(
                select(Customer).where(
                    Customer.id.in_({case.customer_id for case in cases.values()})
                )
            )
        }
        if cases
        else {}
    )
    actions = {
        item.id: item
        for item in session.scalars(
            select(RecoveryAction).where(
                RecoveryAction.id.in_(
                    {row.recovery_action_id for row in rows if row.recovery_action_id}
                )
            )
        )
    }
    items = []
    for row in rows:
        case = cases.get(row.recovery_case_id)
        customer = customers.get(case.customer_id) if case is not None else None
        action = actions.get(row.recovery_action_id) if row.recovery_action_id else None
        payload = _approval_dict(row)
        payload["case"] = (
            None
            if case is None
            else {
                "id": str(case.id),
                "status": case.status,
                "amount_at_risk": money(case.amount_at_risk),
                "currency": case.currency,
            }
        )
        payload["customer"] = (
            None if customer is None else {"full_name": customer.full_name, "email": customer.email}
        )
        payload["proposed_action"] = action.action_type if action is not None else None
        payload["amount"] = (
            money(action.amount)
            if action is not None
            else (money(case.amount_at_risk) if case is not None else None)
        )
        payload["risk"] = action.risk_level if action is not None else None
        meta = action.metadata_json if action is not None else None
        expected = None
        if isinstance(meta, dict):
            expected = meta.get("expected_recovery") or meta.get("expected_value")
        payload["expected_value"] = str(expected) if expected is not None else None
        reason = None
        if isinstance(meta, dict):
            reason = meta.get("policy_reason") or meta.get("reason")
        payload["reason"] = row.decision_reason or reason
        items.append(payload)
    return {"items": items, "page": page, "page_size": page_size, "total": total}


def get_policy(session: Session, merchant: Merchant) -> dict[str, Any]:
    merged = load_recovery_settings().merge_merchant(merchant.settings)
    nested = merchant.settings.get("policy") if isinstance(merchant.settings, dict) else None
    blocked: list[str] = []
    if isinstance(nested, dict) and isinstance(nested.get("blocked_action_types"), list):
        blocked = [str(item) for item in nested["blocked_action_types"]]
    elif isinstance(merchant.settings, dict) and isinstance(
        merchant.settings.get("blocked_action_types"), list
    ):
        blocked = [str(item) for item in merchant.settings["blocked_action_types"]]
    return {
        "merchant": {"id": str(merchant.id), "name": merchant.name, "slug": merchant.slug},
        "source": "merchant.settings.policy merged with environment defaults",
        "policy": {
            "max_retry_attempts": merged.max_retry_attempts,
            "max_discount_percent": str(merged.max_discount_percent),
            "max_daily_discount_budget": str(merged.max_daily_discount_budget),
            "high_value_approval_threshold": str(merged.high_value_approval_threshold),
            "medium_value_approval_threshold": str(merged.medium_value_approval_threshold),
            "max_communications_per_day": merged.max_communications_per_day,
            "quiet_hours_start": merged.quiet_hours_start,
            "quiet_hours_end": merged.quiet_hours_end,
            "automatic_recovery_enabled": merged.automatic_recovery_enabled,
            "approval_ttl_minutes": merged.approval_ttl_minutes,
            "blocked_action_types": blocked,
            "policy_version": merged.policy_version,
        },
        "legal_actions": list(LEGAL_ACTIONS),
    }


def update_policy(session: Session, merchant: Merchant, body: PolicySettingsBody) -> dict[str, Any]:
    illegal = [item for item in body.blocked_action_types if item not in LEGAL_ACTIONS]
    if illegal:
        raise OperatorError(
            "INVALID_POLICY",
            f"Unknown blocked actions: {', '.join(illegal)}",
        )
    if body.medium_value_approval_threshold > body.high_value_approval_threshold:
        raise OperatorError(
            "INVALID_POLICY",
            "medium threshold cannot exceed high-value approval threshold",
        )
    current = dict(merchant.settings or {})
    policy = dict(current.get("policy") or {}) if isinstance(current.get("policy"), dict) else {}
    policy.update(
        {
            "max_retry_attempts": body.max_retry_attempts,
            "max_discount_percent": str(body.max_discount_percent),
            "max_daily_discount_budget": str(body.max_daily_discount_budget),
            "high_value_approval_threshold": str(body.high_value_approval_threshold),
            "medium_value_approval_threshold": str(body.medium_value_approval_threshold),
            "max_communications_per_day": body.max_communications_per_day,
            "quiet_hours_start": body.quiet_hours_start,
            "quiet_hours_end": body.quiet_hours_end,
            "automatic_recovery_enabled": body.automatic_recovery_enabled,
            "approval_ttl_minutes": body.approval_ttl_minutes,
            "blocked_action_types": list(body.blocked_action_types),
        }
    )
    current["policy"] = policy
    merchant.settings = current
    flag_modified(merchant, "settings")
    session.add(merchant)
    session.flush()
    session.refresh(merchant)
    return get_policy(session, merchant)


def run_batch_evaluation_service(
    *,
    n_cases: int = 100,
    seed: int = 42,
    revivex_mode: str = "ml",
    include_multi_seed: bool = True,
) -> dict[str, Any]:
    from recoverai_eval.batch_evaluation import evaluate_batch

    result = evaluate_batch(n_cases=n_cases, seed=seed, revivex_mode=revivex_mode)
    b = result.baseline_metrics
    r = result.revivex_metrics

    multi_seed_summaries = []
    if include_multi_seed:
        for s in [42, 43, 44, 45, 46]:
            res_s = evaluate_batch(n_cases=n_cases, seed=s, revivex_mode=revivex_mode)
            bs = res_s.baseline_metrics
            rs = res_s.revivex_metrics
            multi_seed_summaries.append(
                {
                    "seed": s,
                    "revenue_at_risk": money(bs.total_revenue_at_risk),
                    "baseline_recovered": money(bs.total_recovered),
                    "revivex_recovered": money(rs.total_recovered),
                    "incremental_revenue": money(res_s.incremental_revenue),
                    "recovery_uplift_percent": f"{res_s.recovery_uplift_percent:.2f}",
                    "baseline_recovery_rate": f"{bs.recovery_rate * Decimal('100'):.2f}",
                    "revivex_recovery_rate": f"{rs.recovery_rate * Decimal('100'):.2f}",
                    "baseline_cases_recovered": bs.cases_recovered,
                    "revivex_cases_recovered": rs.cases_recovered,
                }
            )

    return {
        "n_cases": result.n_cases,
        "seed": result.seed,
        "revivex_mode": result.revivex_mode,
        "ml_prediction_count": result.ml_prediction_count,
        "heuristic_fallback_count": result.heuristic_fallback_count,
        "revenue_at_risk": money(result.total_revenue_at_risk),
        "baseline_recovered": money(b.total_recovered),
        "revivex_recovered": money(r.total_recovered),
        "incremental_revenue": money(result.incremental_revenue),
        "recovery_uplift_percent": f"{result.recovery_uplift_percent:.2f}",
        "baseline_recovery_rate": f"{b.recovery_rate * Decimal('100'):.2f}",
        "revivex_recovery_rate": f"{r.recovery_rate * Decimal('100'):.2f}",
        "baseline_cases_recovered": b.cases_recovered,
        "revivex_cases_recovered": r.cases_recovered,
        "baseline_net_recovery": money(b.net_recovery),
        "revivex_net_recovery": money(r.net_recovery),
        "multi_seed_results": multi_seed_summaries,
    }


def latest_evaluation(session: Session) -> dict[str, Any]:
    repo = ModelVersionRepository(session)
    row = repo.get_production() or repo.get_latest()
    file_meta: dict[str, Any] = {}
    pointer = read_production_pointer()
    if pointer is not None:
        try:
            _pipeline, file_meta = load_bundle(pointer)
        except Exception:
            file_meta = {"model_version": pointer, "unavailable": True}
    metrics = row.metrics if row is not None else file_meta.get("test")
    if row is not None and isinstance(row.metrics, dict):
        test = row.metrics.get("test") if isinstance(row.metrics.get("test"), dict) else row.metrics
    elif isinstance(file_meta.get("test"), dict):
        test = file_meta["test"]
    else:
        test = {}
    calibration = {}
    if isinstance(file_meta.get("calibration"), dict):
        calibration = file_meta["calibration"]
    elif isinstance(metrics, dict) and isinstance(metrics.get("calibration"), dict):
        calibration = metrics["calibration"]
    business = (
        file_meta.get("business_sense")
        if isinstance(file_meta.get("business_sense"), dict)
        else None
    )
    batch_summary = run_batch_evaluation_service(
        n_cases=100, seed=42, revivex_mode="ml", include_multi_seed=True
    )
    return {
        "available": row is not None or bool(file_meta),
        "synthetic": True,
        "label": "Held-out synthetic/simulation metrics. Not production Razorpay results.",
        "model_version": row.version if row is not None else file_meta.get("model_version"),
        "dataset_version": row.dataset_version
        if row is not None
        else file_meta.get("dataset_version"),
        "algorithm": row.algorithm if row is not None else file_meta.get("algorithm"),
        "quality_passed": row.quality_passed if row is not None else None,
        "is_production": row.is_production if row is not None else False,
        "trained_at": iso(row.trained_at) if row is not None else file_meta.get("trained_at"),
        "roc_auc": test.get("roc_auc") if isinstance(test, dict) else None,
        "pr_auc": test.get("pr_auc") if isinstance(test, dict) else None,
        "brier": test.get("brier") if isinstance(test, dict) else None,
        "ece": calibration.get("ece"),
        "calibration": calibration,
        "held_out_metrics": test if isinstance(test, dict) else {},
        "business_sense": business,
        "baseline_vs_optimizer": batch_summary,
    }


def _audit_dict(row: Any) -> dict[str, Any]:
    return {
        "id": str(row.id),
        "timestamp": iso(row.created_at),
        "actor_type": row.actor_type,
        "actor_id": row.actor_id,
        "event_type": row.event_type,
        "action": row.action,
        "previous_state": row.previous_state,
        "new_state": row.new_state,
        "summary": row.summary,
        "correlation_id": row.correlation_id,
        "idempotency_key": row.idempotency_key,
        "case_id": as_str(row.case_id),
        "metadata": public_json(row.metadata_json),
    }


def _approval_dict(row: Approval) -> dict[str, Any]:
    return {
        "id": str(row.id),
        "case_id": str(row.recovery_case_id),
        "action_id": as_str(row.recovery_action_id),
        "status": row.status,
        "requested_by": row.requested_by,
        "decided_by": row.decided_by,
        "decision_reason": row.decision_reason,
        "expires_at": iso(row.expires_at),
        "decided_at": iso(row.decided_at),
        "created_at": iso(row.created_at),
    }


def _action_dict(row: RecoveryAction) -> dict[str, Any]:
    return {
        "id": str(row.id),
        "action_type": row.action_type,
        "status": row.status,
        "risk_level": row.risk_level,
        "amount": money(row.amount),
        "currency": row.currency,
        "idempotency_key": row.idempotency_key,
        "error_code": row.error_code,
        "error_message": row.error_message,
        "executed_at": iso(row.executed_at),
        "created_at": iso(row.created_at),
        "metadata": public_json(row.metadata_json),
    }


def _policy_eval_dict(row: PolicyEvaluation) -> dict[str, Any]:
    return {
        "id": str(row.id),
        "action": row.action,
        "allowed": row.allowed,
        "requires_approval": row.requires_approval,
        "risk_level": row.risk_level,
        "reason": row.reason,
        "policy_version": row.policy_version,
        "evaluated_at": iso(row.evaluated_at),
    }


def _decision_dict(row: RecoveryDecision) -> dict[str, Any]:
    return {
        "id": str(row.id),
        "selected_action": row.selected_action,
        "selected_expected_value": money(row.selected_expected_value),
        "policy_verdict": row.policy_verdict,
        "explanation": row.explanation,
        "model_version": row.model_version,
        "decision_version": row.decision_version,
        "candidate_actions": row.candidate_actions,
        "expected_values": row.expected_values,
        "decision_factors": public_json(row.decision_factors),
        "created_at": iso(row.created_at),
    }
