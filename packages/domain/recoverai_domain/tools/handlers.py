from __future__ import annotations

from dataclasses import dataclass, field
from datetime import UTC, datetime
from decimal import Decimal
from typing import Any
from uuid import UUID

from sqlalchemy.orm import Session

from recoverai_db.enums import (
    NotificationChannel,
    NotificationStatus,
    PaymentStatus,
    RecoveryCaseStatus,
)
from recoverai_db.models import (
    Cart,
    Customer,
    Notification,
    Payment,
    PaymentAttempt,
    RecoveryCase,
    Subscription,
)
from recoverai_db.repositories import PaymentRepository
from recoverai_domain.money import as_money
from recoverai_domain.processing import internal_payment_uuid
from recoverai_domain.transitions import transition_case
from recoverai_providers.base import PaymentProvider
from recoverai_providers.errors import ProviderError, ProviderNotFoundError
from recoverai_providers.models import (
    CreatePaymentLinkRequest,
    CreatePaymentRequest,
    CustomerHistory,
    FailureReason,
    ProviderName,
)


@dataclass
class HandlerResult:
    success: bool
    output: dict[str, Any]
    provider: str | None = None
    provider_reference: str | None = None
    amount: Decimal | None = None
    error_code: str | None = None
    error_message: str | None = None
    case_status: RecoveryCaseStatus | None = None
    simulated: bool = True
    metadata: dict[str, Any] = field(default_factory=dict)


@dataclass
class HandlerContext:
    session: Session
    case: RecoveryCase
    merchant_id: UUID
    customer: Customer | None
    payment: Payment | None
    provider: PaymentProvider
    payload: dict[str, Any]
    attempt_number: int
    idempotency_key: str
    actor_id: str | None
    correlation_id: str | None
    queue: Any | None = None


def handle_get_customer_history(ctx: HandlerContext) -> HandlerResult:
    customer = ctx.customer
    if customer is None:
        return HandlerResult(
            success=False,
            output={},
            error_code="MISSING_CUSTOMER",
            error_message="Customer not found",
        )
    payments = PaymentRepository(ctx.session).list_for_customer(ctx.merchant_id, customer.id)
    return HandlerResult(
        success=True,
        output={
            "customer_id": str(customer.id),
            "email": customer.email,
            "lifetime_value": str(customer.lifetime_value),
            "payments": [
                {
                    "id": str(item.id),
                    "status": item.status,
                    "amount": str(item.amount),
                    "provider_payment_id": item.provider_payment_id,
                }
                for item in payments
            ],
        },
        simulated=True,
    )


def handle_get_payment_details(ctx: HandlerContext) -> HandlerResult:
    payment = ctx.payment
    if payment is None:
        return HandlerResult(
            success=False,
            output={},
            error_code="MISSING_PAYMENT",
            error_message="Payment not found",
        )
    return HandlerResult(
        success=True,
        output=_payment_dict(payment),
        provider=payment.provider,
        provider_reference=payment.provider_payment_id,
    )


def handle_get_cart_details(ctx: HandlerContext) -> HandlerResult:
    if ctx.case.cart_id is None:
        return HandlerResult(success=True, output={"cart": None})
    cart = ctx.session.get(Cart, ctx.case.cart_id)
    if cart is None:
        return HandlerResult(success=True, output={"cart": None})
    return HandlerResult(
        success=True,
        output={
            "cart_id": str(cart.id),
            "status": cart.status,
            "total": str(cart.total),
            "discount": str(cart.discount),
            "currency": cart.currency,
        },
    )


def handle_get_subscription_details(ctx: HandlerContext) -> HandlerResult:
    if ctx.case.subscription_id is None:
        return HandlerResult(success=True, output={"subscription": None})
    row = ctx.session.get(Subscription, ctx.case.subscription_id)
    if row is None:
        return HandlerResult(success=True, output={"subscription": None})
    return HandlerResult(
        success=True,
        output={
            "subscription_id": str(row.id),
            "status": row.status,
            "amount": str(row.amount),
            "provider_subscription_id": row.provider_subscription_id,
        },
    )


