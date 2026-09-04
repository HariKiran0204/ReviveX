from datetime import UTC, datetime
from decimal import Decimal

import pytest
from sqlalchemy.exc import IntegrityError

from recoverai_db.enums import MembershipRole, RecoveryCaseStatus, RecoveryCaseType
from recoverai_db.models import (
    AuditEvent,
    Customer,
    Merchant,
    MerchantMembership,
    Payment,
    RecoveryAction,
    RecoveryCase,
    User,
    WebhookEvent,
)
from recoverai_db.repositories import (
    AuditEventRepository,
    CustomerRepository,
    PaymentRepository,
    RecoveryCaseRepository,
    WebhookEventRepository,
)


def test_merchant_membership_unique(db_session) -> None:
    merchant = Merchant(name="Membership Merchant", slug="membership-merchant")
    user = User(email="member@example.test", full_name="Member")
    db_session.add_all([merchant, user])
    db_session.flush()

    db_session.add(
        MerchantMembership(
            merchant_id=merchant.id,
            user_id=user.id,
            role=MembershipRole.ADMIN,
        )
    )
    db_session.flush()
    db_session.add(
        MerchantMembership(
            merchant_id=merchant.id,
            user_id=user.id,
            role=MembershipRole.VIEWER,
        )
    )
    with pytest.raises(IntegrityError):
        db_session.flush()


def test_merchant_isolation_for_customers_payments_cases_and_audit(db_session) -> None:
    merchant_a = Merchant(name="Merchant A", slug="merchant-a")
    merchant_b = Merchant(name="Merchant B", slug="merchant-b")
    db_session.add_all([merchant_a, merchant_b])
    db_session.flush()

    customer_a = Customer(merchant_id=merchant_a.id, email="a@example.test")
    customer_b = Customer(merchant_id=merchant_b.id, email="b@example.test")
    db_session.add_all([customer_a, customer_b])
    db_session.flush()

    payment_b = Payment(
        merchant_id=merchant_b.id,
        customer_id=customer_b.id,
        amount=Decimal("250.00"),
    )
    db_session.add(payment_b)
    db_session.flush()

    case_b = RecoveryCase(
        merchant_id=merchant_b.id,
        customer_id=customer_b.id,
        payment_id=payment_b.id,
        case_type=RecoveryCaseType.FAILED_PAYMENT,
        status=RecoveryCaseStatus.DETECTED,
        amount_at_risk=Decimal("250.00"),
        opened_at=datetime.now(UTC),
    )
    audit_b = AuditEvent(
        merchant_id=merchant_b.id,
        case_id=case_b.id,
        event_type="recovery.case.detected",
        summary="Merchant B case",
        created_at=datetime.now(UTC),
    )
    db_session.add_all([case_b, audit_b])
    db_session.flush()

    customers = CustomerRepository(db_session)
    payments = PaymentRepository(db_session)
    cases = RecoveryCaseRepository(db_session)
    audit = AuditEventRepository(db_session)

    assert customers.get_customer(merchant_a.id, customer_b.id) is None
    assert payments.get_payment(merchant_a.id, payment_b.id) is None
    assert cases.get_case(merchant_a.id, case_b.id) is None
    assert audit.get_event(merchant_a.id, audit_b.id) is None

    assert customers.get_customer(merchant_b.id, customer_b.id) is not None
    assert payments.get_payment(merchant_b.id, payment_b.id) is not None
    assert cases.get_case(merchant_b.id, case_b.id) is not None
    assert audit.get_event(merchant_b.id, audit_b.id) is not None


def test_recovery_action_idempotency_unique(db_session) -> None:
    merchant = Merchant(name="Action Merchant", slug="action-merchant")
    db_session.add(merchant)
    db_session.flush()
    customer = Customer(merchant_id=merchant.id, email="action@example.test")
    db_session.add(customer)
    db_session.flush()
    payment = Payment(
        merchant_id=merchant.id,
        customer_id=customer.id,
        amount=Decimal("100.00"),
    )
    db_session.add(payment)
    db_session.flush()
    case = RecoveryCase(
        merchant_id=merchant.id,
        customer_id=customer.id,
        payment_id=payment.id,
        case_type=RecoveryCaseType.FAILED_PAYMENT,
        status=RecoveryCaseStatus.DETECTED,
        amount_at_risk=Decimal("100.00"),
        opened_at=datetime.now(UTC),
    )
    db_session.add(case)
    db_session.flush()

    db_session.add(
        RecoveryAction(
            merchant_id=merchant.id,
            recovery_case_id=case.id,
            action_type="RETRY_NOW",
            idempotency_key="retry-1",
        )
    )
    db_session.flush()
    db_session.add(
        RecoveryAction(
            merchant_id=merchant.id,
            recovery_case_id=case.id,
            action_type="RETRY_NOW",
            idempotency_key="retry-1",
        )
    )
    with pytest.raises(IntegrityError):
        db_session.flush()


def test_webhook_event_provider_id_unique(db_session) -> None:
    merchant = Merchant(name="Webhook Merchant", slug="webhook-merchant")
    db_session.add(merchant)
    db_session.flush()
    repo = WebhookEventRepository(db_session)
    now = datetime.now(UTC)
    repo.add(
        WebhookEvent(
            merchant_id=merchant.id,
            provider="simulator",
            event_id="evt_123",
            event_type="payment.failed",
            payload={"id": "evt_123"},
            received_at=now,
        )
    )
    db_session.flush()
    repo.add(
        WebhookEvent(
            merchant_id=merchant.id,
            provider="simulator",
            event_id="evt_123",
            event_type="payment.failed",
            payload={"duplicate": True},
            received_at=now,
        )
    )
    with pytest.raises(IntegrityError):
        db_session.flush()


def test_only_one_open_recovery_case_per_payment(db_session) -> None:
    merchant = Merchant(name="Open Case Merchant", slug="open-case-merchant")
    db_session.add(merchant)
    db_session.flush()
    customer = Customer(merchant_id=merchant.id, email="open@example.test")
    db_session.add(customer)
    db_session.flush()
    payment = Payment(
        merchant_id=merchant.id,
        customer_id=customer.id,
        amount=Decimal("500.00"),
    )
    db_session.add(payment)
    db_session.flush()

    db_session.add(
        RecoveryCase(
            merchant_id=merchant.id,
            customer_id=customer.id,
            payment_id=payment.id,
            case_type=RecoveryCaseType.FAILED_PAYMENT,
            status=RecoveryCaseStatus.DETECTED,
            amount_at_risk=Decimal("500.00"),
            opened_at=datetime.now(UTC),
        )
    )
    db_session.flush()
    db_session.add(
        RecoveryCase(
            merchant_id=merchant.id,
            customer_id=customer.id,
            payment_id=payment.id,
            case_type=RecoveryCaseType.FAILED_PAYMENT,
            status=RecoveryCaseStatus.TRIAGED,
            amount_at_risk=Decimal("500.00"),
            opened_at=datetime.now(UTC),
        )
    )
    with pytest.raises(IntegrityError):
        db_session.flush()
