from __future__ import annotations

import hashlib
import math
import random
from decimal import Decimal
from typing import Any

from recoverai_db.enums import RecoveryActionType, RecoveryCaseType
from recoverai_providers.models import CustomerHistory, FailureReason
from recoverai_providers.simulator.interventions import (
    SCORABLE_ACTIONS,
    InterventionContext,
    intervention_recovery_probability,
)

DATASET_ASSUMPTIONS = """
Synthetic generation assumptions (dataset-v1)
=============================================
- One RNG stream seeded by --seed. Customer traits are drawn first; case
  attributes are derived from those traits plus bounded noise. Columns are
  not independent.
- Customer latent traits: payment_quality, liquidity, card_health,
  engagement, price_sensitivity. These drive historical rates, failure
  reasons, discount usage, and communication volume.
- TEMPORARY_BANK_ERROR is more common for otherwise healthy payers; retry
  capture probability is high (simulator capture_probability).
- EXPIRED_CARD is more common when card_health is low; retry stays low;
  SEND_PAYMENT_LINK is the meaningful recovery path.
- INSUFFICIENT_FUNDS is more common when liquidity is low; RETRY_LATER beats
  RETRY_NOW (payday / balance replenishment).
- Repeated failed attempts and prior_failures lower recovery odds.
- High historical_success_rate / historical_recovery_rate raise recovery odds.
- Older abandoned carts (cart_age_hours) lower recovery odds.
- High communication_count lowers SEND_REMINDER response (fatigue).
- High previous_discount_usage reduces OFFER_DISCOUNT effectiveness.
- CUSTOMER_CANCELLED and MANDATE_FAILURE are largely unrecoverable for
  automated payment tools. ESCALATE/DO_NOTHING use organic/human-assisted
  rates only — they are not treated as PSP captures.
- Labels are Bernoulli draws from intervention_recovery_probability, the
  same simulator module used at runtime. No action is forced to succeed.
- recovery_time_hours is sampled only when recovered=1 and is never a feature.
"""

MERCHANT_CATEGORIES = ("GROCERY", "SUBSCRIPTION", "TRAVEL", "DIGITAL", "RETAIL")
PAYMENT_METHODS = ("CARD", "UPI", "NETBANKING", "WALLET")
BANKS = ("HDFC", "SBI", "ICICI", "AXIS", "OTHER")
SEGMENTS = ("NEW", "LOYAL", "HIGH_VALUE", "DORMANT", "PRICE_SENSITIVE")
SUB_STATES = ("NONE", "ACTIVE", "PENDING", "HALTED", "CANCELLED")


def _unit(rng: random.Random) -> float:
    return rng.random()


def _clip(value: float, lo: float = 0.0, hi: float = 1.0) -> float:
    return max(lo, min(hi, value))


def _customer_rng(seed: int, customer_index: int) -> random.Random:
    payload = f"{seed}:customer:{customer_index}".encode()
    digest = hashlib.sha256(payload).digest()
    return random.Random(int.from_bytes(digest[:8], "big"))


def _case_rng(seed: int, case_index: int) -> random.Random:
    payload = f"{seed}:case:{case_index}".encode()
    digest = hashlib.sha256(payload).digest()
    return random.Random(int.from_bytes(digest[:8], "big"))


def _label_rng(seed: int, case_id: str, action: str) -> random.Random:
    payload = f"{seed}:label:{case_id}:{action}".encode()
    digest = hashlib.sha256(payload).digest()
    return random.Random(int.from_bytes(digest[:8], "big"))


def _failure_reason(
    rng: random.Random,
    *,
    liquidity: float,
    card_health: float,
    quality: float,
) -> FailureReason:
    roll = rng.random()
    if quality < 0.12 and roll < 0.18:
        return FailureReason.CUSTOMER_CANCELLED
    if card_health < 0.28 and roll < 0.55:
        return FailureReason.EXPIRED_CARD
    if liquidity < 0.32 and roll < 0.62:
        return FailureReason.INSUFFICIENT_FUNDS
    if quality < 0.22 and roll < 0.28:
        return FailureReason.MANDATE_FAILURE
    if roll < 0.22:
        return FailureReason.TEMPORARY_BANK_ERROR
    if roll < 0.38:
        return FailureReason.NETWORK_TIMEOUT
    if roll < 0.55:
        return FailureReason.DECLINED
    if roll < 0.70:
        return FailureReason.INSUFFICIENT_FUNDS
    if roll < 0.82:
        return FailureReason.EXPIRED_CARD
    if roll < 0.90:
        return FailureReason.CUSTOMER_CANCELLED
    return FailureReason.UNKNOWN


