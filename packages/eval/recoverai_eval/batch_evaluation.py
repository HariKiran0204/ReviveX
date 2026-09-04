"""Batch-level baseline vs ReviveX revenue recovery evaluation.

This module provides deterministic comparison of recovery strategies on
simulated revenue-at-risk cases, measuring actual recovered revenue rather
than just predicted probabilities.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import random
from dataclasses import dataclass, field
from decimal import Decimal
from typing import Any

from recoverai_db.enums import (
    RecoveryActionType,
    RecoveryCaseStatus,
    RecoveryCaseType,
)
from recoverai_providers.models import CustomerHistory, FailureReason
from recoverai_providers.simulator.interventions import (
    InterventionContext,
    intervention_recovery_probability,
    SCORABLE_ACTIONS,
)
from recoverai_eval.data.generate import generate_cases


@dataclass
class CaseEvaluationResult:
    """Result of evaluating a single case under a strategy."""

    case_id: str
    amount_at_risk: Decimal
    action: str | None
    recovered: bool
    recovered_amount: Decimal
    cost: Decimal
    final_status: str
    probability_source: str | None = None


@dataclass
class BatchEvaluationMetrics:
    """Aggregate metrics for a batch evaluation."""

    total_revenue_at_risk: Decimal
    total_recovered: Decimal
    recovery_rate: Decimal
    cases_recovered: int
    total_cases: int
    total_cost: Decimal
    net_recovery: Decimal
    cases_escalated: int = 0
    cases_stopped: int = 0


@dataclass
class BatchComparisonResult:
    """Result of comparing baseline vs ReviveX strategies."""

    n_cases: int
    seed: int
    total_revenue_at_risk: Decimal

    baseline_metrics: BatchEvaluationMetrics
    revivex_metrics: BatchEvaluationMetrics

    incremental_revenue: Decimal
    recovery_uplift_percent: Decimal

    revivex_mode: str = "ml"
    ml_prediction_count: int = 0
    heuristic_fallback_count: int = 0

    case_results: list[dict[str, Any]] = field(default_factory=list)


def _deterministic_rng(seed: int, case_id: str, strategy: str | None = None) -> random.Random:
    """Create a deterministic RNG for a case (paired counterfactual draw)."""
    payload = f"{seed}:{case_id}".encode()
    digest = hashlib.sha256(payload).digest()
    return random.Random(int.from_bytes(digest[:8], "big"))


def _intervention_context_from_case(case: dict[str, Any]) -> InterventionContext:
    """Convert generated case dict to InterventionContext."""
    failure = FailureReason(str(case["failure_reason"]))
    history = CustomerHistory(
        prior_failures=int(case["prior_failures"]),
        prior_captures=int(case["prior_captures"]),
        lifetime_value=Decimal(str(case["customer_lifetime_value"])),
    )
    return InterventionContext(
        failure_reason=failure,
        attempt_number=int(case["attempt_number"]),
        history=history,
        historical_success_rate=float(case["historical_success_rate"]),
        historical_recovery_rate=float(case["historical_recovery_rate"]),
        communication_count=int(case["communication_count"]),
        previous_discount_usage=float(case["previous_discount_usage"]),
        cart_age_hours=float(case["cart_age_hours"]) if case.get("cart_age_hours") else None,
        customer_lifetime_value=Decimal(str(case["customer_lifetime_value"])),
        amount=Decimal(str(case["amount"])),
        hour_of_day=int(case["hour_of_day"]),
        case_type=str(case["case_type"]),
    )


def _baseline_strategy(
    case: dict[str, Any],
    *,
    rng: random.Random,
) -> str:
    """Simple baseline: DO_NOTHING (no intervention).

    This represents a passive baseline where no recovery actions are taken.
    Revenue recovery relies only on organic customer behavior.
    """
    return RecoveryActionType.DO_NOTHING.value


def _revivex_strategy(
    case: dict[str, Any],
    *,
    rng: random.Random,
    mode: str = "ml",
) -> tuple[str, str]:
    """ReviveX strategy: use ERV optimizer to select best action.

    Supports 'ml' mode (using trained ML model predictions) and 'heuristic' mode.
    Selects action with highest Expected Net Recovery Value (ERV), accounting for
    intervention costs, discount costs, communication costs, and risk penalties.
    Returns (selected_action, probability_source).
    """
    ctx = _intervention_context_from_case(case)
    amount = ctx.amount

    best_action = None
    best_erv = Decimal("-999999")
    used_source = "heuristic" if mode == "heuristic" else "ml"

    probs: dict[str, Decimal] = {}
    if mode == "ml":
        from recoverai_eval.inference.api import predict_recovery_probability
        from recoverai_eval.schema import CaseContext

        ctx_dict = {k: v for k, v in case.items() if k in CaseContext.model_fields}
        sources: list[str] = []
        try:
            for action in SCORABLE_ACTIONS:
                pred = predict_recovery_probability(ctx_dict, action)
                if pred.source == "ml":
                    probs[action] = Decimal(str(round(pred.probability, 6)))
                    sources.append("ml")
                else:
                    probs[action] = intervention_recovery_probability(ctx, action)
                    sources.append("heuristic_fallback")
            if any(s == "heuristic_fallback" for s in sources):
                used_source = "heuristic_fallback"
        except Exception:
            probs = {action: intervention_recovery_probability(ctx, action) for action in SCORABLE_ACTIONS}
            used_source = "heuristic_fallback"
    else:
        probs = {action: intervention_recovery_probability(ctx, action) for action in SCORABLE_ACTIONS}
        used_source = "heuristic"

    for action in SCORABLE_ACTIONS:
        prob = probs[action]
        cost = _action_cost(action, amount)

        # Calculate Expected Net Recovery Value
        expected_revenue = prob * amount
        erv = expected_revenue - cost

        if erv > best_erv:
            best_erv = erv
            best_action = action

    selected = best_action if best_action else RecoveryActionType.DO_NOTHING.value
    return selected, used_source


def _action_cost(action: str, amount: Decimal) -> Decimal:
    """Calculate intervention cost for an action."""
    # Simplified cost model (matches optimizer settings)
    costs = {
        RecoveryActionType.RETRY_NOW.value: Decimal("5.00"),
        RecoveryActionType.RETRY_LATER.value: Decimal("2.00"),
        RecoveryActionType.SEND_PAYMENT_LINK.value: Decimal("3.00"),
        RecoveryActionType.SEND_REMINDER.value: Decimal("0.50"),
        RecoveryActionType.OFFER_DISCOUNT.value: Decimal("1.00"),
        RecoveryActionType.ESCALATE.value: Decimal("250.00"),
        RecoveryActionType.DO_NOTHING.value: Decimal("0.00"),
    }
    risk_penalties = {
        RecoveryActionType.RETRY_NOW.value: Decimal("15.00"),
        RecoveryActionType.RETRY_LATER.value: Decimal("4.00"),
        RecoveryActionType.SEND_PAYMENT_LINK.value: Decimal("8.00"),
        RecoveryActionType.SEND_REMINDER.value: Decimal("12.00"),
        RecoveryActionType.OFFER_DISCOUNT.value: Decimal("40.00"),
        RecoveryActionType.ESCALATE.value: Decimal("30.00"),
        RecoveryActionType.DO_NOTHING.value: Decimal("0.00"),
    }
    base_cost = costs.get(action, Decimal("0.00"))
    risk_penalty = risk_penalties.get(action, Decimal("0.00"))

    # Add discount cost if applicable
    discount_cost = Decimal("0.00")
    if action == RecoveryActionType.OFFER_DISCOUNT.value:
        discount_cost = amount * Decimal("0.05")  # 5% default discount

    # Add communication cost for communication-heavy actions
    communication_cost = Decimal("0.00")
    if action in (
        RecoveryActionType.SEND_PAYMENT_LINK.value,
        RecoveryActionType.SEND_REMINDER.value,
        RecoveryActionType.OFFER_DISCOUNT.value,
    ):
        communication_cost = Decimal("1.50")

    return base_cost + discount_cost + communication_cost + risk_penalty


def _simulate_outcome(
    case: dict[str, Any],
    action: str,
    *,
    rng: random.Random,
) -> tuple[bool, Decimal, str]:
    """Simulate the outcome of an intervention using action-conditioned probabilities."""
    ctx = _intervention_context_from_case(case)
    amount = ctx.amount

    # Get the true action-conditioned recovery probability from simulator
    prob = float(intervention_recovery_probability(ctx, action))

    # Roll the outcome using action-conditioned probability
    recovered = rng.random() < prob
    recovered_amount = amount if recovered else Decimal("0.00")

    # Map status to recovery case status
    if recovered:
        final_status = RecoveryCaseStatus.RECOVERED.value
    elif action == RecoveryActionType.ESCALATE.value:
        final_status = RecoveryCaseStatus.ESCALATED.value
    elif action == RecoveryActionType.DO_NOTHING.value:
        final_status = RecoveryCaseStatus.STOPPED.value
    else:
        final_status = RecoveryCaseStatus.FAILED.value

    return recovered, recovered_amount, final_status


def _evaluate_case(
    case: dict[str, Any],
    strategy: str,
    *,
    seed: int,
    revivex_mode: str = "ml",
) -> CaseEvaluationResult:
    """Evaluate a single case under a given strategy."""
    rng = _deterministic_rng(seed, str(case["case_id"]), strategy)
    probability_source = None

    if strategy == "baseline":
        action = _baseline_strategy(case, rng=rng)
    elif strategy == "revivex":
        action, probability_source = _revivex_strategy(case, rng=rng, mode=revivex_mode)
    else:
        raise ValueError(f"Unknown strategy: {strategy}")

    recovered, recovered_amount, final_status = _simulate_outcome(
        case, action, rng=rng
    )
    cost = _action_cost(action, Decimal(str(case["amount"])))

    return CaseEvaluationResult(
        case_id=str(case["case_id"]),
        amount_at_risk=Decimal(str(case["amount"])),
        action=action,
        recovered=recovered,
        recovered_amount=recovered_amount,
        cost=cost,
        final_status=final_status,
        probability_source=probability_source,
    )


def _compute_metrics(results: list[CaseEvaluationResult]) -> BatchEvaluationMetrics:
    """Compute aggregate metrics from case results."""
    total_at_risk = sum(r.amount_at_risk for r in results)
    total_recovered = sum(r.recovered_amount for r in results)
    total_cost = sum(r.cost for r in results)
    cases_recovered = sum(1 for r in results if r.recovered)
    cases_escalated = sum(1 for r in results if r.final_status == RecoveryCaseStatus.ESCALATED.value)
    cases_stopped = sum(1 for r in results if r.final_status == RecoveryCaseStatus.STOPPED.value)

    recovery_rate = (
        total_recovered / total_at_risk if total_at_risk > 0 else Decimal("0.00")
    )
    net_recovery = total_recovered - total_cost

    return BatchEvaluationMetrics(
        total_revenue_at_risk=total_at_risk,
        total_recovered=total_recovered,
        recovery_rate=recovery_rate,
        cases_recovered=cases_recovered,
        total_cases=len(results),
        total_cost=total_cost,
        net_recovery=net_recovery,
        cases_escalated=cases_escalated,
        cases_stopped=cases_stopped,
    )


def evaluate_batch(
    *,
    n_cases: int = 100,
    seed: int = 42,
    revivex_mode: str = "ml",
) -> BatchComparisonResult:
    """Evaluate baseline vs ReviveX on a deterministic batch of cases."""
    # Generate deterministic cases
    cases = generate_cases(seed=seed, n_cases=n_cases)

    # Evaluate baseline
    baseline_results = [
        _evaluate_case(case, "baseline", seed=seed, revivex_mode=revivex_mode) for case in cases
    ]
    baseline_metrics = _compute_metrics(baseline_results)

    # Evaluate ReviveX
    revivex_results = [
        _evaluate_case(case, "revivex", seed=seed, revivex_mode=revivex_mode) for case in cases
    ]
    revivex_metrics = _compute_metrics(revivex_results)

    # Compute comparison metrics
    incremental_revenue = revivex_metrics.total_recovered - baseline_metrics.total_recovered
    recovery_uplift_percent = (
        (incremental_revenue / baseline_metrics.total_recovered * Decimal("100"))
        if baseline_metrics.total_recovered > 0
        else Decimal("0.00")
    )

    ml_prediction_count = sum(1 for r in revivex_results if r.probability_source == "ml")
    heuristic_fallback_count = sum(
        1 for r in revivex_results if r.probability_source in ("heuristic", "heuristic_fallback")
    )

    # Build case-level audit data
    case_results = []
    for case, baseline, revivex in zip(cases, baseline_results, revivex_results):
        case_results.append(
            {
                "case_id": str(case["case_id"]),
                "amount_at_risk": str(case["amount"]),
                "baseline_action": baseline.action,
                "revivex_action": revivex.action,
                "baseline_outcome": baseline.final_status,
                "revivex_outcome": revivex.final_status,
                "baseline_recovered_amount": str(baseline.recovered_amount),
                "revivex_recovered_amount": str(revivex.recovered_amount),
                "incremental_recovered_amount": str(
                    revivex.recovered_amount - baseline.recovered_amount
                ),
                "baseline_cost": str(baseline.cost),
                "revivex_cost": str(revivex.cost),
                "probability_source": revivex.probability_source,
            }
        )

    return BatchComparisonResult(
        n_cases=n_cases,
        seed=seed,
        total_revenue_at_risk=baseline_metrics.total_revenue_at_risk,
        baseline_metrics=baseline_metrics,
        revivex_metrics=revivex_metrics,
        incremental_revenue=incremental_revenue,
        recovery_uplift_percent=recovery_uplift_percent,
        revivex_mode=revivex_mode,
        ml_prediction_count=ml_prediction_count,
        heuristic_fallback_count=heuristic_fallback_count,
        case_results=case_results,
    )


def format_report(result: BatchComparisonResult) -> str:
    """Format evaluation results as a human-readable report."""
    b = result.baseline_metrics
    r = result.revivex_metrics

    lines = [
        "ReviveX Revenue Recovery Evaluation",
        "====================================",
        "",
        f"Cases: {result.n_cases}",
        f"Seed: {result.seed}",
        f"ReviveX Mode: {result.revivex_mode.upper()} (ML Predictions: {result.ml_prediction_count}, Fallbacks: {result.heuristic_fallback_count})",
        f"Revenue at risk: ₹{result.total_revenue_at_risk:,.2f}",
        "",
        f"Baseline recovered: ₹{b.total_recovered:,.2f}",
        f"ReviveX recovered: ₹{r.total_recovered:,.2f}",
        "",
        f"Incremental recovered revenue: ₹{result.incremental_revenue:,.2f}",
        f"Recovery uplift: {result.recovery_uplift_percent:.2f}%",
        "",
        f"Baseline recovery rate: {b.recovery_rate * 100:.2f}%",
        f"ReviveX recovery rate: {r.recovery_rate * 100:.2f}%",
        "",
        f"Baseline net recovery: ₹{b.net_recovery:,.2f}",
        f"ReviveX net recovery: ₹{r.net_recovery:,.2f}",
        "",
        f"Recovered cases:",
        f"  Baseline: {b.cases_recovered}",
        f"  ReviveX: {r.cases_recovered}",
        "",
        f"Escalated: {r.cases_escalated}",
        f"Stopped: {r.cases_stopped}",
    ]

    return "\n".join(lines)


def main(argv: list[str] | None = None) -> None:
    """CLI entry point for batch evaluation."""
    parser = argparse.ArgumentParser(
        description="Evaluate ReviveX vs baseline revenue recovery"
    )
    parser.add_argument("--cases", type=int, default=100, help="Number of cases to evaluate")
    parser.add_argument("--seed", type=int, default=42, help="Random seed for reproducibility")
    parser.add_argument(
        "--revivex-mode",
        choices=["ml", "heuristic"],
        default="ml",
        help="ReviveX probability mode ('ml' or 'heuristic')",
    )
    parser.add_argument("--json", action="store_true", help="Output JSON instead of text report")
    args = parser.parse_args(argv)

    result = evaluate_batch(
        n_cases=args.cases, seed=args.seed, revivex_mode=args.revivex_mode
    )

    if args.json:
        output = {
            "n_cases": result.n_cases,
            "seed": result.seed,
            "revivex_mode": result.revivex_mode,
            "ml_prediction_count": result.ml_prediction_count,
            "heuristic_fallback_count": result.heuristic_fallback_count,
            "total_revenue_at_risk": str(result.total_revenue_at_risk),
            "baseline": {
                "total_recovered": str(result.baseline_metrics.total_recovered),
                "recovery_rate": str(result.baseline_metrics.recovery_rate),
                "cases_recovered": result.baseline_metrics.cases_recovered,
                "total_cost": str(result.baseline_metrics.total_cost),
                "net_recovery": str(result.baseline_metrics.net_recovery),
                "cases_escalated": result.baseline_metrics.cases_escalated,
                "cases_stopped": result.baseline_metrics.cases_stopped,
            },
            "revivex": {
                "total_recovered": str(result.revivex_metrics.total_recovered),
                "recovery_rate": str(result.revivex_metrics.recovery_rate),
                "cases_recovered": result.revivex_metrics.cases_recovered,
                "total_cost": str(result.revivex_metrics.total_cost),
                "net_recovery": str(result.revivex_metrics.net_recovery),
                "cases_escalated": result.revivex_metrics.cases_escalated,
                "cases_stopped": result.revivex_metrics.cases_stopped,
            },
            "incremental_revenue": str(result.incremental_revenue),
            "recovery_uplift_percent": str(result.recovery_uplift_percent),
            "case_results": result.case_results,
        }
        print(json.dumps(output, indent=2))
    else:
        print(format_report(result))


if __name__ == "__main__":
    main()
