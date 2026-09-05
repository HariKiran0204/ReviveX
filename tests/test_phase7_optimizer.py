from __future__ import annotations

import ast
import inspect
from datetime import UTC, datetime, timedelta
from decimal import Decimal
from pathlib import Path
from uuid import uuid4

import pytest
from sqlalchemy.orm import Session

from recoverai_db.enums import (
    PaymentStatus,
    RecoveryActionType,
    RecoveryCaseStatus,
    RecoveryCaseType,
    RiskLevel,
)
from recoverai_db.models import (
    Customer,
    Merchant,
    ModelPrediction,
    Payment,
    RecoveryCase,
    RecoveryDecision,
)
from recoverai_domain.errors import OptimizerError
from recoverai_domain.money import ZERO
from recoverai_domain.optimizer.batch import optimize_batch
from recoverai_domain.optimizer.config import OPTIMIZER_VERSION, OptimizerSettings
from recoverai_domain.optimizer.erv import (
    discount_cost,
    expected_net_recovery,
    expected_recovered_revenue,
    probability_to_decimal,
)
from recoverai_domain.optimizer.metrics import (
    discount_spend,
    expected_recovered_revenue_for,
    expected_recovery_rate,
    intervention_cost_total,
)
from recoverai_domain.optimizer.service import RecoveryOptimizer
from recoverai_domain.optimizer.types import OptimizerCaseInput
from recoverai_domain.policy_types import PolicyEvaluationResult
from recoverai_eval.inference.api import RecoveryProbability, clear_model_cache
from recoverai_eval.inference.fallback import FALLBACK_VERSION

EXAMPLE_PROBS = {
    RecoveryActionType.RETRY_NOW.value: 0.48,
    RecoveryActionType.RETRY_LATER.value: 0.57,
    RecoveryActionType.SEND_PAYMENT_LINK.value: 0.61,
    RecoveryActionType.SEND_REMINDER.value: 0.52,
    RecoveryActionType.OFFER_DISCOUNT.value: 0.71,
    RecoveryActionType.ESCALATE.value: 0.20,
    RecoveryActionType.DO_NOTHING.value: 0.05,
}


def _allowed(reason: str = "allowed") -> PolicyEvaluationResult:
    return PolicyEvaluationResult(
        allowed=True,
        requires_approval=False,
        risk_level=RiskLevel.GREEN,
        reason=reason,
        policy_ids=["test"],
    )


def _blocked(reason: str) -> PolicyEvaluationResult:
    return PolicyEvaluationResult(
        allowed=False,
        requires_approval=False,
        risk_level=RiskLevel.RED,
        reason=reason,
        policy_ids=["test_block"],
    )


def _approval() -> PolicyEvaluationResult:
    return PolicyEvaluationResult(
        allowed=True,
        requires_approval=True,
        risk_level=RiskLevel.RED,
        reason="High-value action requires human approval",
        policy_ids=["high_value_approval_threshold"],
    )


def _input(
    amount: Decimal = Decimal("4000.00"),
    *,
    suspicious: bool = False,
    recovered: Decimal = Decimal("0.00"),
) -> OptimizerCaseInput:
    return OptimizerCaseInput(
        case_id=uuid4(),
        merchant_id=uuid4(),
        amount_at_risk=amount,
        amount_recovered=recovered,
        suspicious=suspicious,
        source_mismatch=suspicious,
        discount_percent=Decimal("5"),
        ml_context={
            "amount": float(amount),
            "failure_reason": "TEMPORARY_BANK_ERROR",
            "attempt_number": 1,
        },
    )


def _policy_map(**overrides: PolicyEvaluationResult) -> dict[str, PolicyEvaluationResult]:
    mapping = {action: _allowed() for action in EXAMPLE_PROBS}
    mapping.update(overrides)
    return mapping


def _optimize(**kwargs: object):
    optimizer = RecoveryOptimizer()
    return optimizer.optimize(
        kwargs.get("case") or _input(),  # type: ignore[arg-type]
        probabilities=kwargs.get("probabilities") or EXAMPLE_PROBS,  # type: ignore[arg-type]
        policy_results=kwargs.get("policy_results") or _policy_map(),  # type: ignore[arg-type]
    )


