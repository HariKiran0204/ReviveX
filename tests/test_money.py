from datetime import UTC, datetime
from decimal import Decimal

import pytest
from sqlalchemy.exc import IntegrityError

from recoverai_db.models import Customer, Merchant, Payment, PaymentAttempt
from recoverai_db.types import validate_non_negative_money


def test_decimal_money_precision(db_session) -> None:
    merchant = Merchant(name="Money Merchant", slug="money-merchant")
    db_session.add(merchant)
    db_session.flush()

    customer = Customer(
        merchant_id=merchant.id,
        email="money@example.test",
        lifetime_value=Decimal("1234.56"),
    )
    db_session.add(customer)
    db_session.flush()

    payment = Payment(
        merchant_id=merchant.id,
        customer_id=customer.id,
        amount=Decimal("999.99"),
        provider_amount_minor=99999,
    )
    db_session.add(payment)
    db_session.flush()

    loaded = db_session.get(Payment, payment.id)
    assert loaded is not None
    assert loaded.amount == Decimal("999.99")
    assert loaded.amount - Decimal("0.01") == Decimal("999.98")


def test_validate_non_negative_money_rejects_negative() -> None:
    with pytest.raises(ValueError, match="must be non-negative"):
        validate_non_negative_money(Decimal("-1.00"), "amount")


def test_payment_amount_cannot_be_negative(db_session) -> None:
    merchant = Merchant(name="Negative Merchant", slug="negative-merchant")
    db_session.add(merchant)
    db_session.flush()
    customer = Customer(merchant_id=merchant.id, email="neg@example.test")
    db_session.add(customer)
    db_session.flush()

    payment = Payment(
        merchant_id=merchant.id,
        customer_id=customer.id,
        amount=Decimal("-10.00"),
    )
    db_session.add(payment)
    with pytest.raises(IntegrityError):
        db_session.flush()


def test_payment_attempt_number_unique(db_session) -> None:
    merchant = Merchant(name="Attempt Merchant", slug="attempt-merchant")
    db_session.add(merchant)
    db_session.flush()
    customer = Customer(merchant_id=merchant.id, email="attempt@example.test")
    db_session.add(customer)
    db_session.flush()
    payment = Payment(
        merchant_id=merchant.id,
        customer_id=customer.id,
        amount=Decimal("100.00"),
    )
    db_session.add(payment)
    db_session.flush()

    db_session.add(
        PaymentAttempt(
            payment_id=payment.id,
            attempt_number=1,
            status="FAILED",
            amount=Decimal("100.00"),
            attempted_at=datetime.now(UTC),
        )
    )
    db_session.flush()
    db_session.add(
        PaymentAttempt(
            payment_id=payment.id,
            attempt_number=1,
            status="FAILED",
            amount=Decimal("100.00"),
            attempted_at=datetime.now(UTC),
        )
    )
    with pytest.raises(IntegrityError):
        db_session.flush()
