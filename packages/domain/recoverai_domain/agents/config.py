from __future__ import annotations

import os
from dataclasses import dataclass
from typing import Literal

TRIAGE_VERSION = "triage-v1"
DIAGNOSIS_VERSION = "diagnosis-v1"
STRATEGY_VERSION = "strategy-v1"
EXPLAINER_VERSION = "decision-explainer-v1"
ANALYST_VERSION = "analyst-v1"
VERIFICATION_EXPLAINER_VERSION = "verification-explainer-v1"
ORCHESTRATOR_VERSION = "orchestrator-v1"

SOURCE_LLM: Literal["LLM"] = "LLM"
SOURCE_FALLBACK: Literal["DETERMINISTIC_FALLBACK"] = "DETERMINISTIC_FALLBACK"

READ_TOOLS = frozenset(
    {
        "get_customer_history",
        "get_payment_details",
        "get_cart_details",
        "get_subscription_details",
        "get_recovery_case",
        "calculate_recovery_probability",
        "check_payment_status",
        "check_subscription_status",
    }
)

RETRYABLE_FAILURES = frozenset({"TEMPORARY_BANK_ERROR", "NETWORK_TIMEOUT", "INSUFFICIENT_FUNDS"})
UNRECOVERABLE_FAILURES = frozenset({"CUSTOMER_CANCELLED", "MANDATE_FAILURE"})
CARD_FAILURES = frozenset({"EXPIRED_CARD", "DECLINED"})


def _int_env(name: str, default: int) -> int:
    raw = os.environ.get(name)
    if raw is None or raw.strip() == "":
        return default
    return int(raw)


@dataclass(frozen=True)
class AgentSettings:
    max_agent_steps: int = 8
    max_tool_calls: int = 12
    max_repeated_tool_calls: int = 2
    llm_timeout_seconds: float = 8.0
    llm_max_retries: int = 1
    llm_provider: str = "stub"

    @classmethod
    def from_env(cls) -> AgentSettings:
        return cls(
            max_agent_steps=_int_env("MAX_AGENT_STEPS", 8),
            max_tool_calls=_int_env("MAX_TOOL_CALLS", 12),
            max_repeated_tool_calls=_int_env("MAX_REPEATED_TOOL_CALLS", 2),
            llm_timeout_seconds=float(os.environ.get("LLM_TIMEOUT_SECONDS") or 8),
            llm_max_retries=_int_env("LLM_MAX_RETRIES", 1),
            llm_provider=(os.environ.get("LLM_PROVIDER") or "stub").strip().lower(),
        )


def load_agent_settings() -> AgentSettings:
    return AgentSettings.from_env()