def _party(session: Session, suffix: str, amount: Decimal = Decimal("4000.00")):
    merchant = Merchant(name=f"Opt {suffix}", slug=f"opt-{suffix}-{uuid4().hex[:8]}")
    session.add(merchant)
    session.flush()
    customer = Customer(
        merchant_id=merchant.id,
        external_id=f"cust-{suffix}",
        email=f"{suffix}@example.test",
        lifetime_value=Decimal("0.00"),
    )
    session.add(customer)
    session.flush()
    payment = Payment(
        merchant_id=merchant.id,
        customer_id=customer.id,
        provider="simulator",
        provider_payment_id=f"pay_{suffix}_{uuid4().hex[:6]}",
        provider_order_id=f"order_{suffix}",
        amount=amount,
        currency="INR",
        status=PaymentStatus.FAILED,
        failure_code="TEMPORARY_BANK_ERROR",
        failed_at=datetime.now(UTC),
    )
    session.add(payment)
    session.flush()
    case = RecoveryCase(
        merchant_id=merchant.id,
        customer_id=customer.id,
        payment_id=payment.id,
        case_type=RecoveryCaseType.FAILED_PAYMENT,
        status=RecoveryCaseStatus.DETECTED,
        amount_at_risk=amount,
        amount_recovered=Decimal("0.00"),
        currency="INR",
        opened_at=datetime.now(UTC),
    )
    session.add(case)
    session.flush()
    return case


def test_erv_formula_and_decimal_money() -> None:
    amount = Decimal("4000.00")
    probability = probability_to_decimal(0.61)
    expected = expected_recovered_revenue(probability, amount)
    assert expected == Decimal("2440.00")
    erv = expected_net_recovery(
        probability=probability,
        amount_at_risk=amount,
        intervention_cost=Decimal("3.00"),
        discount_cost_value=Decimal("0.00"),
        communication_cost=Decimal("1.50"),
        risk_penalty=Decimal("8.00"),
    )
    assert erv == Decimal("2427.50")
    assert isinstance(erv, Decimal)
    assert isinstance(expected, Decimal)


def test_discount_cost_is_percent_of_amount_at_risk() -> None:
    assert discount_cost(Decimal("4000.00"), Decimal("5")) == Decimal("200.00")
    assert discount_cost(Decimal("4000.00"), Decimal("10")) == Decimal("400.00")


def test_intervention_cost_and_risk_penalty_are_configured() -> None:
    settings = OptimizerSettings()
    retry = settings.costs_for(RecoveryActionType.RETRY_NOW.value)
    assert retry.intervention_cost == Decimal("5.00")
    assert retry.risk_penalty == Decimal("15.00")
    escalate = settings.costs_for(RecoveryActionType.ESCALATE.value)
    assert escalate.intervention_cost == Decimal("250.00")


def test_larger_discount_can_lose_to_payment_link() -> None:
    snapshot = OptimizerCaseInput(
        case_id=uuid4(),
        merchant_id=uuid4(),
        amount_at_risk=Decimal("4000.00"),
        amount_recovered=Decimal("0.00"),
        discount_percent=Decimal("20"),
        ml_context={
            "amount": 4000.0,
            "failure_reason": "TEMPORARY_BANK_ERROR",
            "attempt_number": 1,
        },
    )
    result = RecoveryOptimizer().optimize(
        snapshot,
        probabilities=EXAMPLE_PROBS,
        policy_results=_policy_map(),
    )
    by_action = {item.action: item for item in result.candidate_actions}
    assert by_action[RecoveryActionType.OFFER_DISCOUNT.value].discount_cost == Decimal("800.00")
    assert (
        by_action[RecoveryActionType.OFFER_DISCOUNT.value].expected_value
        < by_action[RecoveryActionType.SEND_PAYMENT_LINK.value].expected_value
    )
    assert result.selected_action != RecoveryActionType.OFFER_DISCOUNT.value


