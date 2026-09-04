from __future__ import annotations

from collections.abc import Mapping
from typing import Any

from recoverai_eval.constants import LEAKAGE_FIELDS, MODEL_FEATURE_COLUMNS
from recoverai_eval.errors import ModelQualityError
from recoverai_eval.schema import CaseContext

FEATURE_CATALOG: dict[str, str] = {
    "amount": "Payment or cart amount at risk. Observed before the intervention.",
    "attempt_number": "Current payment attempt count for this subject.",
    "historical_success_rate": "Customer prior captures / (captures + failures).",
    "historical_recovery_rate": "Prior recovery success, independent of this case outcome.",
    "customer_lifetime_value": "Customer CLV at case open.",
    "days_since_last_purchase": "Recency of last successful purchase.",
    "cart_age_hours": "Hours since abandonment; missing when not a cart case.",
    "cart_value": "Abandoned cart value; missing when not a cart case.",
    "communication_count": "Outbound recovery messages already sent.",
    "days_since_last_contact": "Recency of last outbound contact.",
    "previous_discount_usage": "Fraction of historical checkouts that used a discount.",
    "hour_of_day": "Local/UTC hour when scoring runs (0-23).",
    "day_of_week": "Weekday when scoring runs (0=Monday).",
    "prior_failures": "Historical failed payments plus extra failed attempts.",
    "prior_captures": "Historical captured payments for the customer.",
    "customer_success_ratio": "Derived alias of historical_success_rate.",
    "recent_failure_count": "Derived: max(attempt_number - 1, prior_failures contribution).",
    "communication_fatigue": "Derived: min(1, communication_count / 8).",
    "amount_to_clv_ratio": "Derived: amount / CLV when CLV > 0.",
    "merchant_category": "Merchant vertical.",
    "payment_method": "Method used on the failed payment.",
    "bank": "Issuing/acquiring bank bucket.",
    "failure_reason": "Normalized failure code.",
    "subscription_state": "Subscription lifecycle, or NONE.",
    "customer_segment": "Derived segment from historical behavior (not the label).",
    "case_type": "FAILED_PAYMENT / ABANDONED_CHECKOUT / SUBSCRIPTION_FAILURE.",
    "action": "Candidate intervention. Required for action-conditioned scoring.",
    "failure_action_interaction": "Derived categorical: failure_reason|action.",
}


def derive_features(row: Mapping[str, Any], action: str) -> dict[str, Any]:
    for name in LEAKAGE_FIELDS:
        if name in row and name in MODEL_FEATURE_COLUMNS:
            raise ModelQualityError("TARGET_LEAKAGE", f"Leakage field {name} used as a feature")
    amount = float(row["amount"])
    clv_raw = row.get("customer_lifetime_value")
    clv = float(clv_raw) if clv_raw is not None else 0.0
    attempt = int(row["attempt_number"])
    comms = int(row.get("communication_count") or 0)
    success = row.get("historical_success_rate")
    failure = str(row["failure_reason"])
    cart_age = row.get("cart_age_hours")
    features: dict[str, Any] = {
        "amount": amount,
        "attempt_number": attempt,
        "historical_success_rate": float(success) if success is not None else None,
        "historical_recovery_rate": (
            float(row["historical_recovery_rate"])
            if row.get("historical_recovery_rate") is not None
            else None
        ),
        "customer_lifetime_value": clv if clv_raw is not None else None,
        "days_since_last_purchase": row.get("days_since_last_purchase"),
        "cart_age_hours": float(cart_age) if cart_age is not None else None,
        "cart_value": row.get("cart_value"),
        "communication_count": comms,
        "days_since_last_contact": row.get("days_since_last_contact"),
        "previous_discount_usage": row.get("previous_discount_usage"),
        "hour_of_day": row.get("hour_of_day"),
        "day_of_week": row.get("day_of_week"),
        "prior_failures": row.get("prior_failures"),
        "prior_captures": row.get("prior_captures"),
        "customer_success_ratio": float(success) if success is not None else None,
        "recent_failure_count": max(attempt - 1, int(row.get("prior_failures") or 0)),
        "communication_fatigue": min(1.0, comms / 8.0),
        "amount_to_clv_ratio": (amount / clv) if clv > 0 else None,
        "merchant_category": row.get("merchant_category"),
        "payment_method": row.get("payment_method"),
        "bank": row.get("bank"),
        "failure_reason": failure,
        "subscription_state": row.get("subscription_state"),
        "customer_segment": row.get("customer_segment"),
        "case_type": row.get("case_type"),
        "action": action,
        "failure_action_interaction": f"{failure}|{action}",
    }
    leaked = set(features) & LEAKAGE_FIELDS
    if leaked:
        raise ModelQualityError("TARGET_LEAKAGE", f"Derived features leaked {sorted(leaked)}")
    return features


def features_from_context(context: CaseContext, action: str) -> dict[str, Any]:
    return derive_features(context.model_dump(), action)


def assert_no_target_leakage(feature_names: list[str]) -> None:
    leaked = set(feature_names) & LEAKAGE_FIELDS
    if leaked:
        raise ModelQualityError("TARGET_LEAKAGE", f"Feature names include {sorted(leaked)}")
