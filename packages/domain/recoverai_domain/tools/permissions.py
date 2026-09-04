from __future__ import annotations

from recoverai_db.enums import RecoveryActionType

TOOL_BY_ACTION: dict[RecoveryActionType, str] = {
    RecoveryActionType.RETRY_NOW: "retry_payment",
    RecoveryActionType.RETRY_LATER: "schedule_retry",
    RecoveryActionType.SEND_PAYMENT_LINK: "create_payment_link",
    RecoveryActionType.SEND_REMINDER: "send_notification",
    RecoveryActionType.OFFER_DISCOUNT: "offer_discount",
    RecoveryActionType.ESCALATE: "escalate_to_human",
    RecoveryActionType.DO_NOTHING: "pause_recovery",
}

ACTION_BY_TOOL: dict[str, RecoveryActionType] = {
    value: key for key, value in TOOL_BY_ACTION.items()
}


def action_for_tool(tool_name: str) -> RecoveryActionType | None:
    return ACTION_BY_TOOL.get(tool_name)


def tool_for_action(action: str | RecoveryActionType) -> str | None:
    try:
        parsed = action if isinstance(action, RecoveryActionType) else RecoveryActionType(action)
    except ValueError:
        return None
    return TOOL_BY_ACTION.get(parsed)


def parse_action_type(value: str) -> RecoveryActionType:
    return RecoveryActionType(value)
