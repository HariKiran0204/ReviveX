from __future__ import annotations

import uuid
from datetime import datetime
from decimal import Decimal

from sqlalchemy import CheckConstraint, DateTime, ForeignKey, Integer, String
from sqlalchemy.dialects.postgresql import JSONB, UUID
from sqlalchemy.orm import Mapped, mapped_column, relationship

from recoverai_db.base import Base, MerchantScopedMixin, TimestampMixin, UUIDPrimaryKeyMixin
from recoverai_db.enums import DEFAULT_CURRENCY, CartStatus
from recoverai_db.types import MONEY_PRECISION, JsonDict


class Cart(Base, UUIDPrimaryKeyMixin, MerchantScopedMixin, TimestampMixin):
    __tablename__ = "carts"

    customer_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("customers.id", ondelete="RESTRICT"),
        nullable=False,
        index=True,
    )
    status: Mapped[str] = mapped_column(String(32), nullable=False, default=CartStatus.ACTIVE)
    subtotal: Mapped[Decimal] = mapped_column(
        MONEY_PRECISION, nullable=False, default=Decimal("0.00")
    )
    discount: Mapped[Decimal] = mapped_column(
        MONEY_PRECISION, nullable=False, default=Decimal("0.00")
    )
    total: Mapped[Decimal] = mapped_column(MONEY_PRECISION, nullable=False, default=Decimal("0.00"))
    currency: Mapped[str] = mapped_column(String(3), nullable=False, default=DEFAULT_CURRENCY)
    abandoned_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    converted_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    metadata_json: Mapped[JsonDict | None] = mapped_column("metadata", JSONB, nullable=True)

    items: Mapped[list[CartItem]] = relationship(back_populates="cart")

    __table_args__ = (
        CheckConstraint("subtotal >= 0", name="carts_subtotal_non_negative"),
        CheckConstraint("discount >= 0", name="carts_discount_non_negative"),
        CheckConstraint("total >= 0", name="carts_total_non_negative"),
    )


class CartItem(Base, UUIDPrimaryKeyMixin, TimestampMixin):
    __tablename__ = "cart_items"

    cart_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("carts.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    sku: Mapped[str | None] = mapped_column(String(128), nullable=True)
    name: Mapped[str] = mapped_column(String(255), nullable=False)
    quantity: Mapped[int] = mapped_column(Integer, nullable=False, default=1)
    unit_price: Mapped[Decimal] = mapped_column(MONEY_PRECISION, nullable=False)
    subtotal: Mapped[Decimal] = mapped_column(MONEY_PRECISION, nullable=False)
    currency: Mapped[str] = mapped_column(String(3), nullable=False, default=DEFAULT_CURRENCY)

    cart: Mapped[Cart] = relationship(back_populates="items")

    __table_args__ = (
        CheckConstraint("quantity > 0", name="cart_items_quantity_positive"),
        CheckConstraint("unit_price >= 0", name="cart_items_unit_price_non_negative"),
        CheckConstraint("subtotal >= 0", name="cart_items_subtotal_non_negative"),
    )
