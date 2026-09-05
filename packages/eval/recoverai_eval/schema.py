from __future__ import annotations

from pydantic import BaseModel, ConfigDict, Field, field_validator

from recoverai_db.enums import RecoveryActionType
from recoverai_eval.errors import InferenceError

VALID_ACTIONS = frozenset(item.value for item in RecoveryActionType)


class CaseContext(BaseModel):
    """Pre-intervention case snapshot. Outcome fields are forbidden."""

    model_config = ConfigDict(extra="forbid")

    amount: float = Field(ge=0)
    failure_reason: str
    attempt_number: int = Field(ge=1)
    merchant_category: str | None = None
    payment_method: str | None = None
    bank: str | None = None
    historical_success_rate: float | None = Field(default=None, ge=0, le=1)
    historical_recovery_rate: float | None = Field(default=None, ge=0, le=1)
    customer_lifetime_value: float | None = Field(default=None, ge=0)
    days_since_last_purchase: float | None = Field(default=None, ge=0)
    cart_age_hours: float | None = Field(default=None, ge=0)
    cart_value: float | None = Field(default=None, ge=0)
    subscription_state: str | None = None
    communication_count: int | None = Field(default=None, ge=0)
    days_since_last_contact: float | None = Field(default=None, ge=0)
    previous_discount_usage: float | None = Field(default=None, ge=0, le=1)
    hour_of_day: int | None = Field(default=None, ge=0, le=23)
    day_of_week: int | None = Field(default=None, ge=0, le=6)
    customer_segment: str | None = None
    case_type: str | None = None
    prior_failures: int | None = Field(default=None, ge=0)
    prior_captures: int | None = Field(default=None, ge=0)
    merchant_id: str | None = None
    recovery_case_id: str | None = None
    customer_id: str | None = None

    @field_validator("failure_reason")
    @classmethod
    def failure_reason_present(cls, value: str) -> str:
        if not value:
            raise ValueError("failure_reason is required")
        return value


def parse_action(action: str) -> str:
    if action not in VALID_ACTIONS:
        raise InferenceError("INVALID_ACTION", f"Unknown recovery action: {action}")
    return action