def _case_type(rng: random.Random, segment: str, category: str) -> str:
    if category == "SUBSCRIPTION" and rng.random() < 0.55:
        return RecoveryCaseType.SUBSCRIPTION_FAILURE.value
    if segment == "DORMANT" and rng.random() < 0.45:
        return RecoveryCaseType.ABANDONED_CHECKOUT.value
    if rng.random() < 0.18:
        return RecoveryCaseType.ABANDONED_CHECKOUT.value
    return RecoveryCaseType.FAILED_PAYMENT.value


def generate_cases(
    *, seed: int, n_cases: int, n_customers: int | None = None
) -> list[dict[str, Any]]:
    if n_cases < 1:
        raise ValueError("n_cases must be >= 1")
    customer_count = n_customers or max(32, n_cases // 3)
    customers: list[dict[str, float | str | int]] = []
    for index in range(customer_count):
        rng = _customer_rng(seed, index)
        quality = _clip(rng.betavariate(4, 2) if rng.random() > 0.2 else rng.betavariate(2, 4))
        liquidity = _clip(0.55 * quality + 0.45 * rng.random())
        card_health = _clip(0.50 * quality + 0.50 * rng.random())
        engagement = _clip(0.40 * quality + 0.60 * rng.random())
        price_sensitivity = _clip(1.0 - 0.6 * quality + 0.3 * rng.random())
        if quality > 0.75 and rng.random() < 0.5:
            segment = "HIGH_VALUE"
        elif quality > 0.6:
            segment = "LOYAL"
        elif engagement < 0.3:
            segment = "DORMANT"
        elif price_sensitivity > 0.7:
            segment = "PRICE_SENSITIVE"
        else:
            segment = "NEW"
        prior_captures = int(rng.randint(0, 8) * quality + rng.randint(0, 2))
        prior_failures = int(rng.randint(0, 6) * (1 - quality) + rng.randint(0, 2))
        total_hist = max(prior_captures + prior_failures, 1)
        customers.append(
            {
                "customer_index": index,
                "customer_id": f"cust_{seed}_{index}",
                "quality": quality,
                "liquidity": liquidity,
                "card_health": card_health,
                "engagement": engagement,
                "price_sensitivity": price_sensitivity,
                "segment": segment,
                "prior_captures": prior_captures,
                "prior_failures": prior_failures,
                "historical_success_rate": prior_captures / total_hist,
                "historical_recovery_rate": _clip(
                    0.35 * quality
                    + 0.25 * (prior_captures / (prior_captures + 3))
                    + 0.1 * rng.random()
                ),
                "clv": round(200 + quality * 18000 + rng.random() * 2000, 2),
                "previous_discount_usage": _clip(0.15 + 0.7 * price_sensitivity * rng.random()),
            }
        )

    rows: list[dict[str, Any]] = []
    for case_index in range(n_cases):
        rng = _case_rng(seed, case_index)
        customer = customers[case_index % customer_count]
        quality = float(customer["quality"])
        liquidity = float(customer["liquidity"])
        card_health = float(customer["card_health"])
        engagement = float(customer["engagement"])
        category = MERCHANT_CATEGORIES[rng.randrange(len(MERCHANT_CATEGORIES))]
        if float(customer["clv"]) > 8000 and rng.random() < 0.3:
            category = "TRAVEL"
        method = PAYMENT_METHODS[rng.randrange(len(PAYMENT_METHODS))]
        if card_health < 0.35:
            method = "CARD"
        bank = BANKS[rng.randrange(len(BANKS))]
        failure = _failure_reason(
            rng, liquidity=liquidity, card_health=card_health, quality=quality
        )
        case_type = _case_type(rng, str(customer["segment"]), category)
        attempt = 1 + int(rng.random() * (1 + 4 * (1 - quality)))
        attempt = min(max(attempt, 1), 8)
        amount = round(80 + rng.random() * 4500 + (1 - liquidity) * 800, 2)
        if str(customer["segment"]) == "HIGH_VALUE":
            amount = round(amount + 2500 * rng.random(), 2)
        cart_age = None
        cart_value = None
        if case_type == RecoveryCaseType.ABANDONED_CHECKOUT.value:
            cart_age = round(2 + (1 - engagement) * 400 + rng.random() * 80, 2)
            cart_value = amount
        sub_state = "NONE"
        if case_type == RecoveryCaseType.SUBSCRIPTION_FAILURE.value:
            sub_state = "HALTED" if rng.random() < 0.6 else "PENDING"
        comms = int((1 - engagement) * 8 + rng.random() * 3)
        days_contact = (
            round(rng.random() * (2 + comms * 3), 2) if comms else round(rng.random() * 21, 2)
        )
        days_purchase = round((1 - engagement) * 180 + rng.random() * 40, 2)
        hour = int(_clip(rng.gauss(14, 5), 0, 23))
        dow = rng.randrange(7)
        case_id = f"case_{seed}_{case_index}"
        prior_fail = int(customer["prior_failures"]) + max(attempt - 1, 0)
        rows.append(
            {
                "case_id": case_id,
                "customer_id": customer["customer_id"],
                "merchant_category": category,
                "amount": amount,
                "payment_method": method,
                "bank": bank,
                "failure_reason": failure.value,
                "attempt_number": attempt,
                "historical_success_rate": round(float(customer["historical_success_rate"]), 4),
                "historical_recovery_rate": round(float(customer["historical_recovery_rate"]), 4),
                "customer_lifetime_value": float(customer["clv"]),
                "days_since_last_purchase": days_purchase,
                "cart_age_hours": cart_age,
                "cart_value": cart_value,
                "subscription_state": sub_state,
                "communication_count": comms,
                "days_since_last_contact": days_contact,
                "previous_discount_usage": round(float(customer["previous_discount_usage"]), 4),
                "hour_of_day": hour,
                "day_of_week": dow,
                "customer_segment": customer["segment"],
                "case_type": case_type,
                "prior_failures": prior_fail,
                "prior_captures": int(customer["prior_captures"]),
            }
        )
    return rows


def expand_with_labels(
    cases: list[dict[str, Any]],
    *,
    seed: int,
    actions: tuple[str, ...] = SCORABLE_ACTIONS,
) -> list[dict[str, Any]]:
    labeled: list[dict[str, Any]] = []
    for case in cases:
        failure = FailureReason(str(case["failure_reason"]))
        history = CustomerHistory(
            prior_failures=int(case["prior_failures"]),
            prior_captures=int(case["prior_captures"]),
            lifetime_value=Decimal(str(case["customer_lifetime_value"])),
        )
        cart_age = case["cart_age_hours"]
        ctx = InterventionContext(
            failure_reason=failure,
            attempt_number=int(case["attempt_number"]),
            history=history,
            historical_success_rate=float(case["historical_success_rate"]),
            historical_recovery_rate=float(case["historical_recovery_rate"]),
            communication_count=int(case["communication_count"]),
            previous_discount_usage=float(case["previous_discount_usage"]),
            cart_age_hours=float(cart_age) if cart_age is not None else None,
            customer_lifetime_value=Decimal(str(case["customer_lifetime_value"])),
            amount=Decimal(str(case["amount"])),
            hour_of_day=int(case["hour_of_day"]),
            case_type=str(case["case_type"]),
        )
        for action in actions:
            RecoveryActionType(action)
            true_p = float(intervention_recovery_probability(ctx, action))
            rng = _label_rng(seed, str(case["case_id"]), action)
            recovered = 1 if rng.random() < true_p else 0
            recovery_time = None
            if recovered:
                recovery_time = round(max(0.2, rng.lognormvariate(1.2, 0.8)), 2)
            row = dict(case)
            row["action"] = action
            row["true_probability"] = round(true_p, 6)
            row["recovered"] = recovered
            row["recovery_time_hours"] = recovery_time
            labeled.append(row)
    return labeled


def expected_rate(rows: list[dict[str, Any]], **filters: object) -> float:
    matched = [row for row in rows if all(row.get(key) == value for key, value in filters.items())]
    if not matched:
        return math.nan
    return sum(int(row["recovered"]) for row in matched) / len(matched)
