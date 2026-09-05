from __future__ import annotations

import uuid
from datetime import datetime

from sqlalchemy import Boolean, DateTime, ForeignKey, Index, String, Text
from sqlalchemy.dialects.postgresql import JSONB, UUID
from sqlalchemy.orm import Mapped, mapped_column

from recoverai_db.base import Base, MerchantScopedMixin, TimestampMixin, UUIDPrimaryKeyMixin
from recoverai_db.enums import ApprovalStatus
from recoverai_db.types import JsonDict


class PolicyEvaluation(Base, UUIDPrimaryKeyMixin, MerchantScopedMixin, TimestampMixin):
    __tablename__ = "policy_evaluations"

    recovery_case_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("recovery_cases.id", ondelete="SET NULL"),
        nullable=True,
        index=True,
    )
    recovery_action_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("recovery_actions.id", ondelete="SET NULL"),
        nullable=True,
    )
    policy_version: Mapped[str] = mapped_column(String(64), nullable=False)
    action: Mapped[str] = mapped_column(String(64), nullable=False)
    risk_level: Mapped[str] = mapped_column(String(16), nullable=False)
    allowed: Mapped[bool] = mapped_column(Boolean, nullable=False)
    requires_approval: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    reason: Mapped[str | None] = mapped_column(Text, nullable=True)
    policy_ids: Mapped[list[str] | None] = mapped_column(JSONB, nullable=True)
    evaluated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    metadata_json: Mapped[JsonDict | None] = mapped_column("metadata", JSONB, nullable=True)


class Approval(Base, UUIDPrimaryKeyMixin, MerchantScopedMixin, TimestampMixin):
    __tablename__ = "approvals"

    recovery_case_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("recovery_cases.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    recovery_action_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("recovery_actions.id", ondelete="SET NULL"),
        nullable=True,
    )
    policy_evaluation_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("policy_evaluations.id", ondelete="SET NULL"),
        nullable=True,
    )
    status: Mapped[str] = mapped_column(
        String(32),
        nullable=False,
        default=ApprovalStatus.PENDING,
        index=True,
    )
    requested_by: Mapped[str | None] = mapped_column(String(255), nullable=True)
    decided_by: Mapped[str | None] = mapped_column(String(255), nullable=True)
    decision_reason: Mapped[str | None] = mapped_column(Text, nullable=True)
    decided_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    expires_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)

    __table_args__ = (Index("ix_approvals_merchant_status", "merchant_id", "status"),)
