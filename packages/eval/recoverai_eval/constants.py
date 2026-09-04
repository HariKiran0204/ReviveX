from __future__ import annotations

FEATURE_VERSION = "features-v1"
DATASET_SCHEMA_VERSION = "dataset-v1"

LEAKAGE_FIELDS = frozenset(
    {
        "recovered",
        "recovery_time_hours",
        "amount_recovered",
        "true_probability",
        "label",
        "outcome",
        "captured",
    }
)

RAW_CONTEXT_FIELDS = (
    "merchant_category",
    "amount",
    "payment_method",
    "bank",
    "failure_reason",
    "attempt_number",
    "historical_success_rate",
    "historical_recovery_rate",
    "customer_lifetime_value",
    "days_since_last_purchase",
    "cart_age_hours",
    "cart_value",
    "subscription_state",
    "communication_count",
    "days_since_last_contact",
    "previous_discount_usage",
    "hour_of_day",
    "day_of_week",
    "customer_segment",
    "case_type",
    "prior_failures",
    "prior_captures",
)

NUMERIC_FEATURES = (
    "amount",
    "attempt_number",
    "historical_success_rate",
    "historical_recovery_rate",
    "customer_lifetime_value",
    "days_since_last_purchase",
    "cart_age_hours",
    "cart_value",
    "communication_count",
    "days_since_last_contact",
    "previous_discount_usage",
    "hour_of_day",
    "day_of_week",
    "prior_failures",
    "prior_captures",
    "customer_success_ratio",
    "recent_failure_count",
    "communication_fatigue",
    "amount_to_clv_ratio",
)

CATEGORICAL_FEATURES = (
    "merchant_category",
    "payment_method",
    "bank",
    "failure_reason",
    "subscription_state",
    "customer_segment",
    "case_type",
    "action",
    "failure_action_interaction",
)

MODEL_FEATURE_COLUMNS = NUMERIC_FEATURES + CATEGORICAL_FEATURES

ID_COLUMNS = ("case_id", "customer_id", "split")