def handle_get_recovery_case(ctx: HandlerContext) -> HandlerResult:
    case = ctx.case
    return HandlerResult(
        success=True,
        output={
            "case_id": str(case.id),
            "status": case.status,
            "amount_at_risk": str(case.amount_at_risk),
            "amount_recovered": str(case.amount_recovered),
            "currency": case.currency,
            "version": case.version,
        },
    )


def handle_calculate_recovery_probability(ctx: HandlerContext) -> HandlerResult:
    from recoverai_db.enums import RecoveryActionType
    from recoverai_eval.errors import InferenceError
    from recoverai_eval.inference.api import predict_recovery_probability
    from recoverai_eval.inference.domain import case_context_from_domain
    from recoverai_eval.inference.persist import persist_prediction

    action = ctx.payload.get("action") or RecoveryActionType.RETRY_NOW.value
    if not isinstance(action, str):
        action = str(action)
    try:
        context = case_context_from_domain(
            ctx.session,
            merchant_id=ctx.merchant_id,
            case_id=ctx.case.id,
            amount=ctx.case.amount_at_risk,
            failure_reason=ctx.payment.failure_code if ctx.payment is not None else None,
            attempt_number=ctx.attempt_number,
            customer_id=ctx.customer.id if ctx.customer is not None else None,
            payment=ctx.payment,
            cart_id=ctx.case.cart_id,
            subscription_id=ctx.case.subscription_id,
            lifetime_value=ctx.customer.lifetime_value if ctx.customer is not None else None,
            opened_at=ctx.case.opened_at,
            case_type=ctx.case.case_type,
        )
        scored = predict_recovery_probability(context, action, allow_fallback=True)
        persist_prediction(
            ctx.session,
            merchant_id=ctx.merchant_id,
            recovery_case_id=ctx.case.id,
            action=action,
            probability=scored.probability,
            feature_version=scored.feature_version,
            model_version=scored.model_version,
            source=scored.source,
            diagnostics=scored.diagnostics,
        )
    except InferenceError as exc:
        return HandlerResult(
            success=False,
            output={},
            error_code=exc.code,
            error_message=exc.message,
        )
    return HandlerResult(
        success=True,
        output={
            "probability": scored.probability,
            "model_version": scored.model_version,
            "feature_version": scored.feature_version,
            "source": scored.source,
            "action": action,
            "diagnostics": scored.diagnostics,
        },
    )


