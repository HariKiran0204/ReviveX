from __future__ import annotations

import os
from dataclasses import dataclass
from decimal import Decimal

from recoverai_db.enums import RecoveryActionType
from recoverai_domain.money import as_money

OPTIMIZER_VERSION = "erv-v1"

RECOVERY_INTERVENTIONS = frozenset(
    {
        RecoveryActionType.RETRY_NOW,
        RecoveryActionType.RETRY_LATER,
        RecoveryActionType.SEND_PAYMENT_LINK,
        RecoveryActionType.SEND_REMINDER,
        RecoveryActionType.OFFER_DISCOUNT,
    }
)

CONTROL_STRATEGIES = frozenset({RecoveryActionType.ESCALATE, RecoveryActionType.DO_NOTHING})

# Lower is less customer friction. Explicit ranks — not dict iteration order.
FRICTION_RANK: dict[str, int] = {
    RecoveryActionType.DO_NOTHING.value: 0,
    RecoveryActionType.RETRY_LATER.value: 1,
    RecoveryActionType.SEND_PAYMENT_LINK.value: 2,
    RecoveryActionType.SEND_REMINDER.value: 3,
    RecoveryActionType.RETRY_NOW.value: 4,
    RecoveryActionType.OFFER_DISCOUNT.value: 5,
    RecoveryActionType.ESCALATE.value: 6,
}

# Lower is simpler. Explicit ranks — not dict iteration order.
SIMPLICITY_RANK: dict[str, int] = {
    RecoveryActionType.DO_NOTHING.value: 0,
    RecoveryActionType.SEND_REMINDER.value: 1,
    RecoveryActionType.RETRY_LATER.value: 2,
    RecoveryActionType.SEND_PAYMENT_LINK.value: 3,
    RecoveryActionType.RETRY_NOW.value: 4,
    RecoveryActionType.OFFER_DISCOUNT.value: 5,
    RecoveryActionType.ESCALATE.value: 6,
}

LEGAL_ACTIONS: tuple[str, ...] = tuple(item.value for item in RecoveryActionType)


def _decimal_env(name: str, default: Decimal) -> Decimal:
    raw = os.environ.get(name)
    if raw is None or raw.strip() == "":
        return default
    return Decimal(raw)


def _int_env(name: str, default: int) -> int:
    raw = os.environ.get(name)
    if raw is None or raw.strip() == "":
        return default
    return int(raw)


@dataclass(frozen=True)
class ActionCostAssumptions:
    """Prototype INR costs. These are not Razorpay fee schedules."""

    intervention_cost: Decimal
    communication_cost: Decimal
    risk_penalty: Decimal


