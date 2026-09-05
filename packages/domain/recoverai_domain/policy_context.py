from __future__ import annotations

from datetime import UTC, datetime, timedelta
from decimal import Decimal
from typing import Any
from uuid import UUID

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from recoverai_db.enums import RecoveryActionStatus, RecoveryActionType
from recoverai_db.models import Merchant, Notification, RecoveryAction, RecoveryCase
from recoverai_db.repositories import CustomerRepository, PaymentRepository
from recoverai_domain.policy_types import PolicyContext
from recoverai_domain.recovery_config import RecoverySettings, load_recovery_settings


def build_policy_context(
    session: Session,
    case: RecoveryCase,
    *,
    settings: RecoverySettings | None = None,
    now: datetime | None = None,
) -> PolicyContext:
    resolved_now = now or datetime.now(UTC)
    merchant = session.get(Merchant, case.merchant_id)
    if merchant is None:
        raise ValueError(f"Merchant {case.merchant_id} was not found")
    base = settings or load_recovery_settings()
    merged = base.merge_merchant(merchant.settings)
    customer = CustomerRepository(session).get_customer(case.merchant_id, case.customer_id)
    payment = None
    if case.payment_id is not None:
        payment = PaymentRepository(session).get_payment(case.merchant_id, case.payment_id)
    customer_meta = (customer.metadata_json if customer is not None else None) or {}
    merchant_policy = _policy_dict(merchant.settings)
    blocked = _blocked_actions(merchant_policy)
    return PolicyContext(
        case=case,
        merchant=merchant,
        customer=customer,
        payment=payment,
        settings=merged,
        now=resolved_now,
        retry_count=_retry_count(session, case),
        communications_last_24h=_communications_last_24h(
            session, case.merchant_id, case.customer_id, resolved_now
        ),
        discount_spent_today=_discount_spent_today(session, case.merchant_id, resolved_now),
        blocked_action_types=blocked,
        customer_opted_out=_truthy(customer_meta.get("communication_opt_out")),
        suspicious=_is_suspicious(case, customer_meta),
        source_mismatch=_is_source_mismatch(case, customer_meta),
        discount_eligible=not _truthy(customer_meta.get("discount_ineligible")),
        merchant_id=case.merchant_id,
    )


def _policy_dict(settings: dict[str, Any] | None) -> dict[str, Any]:
    if not settings:
        return {}
    nested = settings.get("policy")
    if isinstance(nested, dict):
        return nested
    return settings


def _blocked_actions(policy: dict[str, Any]) -> frozenset[str]:
    raw = policy.get("blocked_action_types") or []
    if not isinstance(raw, list):
        return frozenset()
    return frozenset(str(item) for item in raw)


def _truthy(value: object) -> bool:
    if isinstance(value, bool):
        return value
    if value is None:
        return False
    return str(value).strip().lower() in {"1", "true", "yes", "on"}


def _is_suspicious(case: RecoveryCase, customer_meta: dict[str, Any]) -> bool:
    if _truthy(customer_meta.get("suspicious")):
        return True
    mismatch = case.last_mismatch_reason
    return mismatch in {
        "MERCHANT_MISMATCH",
        "CUSTOMER_MISMATCH",
        "ORDER_MISMATCH",
        "PAYMENT_MISMATCH",
    }


def _is_source_mismatch(case: RecoveryCase, customer_meta: dict[str, Any]) -> bool:
    if _truthy(customer_meta.get("source_mismatch")):
        return True
    return case.last_mismatch_reason in {
        "MERCHANT_MISMATCH",
        "CUSTOMER_MISMATCH",
        "ORDER_MISMATCH",
        "PAYMENT_MISMATCH",
    }


def _retry_count(session: Session, case: RecoveryCase) -> int:
    counted = {
        RecoveryActionStatus.PENDING,
        RecoveryActionStatus.PLANNED,
        RecoveryActionStatus.APPROVAL_REQUIRED,
        RecoveryActionStatus.APPROVED,
        RecoveryActionStatus.EXECUTING,
        RecoveryActionStatus.SUCCEEDED,
        RecoveryActionStatus.COMPLETED,
    }
    stmt = (
        select(func.count())
        .select_from(RecoveryAction)
        .where(
            RecoveryAction.recovery_case_id == case.id,
            RecoveryAction.action_type.in_(
                [RecoveryActionType.RETRY_NOW, RecoveryActionType.RETRY_LATER]
            ),
            RecoveryAction.status.in_([str(item) for item in counted]),
        )
    )
    return int(session.scalar(stmt) or 0)


def _communications_last_24h(
    session: Session, merchant_id: UUID, customer_id: UUID, now: datetime
) -> int:
    since = now - timedelta(hours=24)
    stmt = (
        select(func.count())
        .select_from(Notification)
        .where(
            Notification.merchant_id == merchant_id,
            Notification.customer_id == customer_id,
            Notification.created_at >= since,
            Notification.status != "CANCELLED",
        )
    )
    return int(session.scalar(stmt) or 0)


def _discount_spent_today(session: Session, merchant_id: UUID, now: datetime) -> Decimal:
    start = datetime(now.year, now.month, now.day, tzinfo=UTC)
    counted = {
        str(RecoveryActionStatus.SUCCEEDED),
        str(RecoveryActionStatus.COMPLETED),
        str(RecoveryActionStatus.EXECUTING),
        str(RecoveryActionStatus.PENDING),
        str(RecoveryActionStatus.APPROVED),
        str(RecoveryActionStatus.APPROVAL_REQUIRED),
    }
    stmt = select(func.coalesce(func.sum(RecoveryAction.amount), 0)).where(
        RecoveryAction.merchant_id == merchant_id,
        RecoveryAction.action_type == RecoveryActionType.OFFER_DISCOUNT,
        RecoveryAction.status.in_(list(counted)),
        RecoveryAction.created_at >= start,
    )
    value = session.scalar(stmt)
    return Decimal(str(value or 0))
