from __future__ import annotations

import uuid
from datetime import datetime
from decimal import Decimal

from sqlalchemy import (
    BigInteger,
    CheckConstraint,
    DateTime,
    ForeignKey,
    String,
    Text,
    UniqueConstraint,
)
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column, relationship

from recoverai_db.base import Base, MerchantScopedMixin, TimestampMixin, UUIDPrimaryKeyMixin
from recoverai_db.enums import DEFAULT_CURRENCY, PaymentStatus
from recoverai_db.types import MONEY_PRECISION


class Payment(Base, UUIDPrimaryKeyMixin, MerchantScopedMixin, TimestampMixin):
    __tablename__ = "payments"

    customer_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("customers.id", ondelete="RESTRICT"),
        nullable=False,
        index=True,
    )
    provider: Mapped[str] = mapped_column(String(64), nullable=False, default="simulator")
    provider_payment_id: Mapped[str | None] = mapped_column(String(255), nullable=True)
    provider_order_id: Mapped[str | None] = mapped_column(String(255), nullable=True)
    provider_payment_link_id: Mapped[str | None] = mapped_column(String(255), nullable=True)
    amount: Mapped[Decimal] = mapped_column(MONEY_PRECISION, nullable=False)
    provider_amount_minor: Mapped[int | None] = mapped_column(BigInteger, nullable=True)
    currency: Mapped[str] = mapped_column(String(3), nullable=False, default=DEFAULT_CURRENCY)
    status: Mapped[str] = mapped_column(
        String(32),
        nullable=False,
        default=PaymentStatus.CREATED,
        index=True,
    )
    payment_method: Mapped[str | None] = mapped_column(String(64), nullable=True)
    failure_reason: Mapped[str | None] = mapped_column(Text, nullable=True)
    failure_code: Mapped[str | None] = mapped_column(String(64), nullable=True)
    captured_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    failed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)

    attempts: Mapped[list[PaymentAttempt]] = relationship(back_populates="payment")

    __table_args__ = (
        CheckConstraint("amount >= 0", name="payments_amount_non_negative"),
        UniqueConstraint(
            "merchant_id",
            "provider",
            "provider_payment_id",
            name="uq_payments_merchant_provider_payment_id",
        ),
    )


class PaymentAttempt(Base, UUIDPrimaryKeyMixin, TimestampMixin):
    __tablename__ = "payment_attempts"

    payment_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("payments.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    attempt_number: Mapped[int] = mapped_column(nullable=False)
    status: Mapped[str] = mapped_column(String(32), nullable=False)
    amount: Mapped[Decimal] = mapped_column(MONEY_PRECISION, nullable=False)
    currency: Mapped[str] = mapped_column(String(3), nullable=False, default=DEFAULT_CURRENCY)
    failure_reason: Mapped[str | None] = mapped_column(Text, nullable=True)
    failure_code: Mapped[str | None] = mapped_column(String(64), nullable=True)
    attempted_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)

    payment: Mapped[Payment] = relationship(back_populates="attempts")

    __table_args__ = (
        CheckConstraint("amount >= 0", name="payment_attempts_amount_non_negative"),
        UniqueConstraint(
            "payment_id", "attempt_number", name="uq_payment_attempts_payment_attempt"
        ),
    )