@dataclass(frozen=True)
class OptimizerSettings:
    """Configurable ERV prototype assumptions and freshness rules."""

    optimizer_version: str = OPTIMIZER_VERSION
    prediction_ttl_minutes: int = 60
    default_discount_percent: Decimal = Decimal("5")
    tie_epsilon: Decimal = Decimal("0.01")
    retry_now: ActionCostAssumptions = ActionCostAssumptions(
        intervention_cost=Decimal("5.00"),
        communication_cost=Decimal("0.00"),
        risk_penalty=Decimal("15.00"),
    )
    retry_later: ActionCostAssumptions = ActionCostAssumptions(
        intervention_cost=Decimal("2.00"),
        communication_cost=Decimal("0.00"),
        risk_penalty=Decimal("4.00"),
    )
    send_payment_link: ActionCostAssumptions = ActionCostAssumptions(
        intervention_cost=Decimal("3.00"),
        communication_cost=Decimal("1.50"),
        risk_penalty=Decimal("8.00"),
    )
    send_reminder: ActionCostAssumptions = ActionCostAssumptions(
        intervention_cost=Decimal("0.50"),
        communication_cost=Decimal("1.50"),
        risk_penalty=Decimal("12.00"),
    )
    offer_discount: ActionCostAssumptions = ActionCostAssumptions(
        intervention_cost=Decimal("1.00"),
        communication_cost=Decimal("1.50"),
        risk_penalty=Decimal("40.00"),
    )
    escalate: ActionCostAssumptions = ActionCostAssumptions(
        intervention_cost=Decimal("250.00"),
        communication_cost=Decimal("0.00"),
        risk_penalty=Decimal("30.00"),
    )
    do_nothing: ActionCostAssumptions = ActionCostAssumptions(
        intervention_cost=Decimal("0.00"),
        communication_cost=Decimal("0.00"),
        risk_penalty=Decimal("0.00"),
    )

    @classmethod
    def from_env(cls) -> OptimizerSettings:
        return cls(
            optimizer_version=os.environ.get("OPTIMIZER_VERSION") or OPTIMIZER_VERSION,
            prediction_ttl_minutes=_int_env("PREDICTION_TTL_MINUTES", 60),
            default_discount_percent=_decimal_env("DEFAULT_DISCOUNT_PERCENT", Decimal("5")),
            tie_epsilon=_decimal_env("ERV_TIE_EPSILON", Decimal("0.01")),
            retry_now=ActionCostAssumptions(
                intervention_cost=_decimal_env("COST_RETRY_NOW", Decimal("5.00")),
                communication_cost=_decimal_env("COST_RETRY_NOW_COMMUNICATION", Decimal("0.00")),
                risk_penalty=_decimal_env("RISK_PENALTY_RETRY_NOW", Decimal("15.00")),
            ),
            retry_later=ActionCostAssumptions(
                intervention_cost=_decimal_env("COST_RETRY_LATER", Decimal("2.00")),
                communication_cost=_decimal_env("COST_RETRY_LATER_COMMUNICATION", Decimal("0.00")),
                risk_penalty=_decimal_env("RISK_PENALTY_RETRY_LATER", Decimal("4.00")),
            ),
            send_payment_link=ActionCostAssumptions(
                intervention_cost=_decimal_env("COST_PAYMENT_LINK", Decimal("3.00")),
                communication_cost=_decimal_env("COST_PAYMENT_LINK_COMMUNICATION", Decimal("1.50")),
                risk_penalty=_decimal_env("RISK_PENALTY_PAYMENT_LINK", Decimal("8.00")),
            ),
            send_reminder=ActionCostAssumptions(
                intervention_cost=_decimal_env("COST_REMINDER", Decimal("0.50")),
                communication_cost=_decimal_env("COST_REMINDER_COMMUNICATION", Decimal("1.50")),
                risk_penalty=_decimal_env("RISK_PENALTY_REMINDER", Decimal("12.00")),
            ),
            offer_discount=ActionCostAssumptions(
                intervention_cost=_decimal_env("COST_DISCOUNT_INTERVENTION", Decimal("1.00")),
                communication_cost=_decimal_env("COST_DISCOUNT_COMMUNICATION", Decimal("1.50")),
                risk_penalty=_decimal_env("RISK_PENALTY_DISCOUNT", Decimal("40.00")),
            ),
            escalate=ActionCostAssumptions(
                intervention_cost=_decimal_env("COST_HUMAN_ESCALATION", Decimal("250.00")),
                communication_cost=_decimal_env("COST_ESCALATE_COMMUNICATION", Decimal("0.00")),
                risk_penalty=_decimal_env("RISK_PENALTY_ESCALATE", Decimal("30.00")),
            ),
            do_nothing=ActionCostAssumptions(
                intervention_cost=_decimal_env("COST_DO_NOTHING", Decimal("0.00")),
                communication_cost=_decimal_env("COST_DO_NOTHING_COMMUNICATION", Decimal("0.00")),
                risk_penalty=_decimal_env("RISK_PENALTY_DO_NOTHING", Decimal("0.00")),
            ),
        )

    def costs_for(self, action: str) -> ActionCostAssumptions:
        mapping = {
            RecoveryActionType.RETRY_NOW.value: self.retry_now,
            RecoveryActionType.RETRY_LATER.value: self.retry_later,
            RecoveryActionType.SEND_PAYMENT_LINK.value: self.send_payment_link,
            RecoveryActionType.SEND_REMINDER.value: self.send_reminder,
            RecoveryActionType.OFFER_DISCOUNT.value: self.offer_discount,
            RecoveryActionType.ESCALATE.value: self.escalate,
            RecoveryActionType.DO_NOTHING.value: self.do_nothing,
        }
        try:
            assumptions = mapping[action]
        except KeyError as exc:
            raise KeyError(f"Unknown recovery action: {action}") from exc
        return ActionCostAssumptions(
            intervention_cost=as_money(assumptions.intervention_cost),
            communication_cost=as_money(assumptions.communication_cost),
            risk_penalty=as_money(assumptions.risk_penalty),
        )


def load_optimizer_settings() -> OptimizerSettings:
    return OptimizerSettings.from_env()
