from __future__ import annotations

from decimal import Decimal

from sqlalchemy import CheckConstraint, String
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column

from recoverai_db.base import Base, MerchantScopedMixin, TimestampMixin, UUIDPrimaryKeyMixin
from recoverai_db.enums import DEFAULT_CURRENCY
from recoverai_db.types import MONEY_PRECISION, JsonDict


class Customer(Base, UUIDPrimaryKeyMixin, MerchantScopedMixin, TimestampMixin):
    __tablename__ = "customers"

    external_id: Mapped[str | None] = mapped_column(String(255), nullable=True)
    email: Mapped[str | None] = mapped_column(String(320), nullable=True, index=True)
    phone: Mapped[str | None] = mapped_column(String(32), nullable=True)
    full_name: Mapped[str | None] = mapped_column(String(255), nullable=True)
    lifetime_value: Mapped[Decimal] = mapped_column(
        MONEY_PRECISION,
        nullable=False,
        default=Decimal("0.00"),
    )
    currency: Mapped[str] = mapped_column(String(3), nullable=False, default=DEFAULT_CURRENCY)
    metadata_json: Mapped[JsonDict | None] = mapped_column("metadata", JSONB, nullable=True)

    __table_args__ = (
        CheckConstraint("lifetime_value >= 0", name="customers_lifetime_value_non_negative"),
    )
