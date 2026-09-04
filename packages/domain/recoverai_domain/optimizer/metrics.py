from __future__ import annotations

from decimal import Decimal

from recoverai_domain.money import ZERO, as_money, signed_money
from recoverai_domain.optimizer.erv import expected_net_recovery, expected_recovered_revenue
from recoverai_domain.optimizer.types import CandidateAction, OptimizationResult


def expected_recovered_revenue_for(candidate: CandidateAction) -> Decimal:
    """EXPECTED recovered revenue. Distinct from verified amount_recovered."""
    if candidate.probability is None:
        return ZERO
    return expected_recovered_revenue(candidate.probability, candidate.amount_at_risk)


def expected_net_recovery_for(candidate: CandidateAction) -> Decimal:
    if candidate.probability is None:
        return signed_money(
            ZERO
            - as_money(candidate.intervention_cost)
            - as_money(candidate.discount_cost)
            - as_money(candidate.communication_cost)
            - as_money(candidate.risk_penalty)
        )
    return expected_net_recovery(
        probability=candidate.probability,
        amount_at_risk=candidate.amount_at_risk,
        intervention_cost=candidate.intervention_cost,
        discount_cost_value=candidate.discount_cost,
        communication_cost=candidate.communication_cost,
        risk_penalty=candidate.risk_penalty,
    )


def discount_spend(candidate: CandidateAction) -> Decimal:
    return as_money(candidate.discount_cost)


def intervention_cost_total(candidate: CandidateAction) -> Decimal:
    return as_money(candidate.intervention_cost + candidate.communication_cost)


def expected_recovery_rate(result: OptimizationResult) -> Decimal | None:
    selected = next(
        (item for item in result.candidate_actions if item.action == result.selected_action),
        None,
    )
    if selected is None or selected.probability is None:
        return None
    return selected.probability
