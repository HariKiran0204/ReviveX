"""Deterministic Phase 2 development seed data."""

from __future__ import annotations

import os
import sys
import uuid
from datetime import UTC, datetime
from decimal import Decimal

from recoverai_db.enums import (
    ActorType,
    CartStatus,
    MembershipRole,
    PaymentStatus,
    RecoveryCaseStatus,
    RecoveryCaseType,
    WebhookEventStatus,
)
from recoverai_db.models import (
    AuditEvent,
    Cart,
    CartItem,
    Customer,
    Merchant,
    MerchantMembership,
    Payment,
    PaymentAttempt,
    RecoveryCase,
    Subscription,
    User,
    WebhookEvent,
)
from recoverai_db.repositories import (
    AuditEventRepository,
    CustomerRepository,
    MerchantRepository,
    PaymentRepository,
    RecoveryCaseRepository,
)
from recoverai_db.session import SessionLocal

SEED_NAMESPACE = uuid.UUID("6ba7b810-9dad-11d1-80b4-00c04fd430c8")


def stable_id(name: str) -> uuid.UUID:
    return uuid.uuid5(SEED_NAMESPACE, name)


def seed(session_factory=SessionLocal) -> None:
    database_url = os.environ.get("DATABASE_URL")
    if not database_url:
        raise RuntimeError("DATABASE_URL is required to run the seed script")

    session = session_factory(database_url)
    merchants = MerchantRepository(session)

    if merchants.get_by_slug("acme-retail"):
        print("Seed data already present (acme-retail exists). Skipping.")
        session.close()
        return

    now = datetime.now(UTC)

    merchant_a = Merchant(
        id=stable_id("merchant:acme"),
        name="Acme Retail",
        slug="acme-retail",
        description="Demo merchant A",
        settings={
            "policy": {
                "automatic_recovery_enabled": True,
                "max_retry_attempts": 3,
                "max_discount_percent": "10",
                "max_daily_discount_budget": "5000",
                "high_value_approval_threshold": "25000",
                "medium_value_approval_threshold": "5000",
            }
        },
    )
    merchant_b = Merchant(
        id=stable_id("merchant:orbit"),
        name="Orbit Subscriptions",
        slug="orbit-subscriptions",
        description="Demo merchant B",
    )
    merchants.add(merchant_a)
    merchants.add(merchant_b)

    users = [
        User(
            id=stable_id("user:owner-a"),
            email="owner@acme.test",
            full_name="Acme Owner",
        ),
        User(
            id=stable_id("user:admin-a"),
            email="admin@acme.test",
            full_name="Acme Admin",
        ),
        User(
            id=stable_id("user:operator-b"),
            email="operator@orbit.test",
            full_name="Orbit Operator",
        ),
        User(
            id=stable_id("user:viewer-b"),
            email="viewer@orbit.test",
            full_name="Orbit Viewer",
        ),
    ]
    for user in users:
        merchants.add_user(user)

    memberships = [
        MerchantMembership(
            merchant_id=merchant_a.id,
            user_id=users[0].id,
            role=MembershipRole.OWNER,
        ),
        MerchantMembership(
            merchant_id=merchant_a.id,
            user_id=users[1].id,
            role=MembershipRole.ADMIN,
        ),
        MerchantMembership(
            merchant_id=merchant_b.id,
            user_id=users[2].id,
            role=MembershipRole.OPERATOR,
        ),
        MerchantMembership(
            merchant_id=merchant_b.id,
            user_id=users[3].id,
            role=MembershipRole.VIEWER,
        ),
    ]
    for membership in memberships:
        merchants.add_membership(membership)

    customers_repo = CustomerRepository(session)
    customers: list[Customer] = []
    for index in range(1, 11):
        merchant_id = merchant_a.id if index <= 6 else merchant_b.id
        customer = Customer(
            id=stable_id(f"customer:{index}"),
            merchant_id=merchant_id,
            external_id=f"cust_{index:03d}",
            email=f"customer{index}@example.test",
            full_name=f"Customer {index}",
            lifetime_value=Decimal(f"{index * 1250}.50"),
        )
        customers_repo.add(customer)
        customers.append(customer)

    payments_repo = PaymentRepository(session)
    payments: list[Payment] = []
    for index in range(1, 11):
        customer = customers[index - 1]
        payment = Payment(
            id=stable_id(f"payment:{index}"),
            merchant_id=customer.merchant_id,
            customer_id=customer.id,
            provider="simulator",
            provider_payment_id=f"pay_seed_{index:03d}",
            amount=Decimal(f"{index * 499}.99"),
            provider_amount_minor=int(Decimal(f"{index * 499}.99") * 100),
            status=PaymentStatus.FAILED if index % 2 == 0 else PaymentStatus.CAPTURED,
            payment_method="card",
            failure_reason="insufficient_funds" if index % 2 == 0 else None,
            failed_at=now if index % 2 == 0 else None,
            captured_at=now if index % 2 == 1 else None,
        )
        payments_repo.add(payment)
        payments.append(payment)
        session.add(
            PaymentAttempt(
                payment_id=payment.id,
                attempt_number=1,
                status=payment.status,
                amount=payment.amount,
                currency=payment.currency,
                failure_reason=payment.failure_reason,
                attempted_at=now,
            )
        )
        if index % 3 == 0:
            session.add(
                PaymentAttempt(
                    payment_id=payment.id,
                    attempt_number=2,
                    status=PaymentStatus.FAILED,
                    amount=payment.amount,
                    currency=payment.currency,
                    failure_reason="bank_timeout",
                    attempted_at=now,
                )
            )

    for index in range(1, 4):
        customer = customers[index - 1]
        cart = Cart(
            id=stable_id(f"cart:{index}"),
            merchant_id=customer.merchant_id,
            customer_id=customer.id,
            status=CartStatus.ABANDONED if index == 2 else CartStatus.ACTIVE,
            subtotal=Decimal("1500.00"),
            discount=Decimal("0.00"),
            total=Decimal("1500.00"),
            abandoned_at=now if index == 2 else None,
        )
        session.add(cart)
        session.add(
            CartItem(
                cart_id=cart.id,
                name=f"Item {index}",
                quantity=1,
                unit_price=Decimal("1500.00"),
                subtotal=Decimal("1500.00"),
            )
        )

    for index in range(1, 4):
        customer = customers[index + 2]
        session.add(
            Subscription(
                id=stable_id(f"subscription:{index}"),
                merchant_id=customer.merchant_id,
                customer_id=customer.id,
                provider="simulator",
                provider_subscription_id=f"sub_seed_{index:03d}",
                status="PENDING" if index == 1 else "ACTIVE",
                amount=Decimal("999.00"),
                billing_interval="monthly",
                failed_attempt_count=1 if index == 1 else 0,
                failure_reason="mandate_failure" if index == 1 else None,
            )
        )

    cases_repo = RecoveryCaseRepository(session)
    case_specs = [
        ("case:1", customers[1], payments[1], None, None, RecoveryCaseType.FAILED_PAYMENT),
        (
            "case:2",
            customers[2],
            None,
            stable_id("cart:2"),
            None,
            RecoveryCaseType.ABANDONED_CHECKOUT,
        ),
        (
            "case:3",
            customers[3],
            None,
            None,
            stable_id("subscription:1"),
            RecoveryCaseType.SUBSCRIPTION_FAILURE,
        ),
        ("case:4", customers[4], payments[4], None, None, RecoveryCaseType.FAILED_PAYMENT),
        ("case:5", customers[5], payments[5], None, None, RecoveryCaseType.FAILED_PAYMENT),
    ]
    recovery_cases: list[RecoveryCase] = []
    for name, customer, payment, cart_id, subscription_id, case_type in case_specs:
        case = RecoveryCase(
            id=stable_id(name),
            merchant_id=customer.merchant_id,
            customer_id=customer.id,
            payment_id=payment.id if payment else None,
            cart_id=cart_id,
            subscription_id=subscription_id,
            case_type=case_type,
            status=RecoveryCaseStatus.DETECTED,
            amount_at_risk=payment.amount if payment else Decimal("1500.00"),
            amount_recovered=Decimal("0.00"),
            opened_at=now,
        )
        cases_repo.add(case)
        recovery_cases.append(case)

    audit_repo = AuditEventRepository(session)
    for index, case in enumerate(recovery_cases, start=1):
        audit_repo.add(
            AuditEvent(
                merchant_id=case.merchant_id,
                case_id=case.id,
                actor_type=ActorType.SYSTEM,
                event_type="recovery.case.detected",
                action="detect",
                previous_state=None,
                new_state=RecoveryCaseStatus.DETECTED,
                summary=f"Recovery case detected for seed dataset ({index})",
                created_at=now,
            )
        )

    for index in range(1, 4):
        session.add(
            WebhookEvent(
                merchant_id=merchant_a.id,
                provider="simulator",
                event_id=f"evt_seed_{index:03d}",
                event_type="payment.failed" if index % 2 else "payment.captured",
                signature_valid=True,
                status=WebhookEventStatus.RECEIVED,
                payload={"seed": True, "index": index},
                received_at=now,
            )
        )

    session.commit()
    session.close()
    print("Phase 2 seed data loaded successfully.")


def main() -> int:
    try:
        seed()
        return 0
    except Exception as exc:
        print(f"Seed failed: {exc}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
