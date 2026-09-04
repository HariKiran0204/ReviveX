from __future__ import annotations

import uuid
from datetime import datetime

from sqlalchemy import select
from sqlalchemy.orm import Session

from recoverai_db.models import AuditEvent


class AuditEventRepository:
    def __init__(self, session: Session) -> None:
        self._session = session

    def get_event(self, merchant_id: uuid.UUID, event_id: uuid.UUID) -> AuditEvent | None:
        stmt = select(AuditEvent).where(
            AuditEvent.merchant_id == merchant_id,
            AuditEvent.id == event_id,
        )
        return self._session.scalar(stmt)

    def list_for_case(self, merchant_id: uuid.UUID, case_id: uuid.UUID) -> list[AuditEvent]:
        stmt = (
            select(AuditEvent)
            .where(
                AuditEvent.merchant_id == merchant_id,
                AuditEvent.case_id == case_id,
            )
            .order_by(AuditEvent.created_at.asc())
        )
        return list(self._session.scalars(stmt).all())

    def list_for_case_since(
        self,
        merchant_id: uuid.UUID,
        case_id: uuid.UUID,
        *,
        since: datetime | None = None,
        limit: int = 200,
    ) -> list[AuditEvent]:
        stmt = select(AuditEvent).where(
            AuditEvent.merchant_id == merchant_id,
            AuditEvent.case_id == case_id,
        )
        if since is not None:
            stmt = stmt.where(AuditEvent.created_at > since)
        stmt = stmt.order_by(AuditEvent.created_at.asc()).limit(limit)
        return list(self._session.scalars(stmt).all())

    def page_events(
        self,
        merchant_id: uuid.UUID,
        *,
        case_id: uuid.UUID | None = None,
        event_type: str | None = None,
        actor_id: str | None = None,
        since: datetime | None = None,
        until: datetime | None = None,
        offset: int = 0,
        limit: int = 50,
    ) -> tuple[list[AuditEvent], int]:
        from sqlalchemy import func

        filters = [AuditEvent.merchant_id == merchant_id]
        if case_id is not None:
            filters.append(AuditEvent.case_id == case_id)
        if event_type is not None:
            filters.append(AuditEvent.event_type == event_type)
        if actor_id is not None:
            filters.append(AuditEvent.actor_id == actor_id)
        if since is not None:
            filters.append(AuditEvent.created_at >= since)
        if until is not None:
            filters.append(AuditEvent.created_at <= until)
        count_stmt = select(func.count()).select_from(AuditEvent).where(*filters)
        stmt = (
            select(AuditEvent)
            .where(*filters)
            .order_by(AuditEvent.created_at.desc())
            .offset(offset)
            .limit(limit)
        )
        total = int(self._session.scalar(count_stmt) or 0)
        return list(self._session.scalars(stmt).all()), total

    def list_by_type(
        self,
        merchant_id: uuid.UUID,
        event_type: str,
    ) -> list[AuditEvent]:
        stmt = (
            select(AuditEvent)
            .where(
                AuditEvent.merchant_id == merchant_id,
                AuditEvent.event_type == event_type,
            )
            .order_by(AuditEvent.created_at.asc())
        )
        return list(self._session.scalars(stmt).all())

    def add(self, event: AuditEvent) -> AuditEvent:
        self._session.add(event)
        return event