def handle_retry_payment(ctx: HandlerContext) -> HandlerResult:
    original = ctx.payment
    if original is None:
        return HandlerResult(
            success=False,
            output={},
            error_code="MISSING_PAYMENT",
            error_message="Retry requires a case payment",
        )
    original_provider_id = original.provider_payment_id
    repo = PaymentRepository(ctx.session)
    attempt_number = ctx.payload.get("attempt_number") or repo.next_attempt_number(original.id)
    if not isinstance(attempt_number, int):
        attempt_number = int(attempt_number)
    history = CustomerHistory()
    if ctx.customer is not None:
        history = CustomerHistory(lifetime_value=ctx.customer.lifetime_value)
    failure = None
    if original.failure_code:
        try:
            failure = FailureReason(original.failure_code)
        except ValueError:
            failure = FailureReason.UNKNOWN
    try:
        snapshot = ctx.provider.create_payment(
            CreatePaymentRequest(
                merchant_reference=str(ctx.case.id),
                amount=original.amount,
                currency=original.currency,
                customer_reference=str(original.customer_id),
                provider_order_id=original.provider_order_id,
                attempt_number=attempt_number,
                customer_history=history,
                intended_status=ctx.payload.get("intended_status"),
                failure_reason=failure,
                metadata={
                    "recovery_case_id": str(ctx.case.id),
                    "original_provider_payment_id": original_provider_id,
                    "idempotency_key": ctx.idempotency_key,
                },
            )
        )
    except ProviderError as exc:
        return HandlerResult(
            success=False,
            output={},
            error_code=exc.code,
            error_message=exc.message,
            provider=ctx.provider.name,
        )

    new_payment = Payment(
        id=internal_payment_uuid(ctx.merchant_id, snapshot.provider, snapshot.provider_payment_id),
        merchant_id=ctx.merchant_id,
        customer_id=original.customer_id,
        provider=snapshot.provider,
        provider_payment_id=snapshot.provider_payment_id,
        provider_order_id=snapshot.provider_order_id,
        amount=snapshot.amount,
        currency=snapshot.currency,
        status=snapshot.status,
        payment_method=snapshot.payment_method,
        failure_code=str(snapshot.failure_reason) if snapshot.failure_reason else None,
        failed_at=snapshot.occurred_at if snapshot.status == PaymentStatus.FAILED else None,
        captured_at=snapshot.occurred_at if snapshot.status == PaymentStatus.CAPTURED else None,
    )
    ctx.session.add(new_payment)
    
    if snapshot.provider == ProviderName.SIMULATOR and ctx.queue is not None:
        from recoverai_domain.ingestion import EventIngestionService
        from recoverai_providers.simulator.events import build_provider_event
        
        provider_event = build_provider_event(
            snapshot,
            seed=int(datetime.now(UTC).timestamp()),
            correlation_id=ctx.correlation_id,
            extra_payload={"source": "retry_payment"}
        )
        EventIngestionService().ingest(
            ctx.session,
            provider_event,
            merchant_id=ctx.merchant_id,
            queue=ctx.queue
        )
        
    ctx.session.add(
        PaymentAttempt(
            payment_id=original.id,
            attempt_number=attempt_number,
            status=snapshot.status,
            amount=snapshot.amount,
            currency=snapshot.currency,
            failure_code=str(snapshot.failure_reason) if snapshot.failure_reason else None,
            attempted_at=snapshot.occurred_at,
        )
    )
    ctx.session.flush()
    ctx.session.refresh(original)
    if original.provider_payment_id != original_provider_id:
        return HandlerResult(
            success=False,
            output={},
            error_code="ORIGINAL_PAYMENT_MUTATED",
            error_message="Original failed payment must remain historical",
        )
    return HandlerResult(
        success=True,
        output={
            "original_provider_payment_id": original_provider_id,
            "original_status": original.status,
            "new_provider_payment_id": snapshot.provider_payment_id,
            "new_payment_id": str(new_payment.id),
            "provider_status": snapshot.status,
            "attempt_number": attempt_number,
            "provider": snapshot.provider,
            "simulated": snapshot.provider == ProviderName.SIMULATOR,
        },
        provider=snapshot.provider,
        provider_reference=snapshot.provider_payment_id,
        amount=snapshot.amount,
        case_status=RecoveryCaseStatus.ACTION_COMPLETED,
        metadata={"new_payment_id": str(new_payment.id), "executed": True},
    )


def handle_schedule_retry(ctx: HandlerContext) -> HandlerResult:
    scheduled_for = datetime.fromisoformat(str(ctx.payload["scheduled_for"]).replace("Z", "+00:00"))
    if scheduled_for.tzinfo is None:
        scheduled_for = scheduled_for.replace(tzinfo=UTC)
    return HandlerResult(
        success=True,
        output={
            "scheduled_for": scheduled_for.isoformat(),
            "executed": False,
            "note": "Future workers must re-check payment, case, policy, and idempotency",
        },
        case_status=RecoveryCaseStatus.RETRY_SCHEDULED,
        metadata={"scheduled_for": scheduled_for.isoformat(), "executed": False},
    )


