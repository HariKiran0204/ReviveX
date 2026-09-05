from __future__ import annotations

import uuid
from datetime import datetime
from decimal import Decimal

from sqlalchemy import CheckConstraint, DateTime, ForeignKey, Integer, String, Text
from sqlalchemy.dialects.postgresql import JSONB, UUID
from sqlalchemy.orm import Mapped, mapped_column

from recoverai_db.base import Base, MerchantScopedMixin, TimestampMixin, UUIDPrimaryKeyMixin
from recoverai_db.enums import DEFAULT_CURRENCY, SubscriptionStatus
from recoverai_db.types import MONEY_PRECISION, JsonDict


class Subscription(Base, UUIDPrimaryKeyMixin, MerchantScopedMixin, TimestampMixin):
    __tablename__ = "subscriptions"

    customer_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("customers.id", ondelete="RESTRICT"),
        nullable=False,
        index=True,
    )
    provider: Mapped[str] = mapped_column(String(64), nullable=False, default="simulator")
    provider_subscription_id: Mapped[str | None] = mapped_column(String(255), nullable=True)
    plan_id: Mapped[str | None] = mapped_column(String(128), nullable=True)
    status: Mapped[str] = mapped_column(
        String(32),
        nullable=False,
        default=SubscriptionStatus.CREATED,
        index=True,
    )
    amount: Mapped[Decimal] = mapped_column(MONEY_PRECISION, nullable=False)
    currency: Mapped[str] = mapped_column(String(3), nullable=False, default=DEFAULT_CURRENCY)
    billing_interval: Mapped[str | None] = mapped_column(String(32), nullable=True)
    current_period_start: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    current_period_end: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    failed_attempt_count: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    cancelled_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    metadata_json: Mapped[JsonDict | None] = mapped_column("metadata", JSONB, nullable=True)
    failure_reason: Mapped[str | None] = mapped_column(Text, nullable=True)

    __table_args__ = (CheckConstraint("amount >= 0", name="subscriptions_amount_non_negative"),)
