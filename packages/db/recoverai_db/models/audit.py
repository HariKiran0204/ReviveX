from __future__ import annotations

import uuid
from datetime import datetime

from sqlalchemy import DateTime, ForeignKey, Integer, String, Text
from sqlalchemy.dialects.postgresql import JSONB, UUID
from sqlalchemy.orm import Mapped, mapped_column

from recoverai_db.base import Base, MerchantScopedMixin, TimestampMixin, UUIDPrimaryKeyMixin
from recoverai_db.enums import (
    ActorType,
    AgentRunStatus,
    NotificationChannel,
    NotificationStatus,
)
from recoverai_db.types import JsonDict


class AuditEvent(Base, UUIDPrimaryKeyMixin, MerchantScopedMixin):
    __tablename__ = "audit_events"

    case_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("recovery_cases.id", ondelete="SET NULL"),
        nullable=True,
        index=True,
    )
    actor_type: Mapped[str] = mapped_column(String(32), nullable=False, default=ActorType.SYSTEM)
    actor_id: Mapped[str | None] = mapped_column(String(255), nullable=True)
    event_type: Mapped[str] = mapped_column(String(128), nullable=False)
    action: Mapped[str | None] = mapped_column(String(128), nullable=True)
    previous_state: Mapped[str | None] = mapped_column(String(64), nullable=True)
    new_state: Mapped[str | None] = mapped_column(String(64), nullable=True)
    summary: Mapped[str] = mapped_column(Text, nullable=False)
    metadata_json: Mapped[JsonDict | None] = mapped_column("metadata", JSONB, nullable=True)
    correlation_id: Mapped[str | None] = mapped_column(String(128), nullable=True, index=True)
    idempotency_key: Mapped[str | None] = mapped_column(String(255), nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, index=True
    )


class AgentRun(Base, UUIDPrimaryKeyMixin, MerchantScopedMixin, TimestampMixin):
    __tablename__ = "agent_runs"

    recovery_case_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("recovery_cases.id", ondelete="SET NULL"),
        nullable=True,
        index=True,
    )
    agent_name: Mapped[str] = mapped_column(String(128), nullable=False)
    agent_version: Mapped[str] = mapped_column(String(64), nullable=False)
    status: Mapped[str] = mapped_column(String(32), nullable=False, default=AgentRunStatus.RUNNING)
    input_summary: Mapped[JsonDict | None] = mapped_column(JSONB, nullable=True)
    output_summary: Mapped[JsonDict | None] = mapped_column(JSONB, nullable=True)
    decision_factors: Mapped[JsonDict | None] = mapped_column(JSONB, nullable=True)
    error_message: Mapped[str | None] = mapped_column(Text, nullable=True)
    started_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    completed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    latency_ms: Mapped[int | None] = mapped_column(Integer, nullable=True)


class ToolCall(Base, UUIDPrimaryKeyMixin, MerchantScopedMixin, TimestampMixin):
    __tablename__ = "tool_calls"

    recovery_case_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("recovery_cases.id", ondelete="SET NULL"),
        nullable=True,
        index=True,
    )
    agent_run_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("agent_runs.id", ondelete="SET NULL"),
        nullable=True,
    )
    tool_name: Mapped[str] = mapped_column(String(128), nullable=False)
    tool_version: Mapped[str] = mapped_column(String(64), nullable=False, default="v1")
    status: Mapped[str] = mapped_column(String(32), nullable=False)
    request_payload: Mapped[JsonDict | None] = mapped_column(JSONB, nullable=True)
    response_payload: Mapped[JsonDict | None] = mapped_column(JSONB, nullable=True)
    idempotency_key: Mapped[str | None] = mapped_column(String(255), nullable=True)
    correlation_id: Mapped[str | None] = mapped_column(String(128), nullable=True)
    latency_ms: Mapped[int | None] = mapped_column(Integer, nullable=True)
    error_code: Mapped[str | None] = mapped_column(String(64), nullable=True)
    error_message: Mapped[str | None] = mapped_column(Text, nullable=True)


class Notification(Base, UUIDPrimaryKeyMixin, MerchantScopedMixin, TimestampMixin):
    __tablename__ = "notifications"

    customer_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("customers.id", ondelete="RESTRICT"),
        nullable=False,
        index=True,
    )
    recovery_case_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("recovery_cases.id", ondelete="SET NULL"),
        nullable=True,
        index=True,
    )
    channel: Mapped[str] = mapped_column(
        String(32), nullable=False, default=NotificationChannel.EMAIL
    )
    status: Mapped[str] = mapped_column(
        String(32),
        nullable=False,
        default=NotificationStatus.PENDING,
    )
    provider: Mapped[str | None] = mapped_column(String(64), nullable=True)
    provider_reference: Mapped[str | None] = mapped_column(String(255), nullable=True)
    subject: Mapped[str | None] = mapped_column(String(255), nullable=True)
    body_preview: Mapped[str | None] = mapped_column(Text, nullable=True)
    scheduled_for: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    sent_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    error_code: Mapped[str | None] = mapped_column(String(64), nullable=True)
    error_message: Mapped[str | None] = mapped_column(Text, nullable=True)
    metadata_json: Mapped[JsonDict | None] = mapped_column("metadata", JSONB, nullable=True)
