from __future__ import annotations

from typing import Any
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field
from sqlalchemy import select
from sqlalchemy.orm import Session

from recoverai_db.models import (
    Cart,
    Customer,
    Merchant,
    Payment,
    RecoveryAction,
    RecoveryCase,
    Subscription,
)
from recoverai_db.repositories import PaymentRepository
from recoverai_domain.agents.security import looks_like_injection, strip_secrets, wrap_untrusted
from recoverai_domain.policy_context import build_policy_context
from recoverai_domain.recovery_config import RecoverySettings


class RecoveryAgentContext(BaseModel):
    """Bounded snapshot for agents. No secrets, no raw DB dump."""

    model_config = ConfigDict(extra="forbid")

    case: dict[str, Any]
    customer: dict[str, Any]
    payment: dict[str, Any] | None = None
    cart: dict[str, Any] | None = None
    subscription: dict[str, Any] | None = None
    previous_actions: list[dict[str, Any]] = Field(default_factory=list)
    policy_summary: dict[str, Any] = Field(default_factory=dict)
    customer_untrusted_text: str = ""
    injection_suspected: bool = False
    suspicious: bool = False
    source_mismatch: bool = False


def build_agent_context(
    session: Session,
    case: RecoveryCase,
    *,
    settings: RecoverySettings | None = None,
) -> RecoveryAgentContext:
    merchant = session.get(Merchant, case.merchant_id)
    customer = session.get(Customer, case.customer_id)
    payment = None
    if case.payment_id is not None:
        payment = PaymentRepository(session).get_payment(case.merchant_id, case.payment_id)
    cart = session.get(Cart, case.cart_id) if case.cart_id else None
    subscription = session.get(Subscription, case.subscription_id) if case.subscription_id else None
    policy = build_policy_context(session, case, settings=settings)
    notes = ""
    if customer is not None and customer.metadata_json:
        notes = str(customer.metadata_json.get("notes") or "")
    failure_text = payment.failure_reason if payment is not None else None
    untrusted = wrap_untrusted("customer_notes", notes)
    return RecoveryAgentContext(
        case={
            "id": str(case.id),
            "merchant_id": str(case.merchant_id),
            "case_type": case.case_type,
            "status": case.status,
            "amount_at_risk": str(case.amount_at_risk),
            "amount_recovered": str(case.amount_recovered),
            "currency": case.currency,
            "last_mismatch_reason": case.last_mismatch_reason,
        },
        customer=_customer_summary(customer),
        payment=_payment_summary(payment),
        cart=_cart_summary(cart),
        subscription=_subscription_summary(subscription),
        previous_actions=_action_summaries(session, case.id),
        policy_summary={
            "policy_version": policy.settings.policy_version,
            "max_discount_percent": str(policy.settings.max_discount_percent),
            "automatic_recovery_enabled": policy.settings.automatic_recovery_enabled,
            "merchant_name": merchant.name if merchant is not None else None,
        },
        customer_untrusted_text=untrusted,
        injection_suspected=looks_like_injection(notes) or looks_like_injection(failure_text),
        suspicious=policy.suspicious,
        source_mismatch=policy.source_mismatch,
    )


def _customer_summary(customer: Customer | None) -> dict[str, Any]:
    if customer is None:
        return {}
    return strip_secrets(
        {
            "id": str(customer.id),
            "lifetime_value": str(customer.lifetime_value),
            "has_email": bool(customer.email),
            "opt_out": bool((customer.metadata_json or {}).get("communication_opt_out")),
        }
    )


def _payment_summary(payment: Payment | None) -> dict[str, Any] | None:
    if payment is None:
        return None
    return {
        "status": payment.status,
        "amount": str(payment.amount),
        "currency": payment.currency,
        "failure_code": payment.failure_code,
        "method": payment.payment_method,
        "provider": payment.provider,
    }


def _cart_summary(cart: Cart | None) -> dict[str, Any] | None:
    if cart is None:
        return None
    return {"status": cart.status, "total": str(cart.total), "currency": cart.currency}


def _subscription_summary(subscription: Subscription | None) -> dict[str, Any] | None:
    if subscription is None:
        return None
    return {"status": subscription.status}


def _action_summaries(session: Session, case_id: UUID) -> list[dict[str, Any]]:
    rows = list(
        session.scalars(
            select(RecoveryAction)
            .where(RecoveryAction.recovery_case_id == case_id)
            .order_by(RecoveryAction.created_at.desc())
            .limit(8)
        )
    )
    return [
        {"action_type": row.action_type, "status": row.status, "risk_level": row.risk_level}
        for row in rows
    ]
