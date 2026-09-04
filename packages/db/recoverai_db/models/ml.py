from __future__ import annotations

import uuid
from datetime import datetime
from decimal import Decimal

from sqlalchemy import (
    Boolean,
    CheckConstraint,
    DateTime,
    ForeignKey,
    Index,
    Integer,
    Numeric,
    String,
    Text,
    text,
)
from sqlalchemy.dialects.postgresql import JSONB, UUID
from sqlalchemy.orm import Mapped, mapped_column

from recoverai_db.base import Base, MerchantScopedMixin, TimestampMixin, UUIDPrimaryKeyMixin
from recoverai_db.types import JsonDict

PROBABILITY_PRECISION = Numeric(8, 6)


class ModelVersion(Base, UUIDPrimaryKeyMixin, TimestampMixin):
    __tablename__ = "model_versions"

    version: Mapped[str] = mapped_column(String(64), nullable=False, unique=True)
    algorithm: Mapped[str] = mapped_column(String(64), nullable=False)
    dataset_version: Mapped[str] = mapped_column(String(128), nullable=False)
    feature_version: Mapped[str] = mapped_column(String(64), nullable=False)
    seed: Mapped[int] = mapped_column(Integer, nullable=False)
    trained_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    artifact_path: Mapped[str] = mapped_column(Text, nullable=False)
    quality_passed: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    is_production: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    metrics: Mapped[JsonDict | None] = mapped_column(JSONB, nullable=True)
    configuration: Mapped[JsonDict | None] = mapped_column(JSONB, nullable=True)
    notes: Mapped[str | None] = mapped_column(Text, nullable=True)

    __table_args__ = (
        Index(
            "uq_model_versions_production",
            "is_production",
            unique=True,
            postgresql_where=text("is_production IS TRUE"),
        ),
    )


class ModelPrediction(Base, UUIDPrimaryKeyMixin, MerchantScopedMixin, TimestampMixin):
    __tablename__ = "model_predictions"

    recovery_case_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("recovery_cases.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    action: Mapped[str] = mapped_column(String(64), nullable=False)
    probability: Mapped[Decimal] = mapped_column(PROBABILITY_PRECISION, nullable=False)
    model_version: Mapped[str] = mapped_column(String(64), nullable=False)
    feature_version: Mapped[str] = mapped_column(String(64), nullable=False)
    fingerprint: Mapped[str] = mapped_column(String(64), nullable=False)
    source: Mapped[str] = mapped_column(String(32), nullable=False, default="ml")
    diagnostics: Mapped[JsonDict | None] = mapped_column(JSONB, nullable=True)

    __table_args__ = (
        CheckConstraint(
            "probability >= 0 AND probability <= 1",
            name="model_predictions_probability_unit_interval",
        ),
        Index("uq_model_predictions_fingerprint", "fingerprint", unique=True),
        Index(
            "ix_model_predictions_case_action_version",
            "merchant_id",
            "recovery_case_id",
            "action",
            "model_version",
        ),
    )
