from __future__ import annotations

from collections.abc import Generator
from uuid import UUID

from fastapi import HTTPException, Request
from redis import Redis
from rq import Queue, Retry
from sqlalchemy.orm import Session

from recoverai_api.config import Settings
from recoverai_db.session import SessionLocal
from recoverai_domain.ingestion import EventQueue


class RedisEventQueue:
    def __init__(self, redis_url: str, queue_name: str, max_retries: int) -> None:
        self._redis_url = redis_url
        self._queue_name = queue_name
        self._max_retries = max_retries

    def enqueue_process_provider_event(self, webhook_event_id: UUID) -> None:
        connection = Redis.from_url(self._redis_url, socket_connect_timeout=3)
        try:
            queue = Queue(self._queue_name, connection=connection)
            self._enqueue(
                queue,
                "recoverai_worker.jobs.process_provider_event",
                str(webhook_event_id),
            )
        finally:
            connection.close()

    def enqueue_process_recovery_case(self, case_id: UUID) -> None:
        connection = Redis.from_url(self._redis_url, socket_connect_timeout=3)
        try:
            queue = Queue(self._queue_name, connection=connection)
            self._enqueue(queue, "recoverai_worker.jobs.process_recovery_case", str(case_id))
        finally:
            connection.close()

    def enqueue_verify_recovery_case(
        self,
        case_id: UUID,
        payment_id: UUID | None = None,
        webhook_event_id: UUID | None = None,
    ) -> None:
        connection = Redis.from_url(self._redis_url, socket_connect_timeout=3)
        try:
            queue = Queue(self._queue_name, connection=connection)
            self._enqueue(
                queue,
                "recoverai_worker.jobs.verify_recovery_case",
                str(case_id),
                str(payment_id) if payment_id else None,
                str(webhook_event_id) if webhook_event_id else None,
            )
        finally:
            connection.close()

    def _enqueue(self, queue: Queue, func: str, *args: object) -> None:
        if self._max_retries > 0:
            queue.enqueue(
                func,
                *args,
                retry=Retry(max=self._max_retries, interval=[5, 15, 45]),
                job_timeout=120,
            )
        else:
            queue.enqueue(func, *args, job_timeout=120)


class LoggingEventQueue:
    """Used when Redis is not configured. Events stay RECEIVED until a worker runs."""

    def enqueue_process_provider_event(self, webhook_event_id: UUID) -> None:
        import logging

        logging.getLogger(__name__).warning(
            "event queued locally without Redis; process_provider_event will not run automatically",
            extra={"event_id": str(webhook_event_id)},
        )

    def enqueue_process_recovery_case(self, case_id: UUID) -> None:
        import logging

        logging.getLogger(__name__).warning(
            "recovery case process job not queued; Redis is not configured",
            extra={"case_id": str(case_id)},
        )

    def enqueue_verify_recovery_case(
        self,
        case_id: UUID,
        payment_id: UUID | None = None,
        webhook_event_id: UUID | None = None,
    ) -> None:
        import logging

        del payment_id, webhook_event_id
        logging.getLogger(__name__).warning(
            "recovery verification job not queued; Redis is not configured",
            extra={"case_id": str(case_id)},
        )


def get_request_settings(request: Request) -> Settings:
    return request.app.state.settings  # type: ignore[no-any-return]


def get_db_session(request: Request) -> Generator[Session, None, None]:
    override = getattr(request.app.state, "db_session_factory", None)
    if override is not None:
        yield override()
        return

    settings = get_request_settings(request)
    if not settings.database_url:
        raise HTTPException(status_code=503, detail="DATABASE_URL is not configured")
    session = SessionLocal(settings.database_url)
    try:
        yield session
        session.commit()
    except Exception:
        session.rollback()
        raise
    finally:
        session.close()


def get_event_queue(request: Request) -> EventQueue:
    override = getattr(request.app.state, "event_queue", None)
    if override is not None:
        return override  # type: ignore[no-any-return]
    settings = get_request_settings(request)
    if settings.redis_url:
        return RedisEventQueue(
            settings.redis_url,
            settings.queue_name,
            settings.worker_max_retries,
        )
    return LoggingEventQueue()
