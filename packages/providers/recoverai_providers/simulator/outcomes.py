from __future__ import annotations

import random
from decimal import Decimal

from recoverai_db.enums import PaymentStatus
from recoverai_providers.models import CustomerHistory, FailureReason

_NEVER_CAPTURE = frozenset(
    {
        FailureReason.CUSTOMER_CANCELLED,
        FailureReason.MANDATE_FAILURE,
    }
)


def capture_probability(
    failure_reason: FailureReason | None,
    attempt_number: int,
    history: CustomerHistory,
) -> Decimal:
    """Probability that a simulated attempt is captured rather than failed/cancelled.

    The simulator must not make every recovery succeed. Retryable bank/network
    errors improve with attempt number; hard failures stay near zero.
    """
    attempt = max(attempt_number, 1)
    prior_fail = max(history.prior_failures, 0)
    if failure_reason in _NEVER_CAPTURE:
        return Decimal("0.00")
    if failure_reason is FailureReason.EXPIRED_CARD:
        return Decimal("0.02")
    if failure_reason is FailureReason.TEMPORARY_BANK_ERROR:
        raw = Decimal("0.25") + Decimal("0.15") * (attempt - 1) - Decimal("0.03") * prior_fail
        return min(max(raw, Decimal("0.05")), Decimal("0.80"))
    if failure_reason is FailureReason.NETWORK_TIMEOUT:
        raw = Decimal("0.20") + Decimal("0.15") * (attempt - 1)
        return min(raw, Decimal("0.75"))
    if failure_reason is FailureReason.INSUFFICIENT_FUNDS:
        raw = Decimal("0.08") + Decimal("0.04") * (attempt - 1) - Decimal("0.02") * prior_fail
        return min(max(raw, Decimal("0.02")), Decimal("0.35"))
    if failure_reason is FailureReason.DECLINED:
        raw = Decimal("0.12") + Decimal("0.05") * (attempt - 1)
        return min(raw, Decimal("0.40"))
    raw = Decimal("0.15") + Decimal("0.05") * attempt
    return min(raw, Decimal("0.50"))


def roll_attempt_outcome(
    rng: random.Random,
    *,
    failure_reason: FailureReason | None,
    attempt_number: int,
    history: CustomerHistory,
    intended_status: str | None = None,
) -> tuple[str, FailureReason | None]:
    if intended_status is not None:
        status = intended_status
        if status == PaymentStatus.FAILED:
            return status, failure_reason or FailureReason.UNKNOWN
        if status == PaymentStatus.CANCELLED:
            return status, failure_reason or FailureReason.CUSTOMER_CANCELLED
        return status, None

    reason = failure_reason or FailureReason.UNKNOWN
    if reason is FailureReason.CUSTOMER_CANCELLED:
        return PaymentStatus.CANCELLED, reason

    probability = float(capture_probability(reason, attempt_number, history))
    if rng.random() < probability:
        return PaymentStatus.CAPTURED, None
    return PaymentStatus.FAILED, reason
