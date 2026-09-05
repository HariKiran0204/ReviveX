from __future__ import annotations

import logging
from datetime import UTC, datetime
from typing import Any
from uuid import UUID

from redis import Redis
from rq import Queue, Retry
from sqlalchemy.exc import OperationalError

from recoverai_db.session import SessionLocal
from recoverai_domain.errors import DomainError
from recoverai_domain.followups import apply_followups
from recoverai_domain.processing import mark_dead_letter, process_webhook_event
from recoverai_domain.processor import process_recovery_case as run_process_recovery_case
from recoverai_domain.processor import verify_recovery_case as run_verify_recovery_case
from recoverai_worker.config import get_worker_settings

logger = logging.getLogger(__name__)


def health_heartbeat(worker_id: str | None = None) -> dict[str, str]:
    timestamp = datetime.now(UTC).isoformat()
    identity = worker_id or "rq-job"
    logger.info(
        "RecoverAI worker heartbeat worker=%s timestamp=%s source=job",
        identity,
        timestamp,
    )
    return {"worker": identity, "timestamp": timestamp, "status": "ok"}


def process_provider_event(webhook_event_id: str) -> dict[str, Any]:
    settings = get_worker_settings()
    if not settings.database_url:
        raise RuntimeError("DATABASE_URL is required to process provider events")
    session = SessionLocal(settings.database_url)
    try:
        result = process_webhook_event(session, UUID(webhook_event_id))
        session.commit()
    except Exception:
        session.rollback()
        if not will_retry():
            dead = SessionLocal(settings.database_url)
            try:
                mark_dead_letter(dead, UUID(webhook_event_id), "bounded retries exhausted")
                dead.commit()
            finally:
                dead.close()
        raise
    finally:
        session.close()

    followups = result.get("followups")
    if not _enqueue_followups(followups):
        _apply_followups_now(followups)
    return result


def process_recovery_case_job(case_id: str) -> dict[str, str]:
    settings = get_worker_settings()
    if not settings.database_url:
        raise RuntimeError("DATABASE_URL is required to process recovery cases")
    session = SessionLocal(settings.database_url)
    try:
        result = run_process_recovery_case(session, UUID(case_id))
        session.commit()
        return result
    except DomainError as exc:
        session.rollback()
        if exc.retryable:
            raise
        logger.info("process_recovery_case permanent failure", extra={"code": exc.code})
        return {"status": "error", "code": exc.code, "case_id": case_id}
    except OperationalError:
        session.rollback()
        raise
    finally:
        session.close()


def verify_recovery_case_job(
    case_id: str,
    payment_id: str | None = None,
    webhook_event_id: str | None = None,
) -> dict[str, Any]:
    settings = get_worker_settings()
    if not settings.database_url:
        raise RuntimeError("DATABASE_URL is required to verify recovery cases")
    session = SessionLocal(settings.database_url)
    try:
        result = run_verify_recovery_case(
            session,
            UUID(case_id),
            payment_id=UUID(payment_id) if payment_id else None,
            webhook_event_id=UUID(webhook_event_id) if webhook_event_id else None,
        )
        session.commit()
        return result
    except DomainError as exc:
        session.rollback()
        if exc.retryable:
            raise
        logger.info("verify_recovery_case permanent failure", extra={"code": exc.code})
        return {"status": "error", "code": exc.code, "case_id": case_id, "matched": False}
    except OperationalError:
        session.rollback()
        raise
    finally:
        session.close()


def process_recovery_case(case_id: str) -> dict[str, str]:
    return process_recovery_case_job(case_id)


def verify_recovery_case(
    case_id: str,
    payment_id: str | None = None,
    webhook_event_id: str | None = None,
) -> dict[str, Any]:
    return verify_recovery_case_job(case_id, payment_id, webhook_event_id)


def _enqueue_followups(followups: object) -> bool:
    if not isinstance(followups, list) or not followups:
        return True
    settings = get_worker_settings()
    try:
        connection = Redis.from_url(settings.redis_url, socket_connect_timeout=3)
        try:
            queue = Queue(settings.queue_name, connection=connection)
            retry = (
                Retry(max=settings.worker_max_retries, interval=[5, 15, 45])
                if settings.worker_max_retries > 0
                else None
            )
            for item in followups:
                if not isinstance(item, dict):
                    continue
                name = item.get("name")
                case_id = item.get("case_id")
                if not isinstance(case_id, str):
                    continue
                kwargs: dict[str, Any] = {}
                if retry is not None:
                    kwargs["retry"] = retry
                if name == "process_recovery_case":
                    queue.enqueue(
                        "recoverai_worker.jobs.process_recovery_case",
                        case_id,
                        job_timeout=120,
                        **kwargs,
                    )
                elif name == "verify_recovery_case":
                    queue.enqueue(
                        "recoverai_worker.jobs.verify_recovery_case",
                        case_id,
                        item.get("payment_id"),
                        item.get("webhook_event_id"),
                        job_timeout=120,
                        **kwargs,
                    )
        finally:
            connection.close()
        return True
    except Exception:
        logger.exception("failed to enqueue recovery follow-up jobs")
        return False


def _apply_followups_now(followups: object) -> None:
    settings = get_worker_settings()
    if not settings.database_url:
        return
    session = SessionLocal(settings.database_url)
    try:
        apply_followups(session, followups)
        session.commit()
    except Exception:
        session.rollback()
        logger.exception("failed to apply recovery follow-up jobs locally")
        raise
    finally:
        session.close()


def will_retry() -> bool:
    """True when RQ will schedule another attempt after this failure."""
    try:
        from rq.job import get_current_job
    except Exception:
        return False
    job = get_current_job()
    if job is None:
        return False
    retries_left = getattr(job, "retries_left", None)
    if isinstance(retries_left, int):
        return retries_left > 0
    checker = getattr(job, "should_retry", None)
    if callable(checker):
        return bool(checker())
    return bool(checker)