def test_example_ranking_discount_vs_payment_link() -> None:
    result = _optimize()
    by_action = {item.action: item for item in result.candidate_actions}
    discount = by_action[RecoveryActionType.OFFER_DISCOUNT.value]
    link = by_action[RecoveryActionType.SEND_PAYMENT_LINK.value]
    assert discount.probability == Decimal("0.71")
    assert discount.discount_cost == Decimal("200.00")
    assert discount.expected_recovery == Decimal("2840.00")
    assert link.expected_recovery == Decimal("2440.00")
    assert discount.expected_value < discount.expected_recovery
    ranked = [item.action for item in result.candidate_actions]
    assert result.selected_action in ranked
    assert result.optimizer_version == OPTIMIZER_VERSION


def test_candidate_ranking_orders_by_erv() -> None:
    result = _optimize()
    values = [item.expected_value for item in result.candidate_actions]
    assert values == sorted(values, reverse=True)


def test_deterministic_tie_breaking_prefers_lower_friction() -> None:
    settings = OptimizerSettings()
    zero_costs = OptimizerSettings(
        retry_now=settings.do_nothing,
        retry_later=settings.do_nothing,
        send_payment_link=settings.do_nothing,
        send_reminder=settings.do_nothing,
        offer_discount=settings.do_nothing,
        escalate=settings.escalate,
        do_nothing=settings.do_nothing,
    )
    probs = {action: 0.50 for action in EXAMPLE_PROBS}
    result = RecoveryOptimizer(zero_costs).optimize(
        _input(),
        probabilities=probs,
        policy_results=_policy_map(),
    )
    assert result.selected_action == RecoveryActionType.RETRY_LATER.value


def test_negative_erv_selects_do_nothing() -> None:
    probs = {action: 0.0 for action in EXAMPLE_PROBS}
    result = _optimize(probabilities=probs)
    assert result.selected_action == RecoveryActionType.DO_NOTHING.value
    assert "negative expected value" in result.selection_reason


def test_negative_erv_high_risk_selects_escalate() -> None:
    probs = {action: 0.0 for action in EXAMPLE_PROBS}
    result = RecoveryOptimizer().optimize(
        _input(suspicious=True),
        probabilities=probs,
        policy_results=_policy_map(),
    )
    assert result.selected_action == RecoveryActionType.ESCALATE.value


def test_policy_blocked_top_action_falls_back() -> None:
    result = _optimize(
        policy_results=_policy_map(
            **{
                RecoveryActionType.OFFER_DISCOUNT.value: _blocked(
                    "Discount exceeds the maximum allowed percentage"
                )
            }
        )
    )
    assert result.selected_action != RecoveryActionType.OFFER_DISCOUNT.value
    discount = next(
        item
        for item in result.candidate_actions
        if item.action == RecoveryActionType.OFFER_DISCOUNT.value
    )
    assert discount.allowed is False
    allowed_recovery = [
        item
        for item in result.candidate_actions
        if item.allowed
        and item.action
        in {
            RecoveryActionType.RETRY_NOW.value,
            RecoveryActionType.RETRY_LATER.value,
            RecoveryActionType.SEND_PAYMENT_LINK.value,
            RecoveryActionType.SEND_REMINDER.value,
            RecoveryActionType.OFFER_DISCOUNT.value,
        }
        and item.expected_value >= ZERO
    ]
    assert (
        result.selected_action == max(allowed_recovery, key=lambda item: item.expected_value).action
    )


def test_high_value_action_requiring_approval_can_still_be_selected() -> None:
    result = _optimize(
        policy_results=_policy_map(
            **{
                action: _approval()
                for action in (
                    RecoveryActionType.RETRY_NOW.value,
                    RecoveryActionType.RETRY_LATER.value,
                    RecoveryActionType.SEND_PAYMENT_LINK.value,
                    RecoveryActionType.SEND_REMINDER.value,
                    RecoveryActionType.OFFER_DISCOUNT.value,
                )
            }
        )
    )
    assert result.selected_action is not None
    selected = next(
        item for item in result.candidate_actions if item.action == result.selected_action
    )
    assert selected.allowed is True
    assert selected.requires_approval is True
    assert result.requires_approval is True


