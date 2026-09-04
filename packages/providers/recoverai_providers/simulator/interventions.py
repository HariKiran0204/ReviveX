"""Action-conditioned recovery probabilities for the local simulator.

This extends ``capture_probability`` (retry/capture mechanics). It does not
create a second simulation engine. Labels for ML training must go through here.

ESCALATE and DO_NOTHING are not payment-tool captures. Their probabilities
represent organic or human-assisted recovery, not a guaranteed PSP success.
"""

from __future__ import annotations

from dataclasses import dataclass
from decimal import Decimal

from recoverai_db.enums import RecoveryActionType
from recoverai_providers.models import CustomerHistory, FailureReason
from recoverai_providers.simulator.outcomes import _NEVER_CAPTURE, capture_probability

# Actions the simulator can score with a meaningful recovery label.
SCORABLE_ACTIONS: tuple[str, ...] = tuple(item.value for item in RecoveryActionType)

_HARD_FAILURES = _NEVER_CAPTURE


@dataclass(frozen=True)
class InterventionContext:
    failure_reason: FailureReason | None
    attempt_number: int
    history: CustomerHistory
    historical_success_rate: float
    historical_recovery_rate: float
    communication_count: int
    previous_discount_usage: float
    cart_age_hours: float | None
    customer_lifetime_value: Decimal
    amount: Decimal
    hour_of_day: int
    case_type: str


def _clip_prob(value: Decimal) -> Decimal:
    if value < Decimal("0"):
        return Decimal("0.00")
    if value > Decimal("0.95"):
        return Decimal("0.95")
    return value.quantize(Decimal("0.0001"))


def _dec(value: float) -> Decimal:
    return Decimal(str(round(float(value), 6)))


def intervention_recovery_probability(
    context: InterventionContext,
    action: str,
) -> Decimal:
    """P(revenue recovers | case context, intervention).

    Probabilistic: callers must Bernoulli-sample; no action always succeeds.
    """
    try:
        parsed = RecoveryActionType(action)
    except ValueError as exc:
        raise ValueError(f"Unknown recovery action: {action}") from exc

    reason = context.failure_reason
    attempt = max(context.attempt_number, 1)
    retry_base = capture_probability(reason, attempt, context.history)
    success = _dec(min(max(context.historical_success_rate, 0.0), 1.0))
    prior_recovery = _dec(min(max(context.historical_recovery_rate, 0.0), 1.0))
    loyalty = Decimal("0.12") * success + Decimal("0.08") * prior_recovery
    fatigue = min(Decimal("1"), Decimal(max(context.communication_count, 0)) / Decimal("8"))
    discount_used = _dec(min(max(context.previous_discount_usage, 0.0), 1.0))
    cart_pen = Decimal("0")
    if context.cart_age_hours is not None:
        hours = Decimal(str(max(context.cart_age_hours, 0.0)))
        cart_pen = min(Decimal("0.28"), hours / Decimal("720") * Decimal("0.28"))
    attempt_pen = Decimal("0.045") * Decimal(max(attempt - 1, 0))
    clv = context.customer_lifetime_value
    amount_ratio = Decimal("0")
    if clv > 0:
        amount_ratio = min(context.amount / clv, Decimal("5"))
    high_amount_pen = Decimal("0.04") * max(amount_ratio - Decimal("1"), Decimal("0"))
    quiet_hour = context.hour_of_day >= 21 or context.hour_of_day < 8
    abandoned = context.case_type == "ABANDONED_CHECKOUT"

    if reason in _HARD_FAILURES:
        if parsed is RecoveryActionType.ESCALATE:
            return _clip_prob(Decimal("0.04") + Decimal("0.04") * success)
        if parsed is RecoveryActionType.DO_NOTHING:
            return Decimal("0.01")
        if (
            parsed is RecoveryActionType.SEND_PAYMENT_LINK
            and reason is FailureReason.MANDATE_FAILURE
        ):
            return _clip_prob(Decimal("0.03") + Decimal("0.05") * success)
        return Decimal("0.01")

    if parsed is RecoveryActionType.RETRY_NOW:
        p = retry_base + loyalty - cart_pen - attempt_pen - high_amount_pen
        if reason is FailureReason.INSUFFICIENT_FUNDS:
            p *= Decimal("0.62")
        elif reason is FailureReason.TEMPORARY_BANK_ERROR:
            p = min(Decimal("0.90"), p + Decimal("0.10"))
        elif reason is FailureReason.NETWORK_TIMEOUT:
            p = min(Decimal("0.85"), p + Decimal("0.06"))
        elif reason is FailureReason.EXPIRED_CARD:
            p = min(p, Decimal("0.06"))
        return _clip_prob(p)

    if parsed is RecoveryActionType.RETRY_LATER:
        p = retry_base + loyalty - cart_pen - Decimal("0.02") * attempt_pen - high_amount_pen
        if reason is FailureReason.INSUFFICIENT_FUNDS:
            p = min(Decimal("0.58"), retry_base * Decimal("2.15") + loyalty - cart_pen)
        elif reason is FailureReason.TEMPORARY_BANK_ERROR:
            p = retry_base + loyalty - Decimal("0.03")
        elif reason is FailureReason.EXPIRED_CARD:
            p = min(p, Decimal("0.07"))
        return _clip_prob(p)

    if parsed is RecoveryActionType.SEND_PAYMENT_LINK:
        p = Decimal("0.18") + loyalty + Decimal("0.08") * success - cart_pen - attempt_pen
        if reason is FailureReason.EXPIRED_CARD:
            p = Decimal("0.42") + Decimal("0.22") * success - cart_pen
        elif reason is FailureReason.DECLINED:
            p = Decimal("0.22") + loyalty
        elif reason is FailureReason.TEMPORARY_BANK_ERROR:
            p = retry_base * Decimal("0.55") + Decimal("0.08")
        if abandoned:
            p += Decimal("0.06")
        return _clip_prob(p)

    if parsed is RecoveryActionType.SEND_REMINDER:
        p = (
            Decimal("0.14")
            + Decimal("0.20") * success
            - Decimal("0.22") * fatigue
            - cart_pen
            - attempt_pen
        )
        if quiet_hour:
            p -= Decimal("0.05")
        if abandoned:
            p += Decimal("0.04")
        if reason is FailureReason.EXPIRED_CARD:
            p *= Decimal("0.45")
        return _clip_prob(p)

    if parsed is RecoveryActionType.OFFER_DISCOUNT:
        novelty = Decimal("1") - Decimal("0.70") * discount_used
        p = (
            Decimal("0.20")
            + Decimal("0.16") * success
            + Decimal("0.08") * novelty
            - cart_pen
            - high_amount_pen
        )
        if reason is FailureReason.INSUFFICIENT_FUNDS:
            p += Decimal("0.06")
        if abandoned:
            p += Decimal("0.05")
        return _clip_prob(p * novelty)

    if parsed is RecoveryActionType.DO_NOTHING:
        organic = Decimal("0.025") + Decimal("0.06") * success - Decimal("0.015") * fatigue
        if abandoned:
            organic -= cart_pen * Decimal("0.5")
        return _clip_prob(organic)

    # ESCALATE: human-assisted organic recovery, not an automatic capture.
    assisted = Decimal("0.08") + Decimal("0.12") * success - Decimal("0.03") * fatigue
    return _clip_prob(assisted)
