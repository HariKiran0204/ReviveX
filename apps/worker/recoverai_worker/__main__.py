from __future__ import annotations

import json
import logging
import os
import socket
import sys
import threading
from datetime import UTC, datetime

from redis import Redis
from rq import Queue, Worker

from recoverai_worker.config import WorkerSettings, get_worker_settings
from recoverai_worker.jobs import health_heartbeat


class JsonLogFormatter(logging.Formatter):
    def __init__(self, service: str) -> None:
        super().__init__()
        self._service = service

    def format(self, record: logging.LogRecord) -> str:
        payload = {
            "timestamp": datetime.now(UTC).isoformat(),
            "level": record.levelname,
            "service": self._service,
            "message": record.getMessage(),
        }
        for key in ("correlation_id", "merchant_id", "event_id"):
            value = getattr(record, key, None)
            if value is not None:
                payload[key] = value
        return json.dumps(payload, default=str)


def configure_logging(service: str, level: str) -> None:
    root = logging.getLogger()
    root.handlers.clear()
    handler = logging.StreamHandler(sys.stdout)
    handler.setFormatter(JsonLogFormatter(service=service))
    root.addHandler(handler)
    root.setLevel(getattr(logging, level.upper(), logging.INFO))


def _worker_id() -> str:
    return f"{socket.gethostname()}-{os.getpid()}"


def _heartbeat_loop(interval: int, identity: str, stop: threading.Event) -> None:
    log = logging.getLogger("recoverai_worker.heartbeat")
    while not stop.wait(timeout=interval):
        timestamp = datetime.now(UTC).isoformat()
        log.info(
            "RecoverAI worker heartbeat worker=%s timestamp=%s",
            identity,
            timestamp,
        )


def run(settings: WorkerSettings | None = None) -> None:
    resolved = settings or get_worker_settings()
    configure_logging(resolved.service_name, resolved.log_level)
    logger = logging.getLogger(__name__)
    identity = _worker_id()
    logger.info(
        "RecoverAI worker heartbeat worker=%s timestamp=%s",
        identity,
        datetime.now(UTC).isoformat(),
    )

    connection = Redis.from_url(resolved.redis_url, socket_connect_timeout=5)
    connection.ping()

    queue = Queue(resolved.queue_name, connection=connection)
    queue.enqueue(health_heartbeat, identity)

    stop = threading.Event()
    thread = threading.Thread(
        target=_heartbeat_loop,
        args=(resolved.heartbeat_interval_seconds, identity, stop),
        name="recoverai-heartbeat",
        daemon=True,
    )
    thread.start()
    logger.info("RecoverAI RQ worker starting worker=%s queue=%s", identity, resolved.queue_name)

    worker = Worker([queue], connection=connection, name=identity)
    try:
        worker.work(with_scheduler=False)
    finally:
        stop.set()


def main() -> None:
    run()


if __name__ == "__main__":
    main()
