from __future__ import annotations

import uuid
from datetime import datetime
from decimal import Decimal

from sqlalchemy import CheckConstraint, DateTime, ForeignKey, Index, Integer, String, text
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column

from recoverai_db.base import Base, MerchantScopedMixin, TimestampMixin, UUIDPrimaryKeyMixin
from recoverai_db.enums import DEFAULT_CURRENCY, RecoveryCaseStatus
from recoverai_db.types import MONEY_PRECISION


class RecoveryCase(Base, UUIDPrimaryKeyMixin, MerchantScopedMixin, TimestampMixin):
    __tablename__ = "recovery_cases"

    customer_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("customers.id", ondelete="RESTRICT"),
        nullable=False,
        index=True,
    )
    payment_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("payments.id", ondelete="SET NULL"),
        nullable=True,
    )
    cart_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("carts.id", ondelete="SET NULL"),
        nullable=True,
    )
    subscription_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("subscriptions.id", ondelete="SET NULL"),
        nullable=True,
    )
    case_type: Mapped[str] = mapped_column(String(64), nullable=False, index=True)
    status: Mapped[str] = mapped_column(
        String(32),
        nullable=False,
        default=RecoveryCaseStatus.DETECTED,
        index=True,
    )
    amount_at_risk: Mapped[Decimal] = mapped_column(MONEY_PRECISION, nullable=False)
    amount_recovered: Mapped[Decimal] = mapped_column(
        MONEY_PRECISION,
        nullable=False,
        default=Decimal("0.00"),
    )
    currency: Mapped[str] = mapped_column(String(3), nullable=False, default=DEFAULT_CURRENCY)
    priority: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    source_event_id: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True), nullable=True)
    version: Mapped[int] = mapped_column(Integer, nullable=False, default=1)
    opened_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    closed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    last_mismatch_reason: Mapped[str | None] = mapped_column(String(64), nullable=True)
    verified_payment_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("payments.id", ondelete="SET NULL"),
        nullable=True,
    )
    verified_webhook_event_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True),
        nullable=True,
    )

    __table_args__ = (
        CheckConstraint("amount_at_risk >= 0", name="recovery_cases_amount_at_risk_non_negative"),
        CheckConstraint(
            "amount_recovered >= 0",
            name="recovery_cases_amount_recovered_non_negative",
        ),
        CheckConstraint(
            "amount_recovered <= amount_at_risk",
            name="recovery_cases_recovered_lte_at_risk",
        ),
        CheckConstraint(
            "(payment_id IS NOT NULL)::int + (cart_id IS NOT NULL)::int + "
            "(subscription_id IS NOT NULL)::int >= 1",
            name="recovery_cases_has_subject",
        ),
        Index("ix_recovery_cases_merchant_status", "merchant_id", "status"),
        Index("ix_recovery_cases_merchant_type", "merchant_id", "case_type"),
        Index("ix_recovery_cases_merchant_created_at", "merchant_id", "created_at"),
        Index(
            "uq_recovery_cases_open_payment",
            "merchant_id",
            "payment_id",
            unique=True,
            postgresql_where=text("payment_id IS NOT NULL AND closed_at IS NULL"),
        ),
        Index(
            "uq_recovery_cases_open_cart",
            "merchant_id",
            "cart_id",
            unique=True,
            postgresql_where=text("cart_id IS NOT NULL AND closed_at IS NULL"),
        ),
        Index(
            "uq_recovery_cases_open_subscription",
            "merchant_id",
            "subscription_id",
            unique=True,
            postgresql_where=text("subscription_id IS NOT NULL AND closed_at IS NULL"),
        ),
    )
