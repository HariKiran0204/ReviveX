from __future__ import annotations

from datetime import datetime
from typing import Any
from uuid import UUID

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from recoverai_db.enums import PaymentStatus
from recoverai_db.models import Cart, Notification, Payment, Subscription
from recoverai_eval.schema import CaseContext


def case_context_from_domain(
    session: Session,
    *,
    merchant_id: UUID,
    case_id: UUID,
    amount: Any,
    failure_reason: str | None,
    attempt_number: int,
    customer_id: UUID | None,
    payment: Payment | None,
    cart_id: UUID | None,
    subscription_id: UUID | None,
    lifetime_value: Any | None,
    opened_at: datetime | None,
    case_type: str | None = None,
) -> CaseContext:
    historical_success = None
    historical_recovery = None
    prior_failures = 0
    prior_captures = 0
    days_since_purchase = None
    if customer_id is not None:
        payments = list(
            session.scalars(
                select(Payment).where(
                    Payment.merchant_id == merchant_id,
                    Payment.customer_id == customer_id,
                )
            )
        )
        prior_captures = sum(1 for item in payments if item.status == PaymentStatus.CAPTURED)
        prior_failures = sum(1 for item in payments if item.status == PaymentStatus.FAILED)
        total = prior_captures + prior_failures
        if total:
            historical_success = prior_captures / total
        recovered_cases = [
            item
            for item in payments
            if item.status == PaymentStatus.CAPTURED and item.captured_at is not None
        ]
        if payments:
            historical_recovery = len(recovered_cases) / max(len(payments), 1)
        last_capture = max(
            (item.captured_at for item in payments if item.captured_at is not None),
            default=None,
        )
        if last_capture is not None and opened_at is not None:
            days_since_purchase = max((opened_at - last_capture).total_seconds() / 86400.0, 0.0)

    comms = 0
    days_contact = None
    if customer_id is not None:
        comms = int(
            session.scalar(
                select(func.count()).where(
                    Notification.merchant_id == merchant_id,
                    Notification.customer_id == customer_id,
                )
            )
            or 0
        )
        last_sent = session.scalar(
            select(func.max(Notification.sent_at)).where(
                Notification.merchant_id == merchant_id,
                Notification.customer_id == customer_id,
            )
        )
        if last_sent is not None and opened_at is not None:
            days_contact = max((opened_at - last_sent).total_seconds() / 86400.0, 0.0)

    cart_age = None
    cart_value = None
    if cart_id is not None:
        cart = session.get(Cart, cart_id)
        if cart is not None:
            cart_value = float(cart.total)
            if cart.abandoned_at is not None and opened_at is not None:
                cart_age = max((opened_at - cart.abandoned_at).total_seconds() / 3600.0, 0.0)

    subscription_state = "NONE"
    if subscription_id is not None:
        sub = session.get(Subscription, subscription_id)
        if sub is not None:
            subscription_state = sub.status

    hour = opened_at.hour if opened_at is not None else None
    dow = opened_at.weekday() if opened_at is not None else None
    return CaseContext(
        amount=float(amount),
        failure_reason=failure_reason or "UNKNOWN",
        attempt_number=max(attempt_number, 1),
        payment_method=payment.payment_method if payment is not None else None,
        historical_success_rate=historical_success,
        historical_recovery_rate=historical_recovery,
        customer_lifetime_value=float(lifetime_value) if lifetime_value is not None else None,
        days_since_last_purchase=days_since_purchase,
        cart_age_hours=cart_age,
        cart_value=cart_value,
        subscription_state=subscription_state,
        communication_count=comms,
        days_since_last_contact=days_contact,
        hour_of_day=hour,
        day_of_week=dow,
        merchant_id=str(merchant_id),
        recovery_case_id=str(case_id),
        customer_id=str(customer_id) if customer_id else None,
        prior_failures=prior_failures,
        prior_captures=prior_captures,
        case_type=case_type,
    )