def test_stale_prediction_is_refreshed(db_session: Session) -> None:
    case = _party(db_session, "stale")
    now = datetime.now(UTC)
    stale_at = now - timedelta(hours=3)
    for action, prob in EXAMPLE_PROBS.items():
        db_session.add(
            ModelPrediction(
                merchant_id=case.merchant_id,
                recovery_case_id=case.id,
                action=action,
                probability=Decimal(str(prob)),
                model_version="recovery-v-old",
                feature_version="features-v1",
                fingerprint=f"stale-{case.id}-{action}",
                source="ml",
                created_at=stale_at,
                updated_at=stale_at,
            )
        )
    db_session.flush()
    called: list[str] = []

    def predictor(_ctx: object, action: str) -> RecoveryProbability:
        called.append(action)
        return RecoveryProbability(
            probability=0.4,
            model_version="recovery-v-fresh",
            feature_version="features-v1",
            source="ml",
        )

    result = RecoveryOptimizer(predictor=predictor).optimize_case(
        db_session,
        case.id,
        persist=False,
        now=now,
    )
    assert called
    assert all(item.model_version == "recovery-v-fresh" for item in result.candidate_actions)


def test_fresh_prediction_is_reused(db_session: Session) -> None:
    case = _party(db_session, "fresh-cache")
    now = datetime.now(UTC)
    for action, prob in EXAMPLE_PROBS.items():
        db_session.add(
            ModelPrediction(
                merchant_id=case.merchant_id,
                recovery_case_id=case.id,
                action=action,
                probability=Decimal(str(prob)),
                model_version="recovery-v-cache",
                feature_version="features-v1",
                fingerprint=f"fresh-{case.id}-{action}",
                source="ml",
                created_at=now,
                updated_at=now,
            )
        )
    db_session.flush()

    def predictor(_ctx: object, action: str) -> RecoveryProbability:
        raise AssertionError(f"stale path used predictor for {action}")

    result = RecoveryOptimizer(predictor=predictor).optimize_case(
        db_session,
        case.id,
        persist=False,
        now=now,
    )
    assert result.candidate_actions[0].model_version == "recovery-v-cache"


def test_model_failure_uses_fallback(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path, db_session: Session
) -> None:
    monkeypatch.setenv("RECOVERAI_ML_DIR", str(tmp_path / "missing-models"))
    clear_model_cache()
    case = _party(db_session, "fallback")
    result = RecoveryOptimizer().optimize_case(db_session, case.id, persist=False)
    sources = {item.prediction_source for item in result.candidate_actions}
    assert sources == {"MODEL_FALLBACK"}
    assert result.model_version == FALLBACK_VERSION
    assert all(item.probability is not None for item in result.candidate_actions)


def test_optimizer_cannot_mutate_amount_recovered(db_session: Session) -> None:
    case = _party(db_session, "no-mutate")
    before = case.amount_recovered
    RecoveryOptimizer().optimize_case(
        db_session,
        case.id,
        persist=True,
        probabilities=EXAMPLE_PROBS,
    )
    db_session.refresh(case)
    assert case.amount_recovered == before == Decimal("0.00")


def test_historical_decisions_are_appended(db_session: Session) -> None:
    case = _party(db_session, "history")
    optimizer = RecoveryOptimizer()
    first = optimizer.optimize_case(db_session, case.id, persist=True, probabilities=EXAMPLE_PROBS)
    second = optimizer.optimize_case(db_session, case.id, persist=True, probabilities=EXAMPLE_PROBS)
    rows = (
        db_session.query(RecoveryDecision)
        .filter_by(recovery_case_id=case.id)
        .order_by(RecoveryDecision.created_at)
        .all()
    )
    assert len(rows) == 2
    assert rows[0].id != rows[1].id
    assert rows[0].decision_version == OPTIMIZER_VERSION
    assert first.decision_id == rows[0].id
    assert second.decision_id == rows[1].id


