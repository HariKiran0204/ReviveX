from __future__ import annotations

from recoverai_db.enums import RecoveryActionType, RecoveryCaseType
from recoverai_domain.agents.config import (
    ANALYST_VERSION,
    CARD_FAILURES,
    DIAGNOSIS_VERSION,
    EXPLAINER_VERSION,
    RETRYABLE_FAILURES,
    SOURCE_FALLBACK,
    STRATEGY_VERSION,
    TRIAGE_VERSION,
    UNRECOVERABLE_FAILURES,
    VERIFICATION_EXPLAINER_VERSION,
)
from recoverai_domain.agents.context import RecoveryAgentContext
from recoverai_domain.agents.schemas import (
    AnalystAnswer,
    DecisionExplanation,
    DiagnosisResult,
    StrategyResult,
    TriageResult,
    VerificationExplanation,
)
from recoverai_domain.optimizer.config import LEGAL_ACTIONS
from recoverai_domain.optimizer.types import OptimizationResult


def fallback_triage(context: RecoveryAgentContext) -> TriageResult:
    case_type = RecoveryCaseType(context.case["case_type"])
    amount = float(context.case["amount_at_risk"])
    if amount > 25000:
        severity: str = "HIGH"
    elif amount > 5000:
        severity = "MEDIUM"
    else:
        severity = "LOW"
    return TriageResult(
        case_type=case_type,
        severity=severity,  # type: ignore[arg-type]
        investigation_needed=case_type != RecoveryCaseType.FAILED_PAYMENT or severity != "LOW",
        relevant_context=_relevant(context),
        source=SOURCE_FALLBACK,
        agent_version=TRIAGE_VERSION,
    )


def fallback_diagnosis(context: RecoveryAgentContext) -> DiagnosisResult:
    code = (context.payment or {}).get("failure_code") or "UNKNOWN"
    if code in UNRECOVERABLE_FAILURES:
        recoverability = "UNRECOVERABLE"
        confidence = 0.92
        cause = f"Failure {code} is treated as largely unrecoverable by automated payment tools"
    elif code in RETRYABLE_FAILURES:
        recoverability = "HIGH" if code != "INSUFFICIENT_FUNDS" else "MEDIUM"
        confidence = 0.88
        cause = f"Known retryable failure {code}"
    elif code in CARD_FAILURES:
        recoverability = "MEDIUM"
        confidence = 0.8
        cause = f"Instrument failure {code}; a new payment method or link is more likely"
    else:
        recoverability = "LOW"
        confidence = 0.45
        cause = f"Ambiguous or unknown failure ({code})"
    evidence = [f"failure_code={code}"]
    if context.injection_suspected:
        evidence.append("Customer text treated as untrusted data and ignored as instructions")
    return DiagnosisResult(
        root_cause=cause,
        confidence=confidence,
        evidence=evidence,
        recoverability=recoverability,  # type: ignore[arg-type]
        source=SOURCE_FALLBACK,
        agent_version=DIAGNOSIS_VERSION,
    )


