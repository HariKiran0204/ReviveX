from __future__ import annotations

import uuid

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from recoverai_db.models import Payment, PaymentAttempt


class PaymentRepository:
    def __init__(self, session: Session) -> None:
        self._session = session

    def get_payment(self, merchant_id: uuid.UUID, payment_id: uuid.UUID) -> Payment | None:
        stmt = select(Payment).where(
            Payment.merchant_id == merchant_id,
            Payment.id == payment_id,
        )
        return self._session.scalar(stmt)

    def get_by_provider_payment_id(
        self,
        merchant_id: uuid.UUID,
        provider: str,
        provider_payment_id: str,
    ) -> Payment | None:
        stmt = select(Payment).where(
            Payment.merchant_id == merchant_id,
            Payment.provider == provider,
            Payment.provider_payment_id == provider_payment_id,
        )
        return self._session.scalar(stmt)

    def list_for_customer(self, merchant_id: uuid.UUID, customer_id: uuid.UUID) -> list[Payment]:
        stmt = (
            select(Payment)
            .where(
                Payment.merchant_id == merchant_id,
                Payment.customer_id == customer_id,
            )
            .order_by(Payment.created_at.desc())
        )
        return list(self._session.scalars(stmt).all())

    def next_attempt_number(self, payment_id: uuid.UUID) -> int:
        stmt = select(func.max(PaymentAttempt.attempt_number)).where(
            PaymentAttempt.payment_id == payment_id
        )
        current = self._session.scalar(stmt)
        return int(current or 0) + 1

    def add(self, payment: Payment) -> Payment:
        self._session.add(payment)
        return payment
