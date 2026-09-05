from __future__ import annotations

from recoverai_db.enums import RiskLevel, ToolPermission
from recoverai_domain.errors import ToolValidationError
from recoverai_domain.tools.schemas import INPUT_MODELS, OUTPUT_SCHEMAS, ToolSpec

TOOL_SPECS: dict[str, ToolSpec] = {
    "get_customer_history": ToolSpec(
        name="get_customer_history",
        version="v1",
        description="Read customer profile and prior payments for the case merchant.",
        input_model=INPUT_MODELS["get_customer_history"],
        output_schema=OUTPUT_SCHEMAS["get_customer_history"],
        risk_level=RiskLevel.GREEN,
        required_permission=ToolPermission.VIEW_CUSTOMER,
        timeout_seconds=10,
        side_effect=False,
    ),
    "get_payment_details": ToolSpec(
        name="get_payment_details",
        version="v1",
        description="Read the failed payment attached to the recovery case.",
        input_model=INPUT_MODELS["get_payment_details"],
        output_schema=OUTPUT_SCHEMAS["get_payment_details"],
        risk_level=RiskLevel.GREEN,
        required_permission=ToolPermission.VIEW_PAYMENT,
        timeout_seconds=10,
        side_effect=False,
    ),
    "get_cart_details": ToolSpec(
        name="get_cart_details",
        version="v1",
        description="Read cart context when the case is an abandoned checkout.",
        input_model=INPUT_MODELS["get_cart_details"],
        output_schema=OUTPUT_SCHEMAS["get_cart_details"],
        risk_level=RiskLevel.GREEN,
        required_permission=ToolPermission.VIEW_RECOVERY,
        timeout_seconds=10,
        side_effect=False,
    ),
    "get_subscription_details": ToolSpec(
        name="get_subscription_details",
        version="v1",
        description="Read subscription context when the case is a subscription failure.",
        input_model=INPUT_MODELS["get_subscription_details"],
        output_schema=OUTPUT_SCHEMAS["get_subscription_details"],
        risk_level=RiskLevel.GREEN,
        required_permission=ToolPermission.VIEW_RECOVERY,
        timeout_seconds=10,
        side_effect=False,
    ),
    "get_recovery_case": ToolSpec(
        name="get_recovery_case",
        version="v1",
        description="Read recovery case status and amounts. Does not mutate recovered revenue.",
        input_model=INPUT_MODELS["get_recovery_case"],
        output_schema=OUTPUT_SCHEMAS["get_recovery_case"],
        risk_level=RiskLevel.GREEN,
        required_permission=ToolPermission.VIEW_RECOVERY,
        timeout_seconds=10,
        side_effect=False,
    ),
    "calculate_recovery_probability": ToolSpec(
        name="calculate_recovery_probability",
        version="v1",
        description="Estimate P(recovery | case, action). Does not choose or execute the action.",
        input_model=INPUT_MODELS["calculate_recovery_probability"],
        output_schema=OUTPUT_SCHEMAS["calculate_recovery_probability"],
        risk_level=RiskLevel.GREEN,
        required_permission=ToolPermission.VIEW_RECOVERY,
        timeout_seconds=10,
        side_effect=False,
    ),
    "retry_payment": ToolSpec(
        name="retry_payment",
        version="v1",
        description="Create a new simulated payment attempt. Does not reuse the failed payment id.",
        input_model=INPUT_MODELS["retry_payment"],
        output_schema=OUTPUT_SCHEMAS["retry_payment"],
        risk_level=RiskLevel.YELLOW,
        required_permission=ToolPermission.RETRY_PAYMENT,
        timeout_seconds=30,
        side_effect=True,
    ),
    "schedule_retry": ToolSpec(
        name="schedule_retry",
        version="v1",
        description="Persist a future retry. Does not execute the payment now.",
        input_model=INPUT_MODELS["schedule_retry"],
        output_schema=OUTPUT_SCHEMAS["schedule_retry"],
        risk_level=RiskLevel.GREEN,
        required_permission=ToolPermission.RETRY_PAYMENT,
        timeout_seconds=10,
        side_effect=True,
    ),
    "create_payment_link": ToolSpec(
        name="create_payment_link",
        version="v1",
        description="Create a simulated payment link. Not a Razorpay payment link.",
        input_model=INPUT_MODELS["create_payment_link"],
        output_schema=OUTPUT_SCHEMAS["create_payment_link"],
        risk_level=RiskLevel.YELLOW,
        required_permission=ToolPermission.CREATE_PAYMENT_LINK,
        timeout_seconds=30,
        side_effect=True,
    ),
    "send_notification": ToolSpec(
        name="send_notification",
        version="v1",
        description="Record a simulated notification. No SMS or WhatsApp delivery.",
        input_model=INPUT_MODELS["send_notification"],
        output_schema=OUTPUT_SCHEMAS["send_notification"],
        risk_level=RiskLevel.GREEN,
        required_permission=ToolPermission.SEND_NOTIFICATION,
        timeout_seconds=15,
        side_effect=True,
    ),
    "offer_discount": ToolSpec(
        name="offer_discount",
        version="v1",
        description="Record a bounded discount. Does not decide economic value.",
        input_model=INPUT_MODELS["offer_discount"],
        output_schema=OUTPUT_SCHEMAS["offer_discount"],
        risk_level=RiskLevel.YELLOW,
        required_permission=ToolPermission.OFFER_DISCOUNT,
        timeout_seconds=15,
        side_effect=True,
    ),
    "check_payment_status": ToolSpec(
        name="check_payment_status",
        version="v1",
        description="Fetch payment status from the provider adapter or local records.",
        input_model=INPUT_MODELS["check_payment_status"],
        output_schema=OUTPUT_SCHEMAS["check_payment_status"],
        risk_level=RiskLevel.GREEN,
        required_permission=ToolPermission.VIEW_PAYMENT,
        timeout_seconds=15,
        side_effect=False,
    ),
    "check_subscription_status": ToolSpec(
        name="check_subscription_status",
        version="v1",
        description="Read local subscription status. Provider subscription fetch is not required.",
        input_model=INPUT_MODELS["check_subscription_status"],
        output_schema=OUTPUT_SCHEMAS["check_subscription_status"],
        risk_level=RiskLevel.GREEN,
        required_permission=ToolPermission.VIEW_RECOVERY,
        timeout_seconds=10,
        side_effect=False,
    ),
    "escalate_to_human": ToolSpec(
        name="escalate_to_human",
        version="v1",
        description="Escalate the case. Never claims financial recovery.",
        input_model=INPUT_MODELS["escalate_to_human"],
        output_schema=OUTPUT_SCHEMAS["escalate_to_human"],
        risk_level=RiskLevel.GREEN,
        required_permission=ToolPermission.ESCALATE,
        timeout_seconds=10,
        side_effect=True,
    ),
    "pause_recovery": ToolSpec(
        name="pause_recovery",
        version="v1",
        description="Stop automatic recovery for the case without crediting revenue.",
        input_model=INPUT_MODELS["pause_recovery"],
        output_schema=OUTPUT_SCHEMAS["pause_recovery"],
        risk_level=RiskLevel.GREEN,
        required_permission=ToolPermission.PAUSE_RECOVERY,
        timeout_seconds=10,
        side_effect=True,
    ),
}


class ToolRegistry:
    def get(self, name: str) -> ToolSpec:
        spec = TOOL_SPECS.get(name)
        if spec is None:
            raise ToolValidationError("UNKNOWN_TOOL", f"Tool {name} is not registered")
        return spec

    def require(self, name: str) -> ToolSpec:
        return self.get(name)

    def all_specs(self) -> list[ToolSpec]:
        return list(TOOL_SPECS.values())


def get_tool_registry() -> ToolRegistry:
    return ToolRegistry()
