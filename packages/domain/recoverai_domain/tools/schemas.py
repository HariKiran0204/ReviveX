from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from pydantic import BaseModel, ConfigDict, Field

from recoverai_db.enums import NotificationChannel, RiskLevel, ToolPermission


class StrictModel(BaseModel):
    model_config = ConfigDict(extra="forbid")


class EmptyInput(StrictModel):
    pass


class GetCustomerHistoryInput(StrictModel):
    pass


class GetPaymentDetailsInput(StrictModel):
    pass


class GetCartDetailsInput(StrictModel):
    pass


class GetSubscriptionDetailsInput(StrictModel):
    pass


class GetRecoveryCaseInput(StrictModel):
    pass


class CalculateRecoveryProbabilityInput(StrictModel):
    action: str | None = None


class RetryPaymentInput(StrictModel):
    attempt_number: int | None = None


class ScheduleRetryInput(StrictModel):
    scheduled_for: str


class CreatePaymentLinkInput(StrictModel):
    description: str | None = None


class SendNotificationInput(StrictModel):
    channel: NotificationChannel = NotificationChannel.EMAIL
    subject: str | None = None
    body_preview: str | None = None


class OfferDiscountInput(StrictModel):
    discount_percent: str = Field(description="Percentage as a decimal string, e.g. 10.00")


class CheckPaymentStatusInput(StrictModel):
    provider_payment_id: str | None = None


class CheckSubscriptionStatusInput(StrictModel):
    pass


class EscalateToHumanInput(StrictModel):
    reason: str | None = None


class PauseRecoveryInput(StrictModel):
    reason: str | None = None


INPUT_MODELS: dict[str, type[StrictModel]] = {
    "get_customer_history": GetCustomerHistoryInput,
    "get_payment_details": GetPaymentDetailsInput,
    "get_cart_details": GetCartDetailsInput,
    "get_subscription_details": GetSubscriptionDetailsInput,
    "get_recovery_case": GetRecoveryCaseInput,
    "calculate_recovery_probability": CalculateRecoveryProbabilityInput,
    "retry_payment": RetryPaymentInput,
    "schedule_retry": ScheduleRetryInput,
    "create_payment_link": CreatePaymentLinkInput,
    "send_notification": SendNotificationInput,
    "offer_discount": OfferDiscountInput,
    "check_payment_status": CheckPaymentStatusInput,
    "check_subscription_status": CheckSubscriptionStatusInput,
    "escalate_to_human": EscalateToHumanInput,
    "pause_recovery": PauseRecoveryInput,
}


OUTPUT_SCHEMAS: dict[str, dict[str, Any]] = {name: {"type": "object"} for name in INPUT_MODELS}


@dataclass(frozen=True)
class ToolSpec:
    name: str
    version: str
    description: str
    input_model: type[StrictModel]
    output_schema: dict[str, Any]
    risk_level: RiskLevel
    required_permission: ToolPermission
    timeout_seconds: int
    side_effect: bool
