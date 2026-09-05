from __future__ import annotations

import uuid

from sqlalchemy import select
from sqlalchemy.orm import Session

from recoverai_db.models import WebhookEvent


class WebhookEventRepository:
    def __init__(self, session: Session) -> None:
        self._session = session

    def get(self, event_pk: uuid.UUID) -> WebhookEvent | None:
        return self._session.get(WebhookEvent, event_pk)

    def get_by_provider_event(
        self,
        merchant_id: uuid.UUID,
        provider: str,
        event_id: str,
    ) -> WebhookEvent | None:
        stmt = select(WebhookEvent).where(
            WebhookEvent.merchant_id == merchant_id,
            WebhookEvent.provider == provider,
            WebhookEvent.event_id == event_id,
        )
        return self._session.scalar(stmt)

    def get_by_provider_event_id(self, provider: str, event_id: str) -> WebhookEvent | None:
        stmt = select(WebhookEvent).where(
            WebhookEvent.provider == provider,
            WebhookEvent.event_id == event_id,
        )
        return self._session.scalar(stmt)

    def list_recent(
        self,
        *,
        merchant_id: uuid.UUID | None = None,
        limit: int = 50,
    ) -> list[WebhookEvent]:
        stmt = select(WebhookEvent).order_by(WebhookEvent.received_at.desc()).limit(limit)
        if merchant_id is not None:
            stmt = select(WebhookEvent).where(WebhookEvent.merchant_id == merchant_id)
            stmt = stmt.order_by(WebhookEvent.received_at.desc()).limit(limit)
        return list(self._session.scalars(stmt).all())

    def add(self, event: WebhookEvent) -> WebhookEvent:
        self._session.add(event)
        return event
