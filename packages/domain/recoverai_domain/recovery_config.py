from __future__ import annotations

import os
from dataclasses import dataclass
from decimal import Decimal
from typing import Any


def _int_env(name: str, default: int) -> int:
    raw = os.environ.get(name)
    if raw is None or raw.strip() == "":
        return default
    return int(raw)


def _decimal_env(name: str, default: Decimal) -> Decimal:
    raw = os.environ.get(name)
    if raw is None or raw.strip() == "":
        return default
    return Decimal(raw)


def _bool_env(name: str, default: bool) -> bool:
    raw = os.environ.get(name)
    if raw is None or raw.strip() == "":
        return default
    return raw.strip().lower() in {"1", "true", "yes", "on"}


POLICY_VERSION = "policy-v1"


@dataclass(frozen=True)
class RecoverySettings:
    """Recovery and policy configuration. Merchant settings may override these."""

    recovery_window_hours: int = 72
    recovery_ordering_grace_minutes: int = 60
    high_value_approval_threshold: Decimal = Decimal("25000")
    medium_value_approval_threshold: Decimal = Decimal("5000")
    max_retry_attempts: int = 3
    max_discount_percent: Decimal = Decimal("10")
    max_daily_discount_budget: Decimal = Decimal("5000")
    max_communications_per_day: int = 3
    quiet_hours_start: int = 21
    quiet_hours_end: int = 8
    automatic_recovery_enabled: bool = True
    approval_ttl_minutes: int = 60
    policy_version: str = POLICY_VERSION

    @classmethod
    def from_env(cls) -> RecoverySettings:
        return cls(
            recovery_window_hours=_int_env("RECOVERY_WINDOW_HOURS", 72),
            recovery_ordering_grace_minutes=_int_env("RECOVERY_ORDERING_GRACE_MINUTES", 60),
            high_value_approval_threshold=_decimal_env(
                "HIGH_VALUE_APPROVAL_THRESHOLD", Decimal("25000")
            ),
            medium_value_approval_threshold=_decimal_env(
                "MEDIUM_VALUE_APPROVAL_THRESHOLD", Decimal("5000")
            ),
            max_retry_attempts=_int_env("MAX_RETRY_ATTEMPTS", 3),
            max_discount_percent=_decimal_env("MAX_DISCOUNT_PERCENT", Decimal("10")),
            max_daily_discount_budget=_decimal_env("MAX_DAILY_DISCOUNT_BUDGET", Decimal("5000")),
            max_communications_per_day=_int_env("MAX_COMMUNICATIONS_PER_DAY", 3),
            quiet_hours_start=_int_env("QUIET_HOURS_START", 21),
            quiet_hours_end=_int_env("QUIET_HOURS_END", 8),
            automatic_recovery_enabled=_bool_env("AUTOMATIC_RECOVERY_ENABLED", True),
            approval_ttl_minutes=_int_env("APPROVAL_TTL_MINUTES", 60),
            policy_version=os.environ.get("POLICY_VERSION") or POLICY_VERSION,
        )

    def merge_merchant(self, settings: dict[str, Any] | None) -> RecoverySettings:
        policy = _policy_section(settings)
        if not policy:
            return self
        return RecoverySettings(
            recovery_window_hours=_int_value(
                policy, "recovery_window_hours", self.recovery_window_hours
            ),
            recovery_ordering_grace_minutes=_int_value(
                policy, "recovery_ordering_grace_minutes", self.recovery_ordering_grace_minutes
            ),
            high_value_approval_threshold=_decimal_value(
                policy, "high_value_approval_threshold", self.high_value_approval_threshold
            ),
            medium_value_approval_threshold=_decimal_value(
                policy, "medium_value_approval_threshold", self.medium_value_approval_threshold
            ),
            max_retry_attempts=_int_value(policy, "max_retry_attempts", self.max_retry_attempts),
            max_discount_percent=_decimal_value(
                policy, "max_discount_percent", self.max_discount_percent
            ),
            max_daily_discount_budget=_decimal_value(
                policy, "max_daily_discount_budget", self.max_daily_discount_budget
            ),
            max_communications_per_day=_int_value(
                policy, "max_communications_per_day", self.max_communications_per_day
            ),
            quiet_hours_start=_int_value(policy, "quiet_hours_start", self.quiet_hours_start),
            quiet_hours_end=_int_value(policy, "quiet_hours_end", self.quiet_hours_end),
            automatic_recovery_enabled=_bool_value(
                policy, "automatic_recovery_enabled", self.automatic_recovery_enabled
            ),
            approval_ttl_minutes=_int_value(
                policy, "approval_ttl_minutes", self.approval_ttl_minutes
            ),
            policy_version=str(policy.get("policy_version") or self.policy_version),
        )


def _policy_section(settings: dict[str, Any] | None) -> dict[str, Any]:
    if not settings:
        return {}
    nested = settings.get("policy")
    if isinstance(nested, dict):
        return nested
    return settings


def _int_value(data: dict[str, Any], key: str, default: int) -> int:
    raw = data.get(key)
    if raw is None or raw == "":
        return default
    return int(raw)


def _decimal_value(data: dict[str, Any], key: str, default: Decimal) -> Decimal:
    raw = data.get(key)
    if raw is None or raw == "":
        return default
    return Decimal(str(raw))


def _bool_value(data: dict[str, Any], key: str, default: bool) -> bool:
    raw = data.get(key)
    if raw is None or raw == "":
        return default
    if isinstance(raw, bool):
        return raw
    return str(raw).strip().lower() in {"1", "true", "yes", "on"}


def load_recovery_settings() -> RecoverySettings:
    return RecoverySettings.from_env()