def fallback_strategy(context: RecoveryAgentContext, diagnosis: DiagnosisResult) -> StrategyResult:
    code = (context.payment or {}).get("failure_code") or "UNKNOWN"
    if diagnosis.recoverability == "UNRECOVERABLE" or code in UNRECOVERABLE_FAILURES:
        actions = [
            RecoveryActionType.ESCALATE.value,
            RecoveryActionType.DO_NOTHING.value,
        ]
        rationale = "Automated payment tools are unlikely to recover this failure"
    elif code in {"TEMPORARY_BANK_ERROR", "NETWORK_TIMEOUT"}:
        actions = [
            RecoveryActionType.RETRY_LATER.value,
            RecoveryActionType.RETRY_NOW.value,
            RecoveryActionType.SEND_PAYMENT_LINK.value,
            RecoveryActionType.SEND_REMINDER.value,
            RecoveryActionType.ESCALATE.value,
            RecoveryActionType.DO_NOTHING.value,
        ]
        rationale = "Temporary processor/network failure; retries and a payment link are legal"
    elif code == "INSUFFICIENT_FUNDS":
        actions = [
            RecoveryActionType.RETRY_LATER.value,
            RecoveryActionType.SEND_PAYMENT_LINK.value,
            RecoveryActionType.SEND_REMINDER.value,
            RecoveryActionType.OFFER_DISCOUNT.value,
            RecoveryActionType.ESCALATE.value,
            RecoveryActionType.DO_NOTHING.value,
        ]
        rationale = (
            "Liquidity pressure; delayed retry or a link is preferred over an immediate debit"
        )
    elif code in CARD_FAILURES:
        actions = [
            RecoveryActionType.SEND_PAYMENT_LINK.value,
            RecoveryActionType.SEND_REMINDER.value,
            RecoveryActionType.OFFER_DISCOUNT.value,
            RecoveryActionType.ESCALATE.value,
            RecoveryActionType.DO_NOTHING.value,
        ]
        rationale = (
            "Card issue; a new payment path is more useful than retrying the same instrument"
        )
    else:
        actions = list(LEGAL_ACTIONS)
        rationale = "Ambiguous failure; optimizer will rank the closed action set"
    return StrategyResult(
        candidate_actions=actions,
        rationale=rationale,
        source=SOURCE_FALLBACK,
        agent_version=STRATEGY_VERSION,
    )


def fallback_explanation(
    context: RecoveryAgentContext,
    result: OptimizationResult,
) -> DecisionExplanation:
    selected = result.selected_action
    comparison_parts: list[str] = []
    for item in result.candidate_actions[:5]:
        comparison_parts.append(f"{item.action} ERV {item.expected_value} allowed={item.allowed}")
    policy = "unknown"
    if selected:
        match = next((item for item in result.candidate_actions if item.action == selected), None)
        if match is not None:
            if not match.allowed:
                policy = "BLOCKED"
            elif match.requires_approval:
                policy = f"{match.risk_level} / approval required"
            else:
                policy = f"{match.risk_level} / automatic"
    failure = (context.payment or {}).get("failure_code") or "UNKNOWN"
    return DecisionExplanation(
        observed=f"{failure}, amount_at_risk={context.case['amount_at_risk']}",
        candidate_comparison="; ".join(comparison_parts) or "No candidates",
        selected_action=selected,
        policy=policy,
        reason=result.selection_reason,
        source=SOURCE_FALLBACK,
        agent_version=EXPLAINER_VERSION,
    )


def fallback_verification(
    *,
    matched: bool,
    mismatch_reason: str | None,
    amount_recovered: str,
) -> VerificationExplanation:
    if matched:
        summary = f"Verification matched a capture. Credited {amount_recovered}."
    else:
        summary = f"Verification did not credit recovery. Mismatch={mismatch_reason or 'NONE'}."
    return VerificationExplanation(
        matched=matched,
        summary=summary,
        mismatch_reason=mismatch_reason,
        source=SOURCE_FALLBACK,
        agent_version=VERIFICATION_EXPLAINER_VERSION,
    )


def fallback_analyst(question: str, metrics: dict[str, str]) -> AnalystAnswer:
    answer = (
        f"Revenue at risk {metrics.get('revenue_at_risk', '0')}; "
        f"verified recovered {metrics.get('revenue_recovered', '0')}; "
        f"open cases {metrics.get('open_cases', '0')}."
    )
    return AnalystAnswer(
        question=question,
        answer=answer,
        metrics=metrics,
        source=SOURCE_FALLBACK,
        agent_version=ANALYST_VERSION,
    )


def _relevant(context: RecoveryAgentContext) -> list[str]:
    items = [f"case_type={context.case['case_type']}"]
    if context.payment:
        items.append(f"failure_code={context.payment.get('failure_code')}")
    if context.cart:
        items.append("cart_present")
    if context.subscription:
        items.append("subscription_present")
    return items
