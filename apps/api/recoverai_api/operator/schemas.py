from __future__ import annotations

from decimal import Decimal
from uuid import UUID

from pydantic import BaseModel, Field


class PolicySettingsBody(BaseModel):
    max_retry_attempts: int = Field(ge=0, le=50)
    max_discount_percent: Decimal = Field(ge=0, le=100)
    max_daily_discount_budget: Decimal = Field(ge=0)
    high_value_approval_threshold: Decimal = Field(ge=0)
    medium_value_approval_threshold: Decimal = Field(ge=0)
    max_communications_per_day: int = Field(ge=0, le=100)
    quiet_hours_start: int = Field(ge=0, le=23)
    quiet_hours_end: int = Field(ge=0, le=23)
    automatic_recovery_enabled: bool
    approval_ttl_minutes: int = Field(ge=1, le=24 * 60)
    blocked_action_types: list[str] = Field(default_factory=list)


class PolicyUpdateRequest(BaseModel):
    merchant_id: UUID | None = None
    merchant_slug: str | None = None
    policy: PolicySettingsBody


class ApprovalDecisionRequest(BaseModel):
    merchant_id: UUID | None = None
    reason: str | None = None
    actor_id: str | None = "demo-operator"


class DemoRequest(BaseModel):
    kind: str
    merchant_slug: str | None = None
    seed: int | None = None
    amount: Decimal | None = None


class AnalystAskRequest(BaseModel):
    question: str
