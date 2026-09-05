from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
from decimal import Decimal
from typing import Any
from uuid import UUID

from recoverai_db.enums import RecoveryActionType, RiskLevel
from recoverai_db.models import Customer, Merchant, Payment, RecoveryCase
from recoverai_domain.recovery_config import POLICY_VERSION, RecoverySettings

AUTOMATIC_ACTIONS = frozenset(
    {
        RecoveryActionType.RETRY_NOW,
        RecoveryActionType.RETRY_LATER,
        RecoveryActionType.SEND_PAYMENT_LINK,
        RecoveryActionType.SEND_REMINDER,
        RecoveryActionType.OFFER_DISCOUNT,
    }
)

COMMUNICATION_ACTIONS = frozenset(
    {
        RecoveryActionType.SEND_REMINDER,
        RecoveryActionType.SEND_PAYMENT_LINK,
        RecoveryActionType.OFFER_DISCOUNT,
    }
)

RETRY_ACTIONS = frozenset({RecoveryActionType.RETRY_NOW, RecoveryActionType.RETRY_LATER})


@dataclass(frozen=True)
class ProposedAction:
    action_type: str
    discount_percent: Decimal | None = None
    discount_amount: Decimal | None = None
    channel: str | None = None
    scheduled_for: datetime | None = None
    metadata: dict[str, Any] = field(default_factory=dict)


@dataclass
class PolicyEvaluationResult:
    allowed: bool
    requires_approval: bool
    risk_level: RiskLevel
    reason: str
    policy_ids: list[str]
    policy_version: str = POLICY_VERSION

    def to_public_dict(self) -> dict[str, object]:
        return {
            "allowed": self.allowed,
            "requires_approval": self.requires_approval,
            "risk_level": str(self.risk_level),
            "reason": self.reason,
            "policy_ids": list(self.policy_ids),
            "policy_version": self.policy_version,
        }


@dataclass
class PolicyContext:
    case: RecoveryCase
    merchant: Merchant
    customer: Customer | None
    payment: Payment | None
    settings: RecoverySettings
    now: datetime
    retry_count: int
    communications_last_24h: int
    discount_spent_today: Decimal
    blocked_action_types: frozenset[str]
    customer_opted_out: bool
    suspicious: bool
    source_mismatch: bool
    discount_eligible: bool
    merchant_id: UUID