def test_optimizer_is_deterministic() -> None:
    now = datetime(2026, 9, 4, 12, 0, tzinfo=UTC)
    snapshot = _input()
    policy = _policy_map()
    first = RecoveryOptimizer().optimize(
        snapshot,
        probabilities=EXAMPLE_PROBS,
        policy_results=policy,
        now=now,
    )
    second = RecoveryOptimizer().optimize(
        snapshot,
        probabilities=EXAMPLE_PROBS,
        policy_results=policy,
        now=now,
    )
    assert first.selected_action == second.selected_action
    assert first.selected_expected_value == second.selected_expected_value
    assert [item.to_public_dict() for item in first.candidate_actions] == [
        item.to_public_dict() for item in second.candidate_actions
    ]


def test_probabilities_outside_unit_interval_rejected() -> None:
    with pytest.raises(OptimizerError) as exc:
        _optimize(probabilities={**EXAMPLE_PROBS, RecoveryActionType.RETRY_NOW.value: 1.2})
    assert exc.value.code == "INVALID_PROBABILITY"


def test_missing_candidate_probability_excluded() -> None:
    partial = {
        RecoveryActionType.RETRY_NOW.value: 0.48,
        RecoveryActionType.DO_NOTHING.value: 0.01,
        RecoveryActionType.ESCALATE.value: 0.01,
    }
    result = _optimize(probabilities=partial)
    missing = [
        item
        for item in result.candidate_actions
        if item.action == RecoveryActionType.SEND_PAYMENT_LINK.value
    ][0]
    assert missing.missing_probability is True
    assert missing.allowed is False
    assert result.selected_action == RecoveryActionType.RETRY_NOW.value


def test_batch_optimization_does_not_execute() -> None:
    cases = [(_input(), EXAMPLE_PROBS), (_input(), EXAMPLE_PROBS)]
    batch = optimize_batch(cases)
    assert batch.case_count == 2
    assert all(item.selected_action for item in batch.results)


def test_expected_metrics_distinct_from_actual_recovery() -> None:
    result = _optimize()
    selected = next(
        item for item in result.candidate_actions if item.action == result.selected_action
    )
    assert expected_recovered_revenue_for(selected) == selected.expected_recovery
    assert discount_spend(selected) == selected.discount_cost
    assert intervention_cost_total(selected) == (
        selected.intervention_cost + selected.communication_cost
    )
    assert expected_recovery_rate(result) == selected.probability
    assert selected.expected_recovery != selected.amount_at_risk or selected.probability == Decimal(
        "1"
    )


def test_optimizer_never_imports_payment_provider() -> None:
    from recoverai_domain import optimizer as package
    from recoverai_domain.optimizer import batch, persist, ranking, service

    for module in (package, service, persist, ranking, batch):
        tree = ast.parse(inspect.getsource(module))
        imported: set[str] = set()
        for node in ast.walk(tree):
            if isinstance(node, ast.Import):
                imported.update(alias.name.split(".")[0] for alias in node.names)
            if isinstance(node, ast.ImportFrom) and node.module:
                imported.add(node.module.split(".")[0])
        assert "recoverai_providers" not in imported


def test_invariants_selected_is_legal_and_max_erv() -> None:
    result = _optimize()
    eligible = [
        item for item in result.candidate_actions if item.allowed and not item.missing_probability
    ]
    selected = next(
        item for item in result.candidate_actions if item.action == result.selected_action
    )
    assert selected.action in {item.value for item in RecoveryActionType}
    assert selected.allowed is True
    recovery = {
        RecoveryActionType.RETRY_NOW.value,
        RecoveryActionType.RETRY_LATER.value,
        RecoveryActionType.SEND_PAYMENT_LINK.value,
        RecoveryActionType.SEND_REMINDER.value,
        RecoveryActionType.OFFER_DISCOUNT.value,
    }
    positive = [
        item for item in eligible if item.action in recovery and item.expected_value >= ZERO
    ]
    if positive:
        best = max(item.expected_value for item in positive)
        assert selected.expected_value >= best - Decimal("0.01")
        assert selected.action in recovery
