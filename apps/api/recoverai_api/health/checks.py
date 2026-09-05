from __future__ import annotations

import logging
from dataclasses import dataclass

import psycopg
from redis import Redis

from recoverai_api.config import Settings

logger = logging.getLogger(__name__)

STATUS_OK = "ok"
STATUS_UNAVAILABLE = "unavailable"
STATUS_SKIPPED = "skipped"


@dataclass(frozen=True)
class CheckResult:
    name: str
    status: str
    required: bool

    @property
    def ok(self) -> bool:
        if self.status == STATUS_SKIPPED:
            return not self.required
        return self.status == STATUS_OK


def check_application() -> CheckResult:
    return CheckResult(name="application", status=STATUS_OK, required=True)


def check_database(settings: Settings) -> CheckResult:
    required = settings.is_production or settings.database_url is not None
    if not settings.database_url:
        return CheckResult(name="database", status=STATUS_SKIPPED, required=required)
    try:
        with psycopg.connect(settings.database_url, connect_timeout=3) as conn:
            conn.execute("SELECT 1")
        return CheckResult(name="database", status=STATUS_OK, required=required)
    except Exception:
        logger.warning("database readiness check failed", exc_info=True)
        return CheckResult(name="database", status=STATUS_UNAVAILABLE, required=required)


def check_redis(settings: Settings) -> CheckResult:
    required = settings.is_production or settings.redis_url is not None
    if not settings.redis_url:
        return CheckResult(name="redis", status=STATUS_SKIPPED, required=required)
    client: Redis[bytes] | None = None
    try:
        client = Redis.from_url(settings.redis_url, socket_connect_timeout=3)
        if client.ping() is True:
            return CheckResult(name="redis", status=STATUS_OK, required=required)
        return CheckResult(name="redis", status=STATUS_UNAVAILABLE, required=required)
    except Exception:
        logger.warning("redis readiness check failed", exc_info=True)
        return CheckResult(name="redis", status=STATUS_UNAVAILABLE, required=required)
    finally:
        if client is not None:
            client.close()


def run_readiness_checks(settings: Settings) -> list[CheckResult]:
    return [
        check_application(),
        check_database(settings),
        check_redis(settings),
    ]
