from __future__ import annotations

from decimal import Decimal

from recoverai_eval.schema import CaseContext, parse_action
from recoverai_providers.models import CustomerHistory, FailureReason
from recoverai_providers.simulator.interventions import (
    InterventionContext,
    intervention_recovery_probability,
)

FALLBACK_VERSION = "MODEL_FALLBACK"


def fallback_probability(context: CaseContext, action: str) -> float:
    """Deterministic rule-based score. Not a trained model."""
    parsed = parse_action(action)
    try:
        reason = FailureReason(context.failure_reason)
    except ValueError:
        reason = FailureReason.UNKNOWN
    history = CustomerHistory(
        prior_failures=context.prior_failures or 0,
        prior_captures=context.prior_captures or 0,
        lifetime_value=Decimal(str(context.customer_lifetime_value or 0)),
    )
    intervention = InterventionContext(
        failure_reason=reason,
        attempt_number=context.attempt_number,
        history=history,
        historical_success_rate=context.historical_success_rate or 0.0,
        historical_recovery_rate=context.historical_recovery_rate or 0.0,
        communication_count=context.communication_count or 0,
        previous_discount_usage=context.previous_discount_usage or 0.0,
        cart_age_hours=context.cart_age_hours,
        customer_lifetime_value=Decimal(str(context.customer_lifetime_value or 0)),
        amount=Decimal(str(context.amount)),
        hour_of_day=context.hour_of_day if context.hour_of_day is not None else 12,
        case_type=context.case_type or "FAILED_PAYMENT",
    )
    value = float(intervention_recovery_probability(intervention, parsed))
    return min(max(value, 0.0), 1.0)