def handle_create_payment_link(ctx: HandlerContext) -> HandlerResult:
    amount = as_money(ctx.case.amount_at_risk)
    try:
        snapshot = ctx.provider.create_payment_link(
            CreatePaymentLinkRequest(
                merchant_reference=str(ctx.case.id),
                amount=amount,
                currency=ctx.case.currency,
                customer_reference=str(ctx.case.customer_id),
                description=ctx.payload.get("description"),
                metadata={"recovery_case_id": str(ctx.case.id), "simulated": True},
            )
        )
    except ProviderError as exc:
        return HandlerResult(
            success=False,
            output={},
            error_code=exc.code,
            error_message=exc.message,
            provider=ctx.provider.name,
        )
    if ctx.payment is not None:
        ctx.payment.provider_payment_link_id = snapshot.provider_payment_link_id
    return HandlerResult(
        success=True,
        output={
            "provider": snapshot.provider,
            "provider_payment_link_id": snapshot.provider_payment_link_id,
            "url": snapshot.url,
            "status": snapshot.status,
            "simulated": snapshot.simulated,
        },
        provider=snapshot.provider,
        provider_reference=snapshot.provider_payment_link_id,
        amount=snapshot.amount,
        case_status=RecoveryCaseStatus.ACTION_COMPLETED,
        simulated=snapshot.simulated,
    )


def handle_send_notification(ctx: HandlerContext) -> HandlerResult:
    if ctx.customer is None:
        return HandlerResult(
            success=False,
            output={},
            error_code="MISSING_CUSTOMER",
            error_message="Notification requires a customer",
        )
    channel = ctx.payload.get("channel") or NotificationChannel.EMAIL
    now = datetime.now(UTC)
    row = Notification(
        merchant_id=ctx.merchant_id,
        customer_id=ctx.customer.id,
        recovery_case_id=ctx.case.id,
        channel=str(channel),
        status=NotificationStatus.SENT,
        provider=ProviderName.SIMULATOR,
        provider_reference=f"notif_sim_{ctx.idempotency_key[:24]}",
        subject=ctx.payload.get("subject") or "Recovery reminder",
        body_preview=ctx.payload.get("body_preview") or "Simulated recovery reminder",
        sent_at=now,
        metadata_json={"simulated": True, "idempotency_key": ctx.idempotency_key},
    )
    ctx.session.add(row)
    ctx.session.flush()
    return HandlerResult(
        success=True,
        output={
            "notification_id": str(row.id),
            "channel": row.channel,
            "status": row.status,
            "provider": row.provider,
            "simulated": True,
        },
        provider=row.provider,
        provider_reference=row.provider_reference,
        case_status=RecoveryCaseStatus.ACTION_COMPLETED,
    )


def handle_offer_discount(ctx: HandlerContext) -> HandlerResult:
    percent = Decimal(str(ctx.payload["discount_percent"]))
    amount = as_money((as_money(ctx.case.amount_at_risk) * percent) / Decimal("100"))
    if ctx.case.cart_id is not None:
        cart = ctx.session.get(Cart, ctx.case.cart_id)
        if cart is not None:
            cart.discount = as_money(cart.discount + amount)
    return HandlerResult(
        success=True,
        output={
            "discount_percent": str(percent),
            "discount_amount": str(amount),
            "currency": ctx.case.currency,
            "executed": True,
        },
        amount=amount,
        case_status=RecoveryCaseStatus.ACTION_COMPLETED,
        metadata={"discount_percent": str(percent), "executed": True},
    )


def handle_check_payment_status(ctx: HandlerContext) -> HandlerResult:
    provider_payment_id = ctx.payload.get("provider_payment_id")
    if provider_payment_id:
        try:
            snapshot = ctx.provider.fetch_payment(str(provider_payment_id))
            return HandlerResult(
                success=True,
                output=snapshot.model_dump(mode="json"),
                provider=snapshot.provider,
                provider_reference=snapshot.provider_payment_id,
            )
        except ProviderNotFoundError:
            pass
        except ProviderError as exc:
            return HandlerResult(
                success=False,
                output={},
                error_code=exc.code,
                error_message=exc.message,
                provider=ctx.provider.name,
            )
    if ctx.payment is None:
        return HandlerResult(
            success=False,
            output={},
            error_code="MISSING_PAYMENT",
            error_message="Payment not found",
        )
    return HandlerResult(
        success=True, output=_payment_dict(ctx.payment), provider=ctx.payment.provider
    )


