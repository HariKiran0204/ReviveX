from __future__ import annotations

from decimal import Decimal

from recoverai_db.enums import RecoveryActionType
from recoverai_domain.errors import OptimizerError
from recoverai_domain.money import ZERO, as_money, signed_money
from recoverai_domain.optimizer.config import OptimizerSettings


def probability_to_decimal(value: Decimal | float | str) -> Decimal:
    if isinstance(value, Decimal):
        probability = value
    elif isinstance(value, float):
        probability = Decimal(str(value))
    else:
        probability = Decimal(value)
    if probability < 0 or probability > 1:
        raise OptimizerError(
            "INVALID_PROBABILITY",
            f"Probability {probability} is outside [0, 1]",
        )
    return probability


def discount_cost(amount_at_risk: Decimal, discount_percent: Decimal) -> Decimal:
    """INR concession: amount_at_risk × percent / 100. Prototype, not a PSP fee."""
    amount = as_money(amount_at_risk)
    percent = discount_percent
    if not isinstance(percent, Decimal):
        raise TypeError("discount_percent must be Decimal")
    if percent < 0:
        raise OptimizerError("INVALID_DISCOUNT", "Discount percent must be >= 0")
    return as_money((amount * percent) / Decimal("100"))


def expected_recovered_revenue(probability: Decimal, amount_at_risk: Decimal) -> Decimal:
    """EXPECTED recovered amount: P(recovery) × amount_at_risk. Not actual recovery."""
    p = probability_to_decimal(probability)
    amount = as_money(amount_at_risk)
    return as_money(p * amount)


def expected_net_recovery(
    *,
    probability: Decimal,
    amount_at_risk: Decimal,
    intervention_cost: Decimal,
    discount_cost_value: Decimal,
    communication_cost: Decimal,
    risk_penalty: Decimal,
) -> Decimal:
    """
    ERV = P(recovery) × recoverable_amount
          − intervention_cost
          − discount_cost
          − communication_cost
          − risk_penalty

    Monetary terms are Decimal. Probability is converted via str() then Decimal.
    """
    expected = expected_recovered_revenue(probability, amount_at_risk)
    return signed_money(
        expected
        - as_money(intervention_cost)
        - as_money(discount_cost_value)
        - as_money(communication_cost)
        - as_money(risk_penalty)
    )


def costs_for_action(
    action: str,
    amount_at_risk: Decimal,
    settings: OptimizerSettings,
    *,
    discount_percent: Decimal | None,
) -> tuple[Decimal, Decimal, Decimal, Decimal]:
    assumptions = settings.costs_for(action)
    concession = ZERO
    if action == RecoveryActionType.OFFER_DISCOUNT.value:
        percent = (
            discount_percent if discount_percent is not None else settings.default_discount_percent
        )
        concession = discount_cost(amount_at_risk, percent)
    return (
        assumptions.intervention_cost,
        concession,
        assumptions.communication_cost,
        assumptions.risk_penalty,
    )