def handle_check_subscription_status(ctx: HandlerContext) -> HandlerResult:
    return handle_get_subscription_details(ctx)


def handle_escalate_to_human(ctx: HandlerContext) -> HandlerResult:
    reason = ctx.payload.get("reason") or "Escalated to a human operator"
    return HandlerResult(
        success=True,
        output={"escalated": True, "reason": reason, "amount_recovered_claimed": False},
        case_status=RecoveryCaseStatus.ESCALATED,
        metadata={"executed": True},
    )


def handle_pause_recovery(ctx: HandlerContext) -> HandlerResult:
    reason = ctx.payload.get("reason") or "Automatic recovery paused"
    return HandlerResult(
        success=True,
        output={"stopped": True, "reason": reason},
        case_status=RecoveryCaseStatus.STOPPED,
        metadata={"executed": True},
    )


def apply_case_outcome(
    session: Session,
    case: RecoveryCase,
    result: HandlerResult,
    actor_type: str,
    correlation_id: str | None,
) -> None:
    target = result.case_status
    if target is None:
        return
    current = case.status
    if current == str(target):
        return
    if str(target) == RecoveryCaseStatus.ACTION_COMPLETED:
        if current in {
            RecoveryCaseStatus.POLICY_CHECK,
            RecoveryCaseStatus.AWAITING_APPROVAL,
        }:
            transition_case(
                session,
                case,
                RecoveryCaseStatus.EXECUTING,
                actor_type=actor_type,
                correlation_id=correlation_id,
                summary="Tool execution started",
            )
        if case.status == RecoveryCaseStatus.EXECUTING:
            transition_case(
                session,
                case,
                RecoveryCaseStatus.ACTION_COMPLETED,
                actor_type=actor_type,
                correlation_id=correlation_id,
                summary="Tool execution recorded. Verification still owns recovered revenue.",
            )
        return
    if str(target) == RecoveryCaseStatus.RETRY_SCHEDULED:
        if current == RecoveryCaseStatus.POLICY_CHECK:
            transition_case(
                session,
                case,
                RecoveryCaseStatus.RETRY_SCHEDULED,
                actor_type=actor_type,
                correlation_id=correlation_id,
                summary="Retry scheduled; not executed",
            )
        return
    if str(target) in {RecoveryCaseStatus.ESCALATED, RecoveryCaseStatus.STOPPED} and current in {
        RecoveryCaseStatus.POLICY_CHECK,
        RecoveryCaseStatus.AWAITING_APPROVAL,
        RecoveryCaseStatus.FAILED,
        RecoveryCaseStatus.NOT_RECOVERED,
    }:
        transition_case(
            session,
            case,
            target,
            actor_type=actor_type,
            correlation_id=correlation_id,
            summary=str(result.output.get("reason") or f"Case moved to {target}"),
        )


def _payment_dict(payment: Payment) -> dict[str, Any]:
    return {
        "payment_id": str(payment.id),
        "provider": payment.provider,
        "provider_payment_id": payment.provider_payment_id,
        "provider_order_id": payment.provider_order_id,
        "status": payment.status,
        "amount": str(payment.amount),
        "currency": payment.currency,
        "failure_code": payment.failure_code,
    }


HANDLERS = {
    "get_customer_history": handle_get_customer_history,
    "get_payment_details": handle_get_payment_details,
    "get_cart_details": handle_get_cart_details,
    "get_subscription_details": handle_get_subscription_details,
    "get_recovery_case": handle_get_recovery_case,
    "calculate_recovery_probability": handle_calculate_recovery_probability,
    "retry_payment": handle_retry_payment,
    "schedule_retry": handle_schedule_retry,
    "create_payment_link": handle_create_payment_link,
    "send_notification": handle_send_notification,
    "offer_discount": handle_offer_discount,
    "check_payment_status": handle_check_payment_status,
    "check_subscription_status": handle_check_subscription_status,
    "escalate_to_human": handle_escalate_to_human,
    "pause_recovery": handle_pause_recovery,
}
