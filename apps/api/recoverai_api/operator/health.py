from __future__ import annotations

from typing import Any

from recoverai_api.config import Settings
from recoverai_api.health.checks import STATUS_OK, STATUS_SKIPPED, STATUS_UNAVAILABLE, CheckResult

STATUS_DEGRADED = "degraded"


def _result(name: str, status: str, *, detail: str, required: bool = False) -> dict[str, Any]:
    return {"name": name, "status": status, "detail": detail, "required": required}


def check_worker(settings: Settings) -> dict[str, Any]:
    if not settings.redis_url:
        return _result("worker", STATUS_SKIPPED, detail="REDIS_URL is not configured")
    try:
        from redis import Redis
        from rq import Worker

        client = Redis.from_url(settings.redis_url, socket_connect_timeout=3)
        try:
            workers = Worker.all(connection=client)
            if workers:
                names = [str(getattr(item, "name", "worker")) for item in workers[:8]]
                return _result(
                    "worker",
                    STATUS_OK,
                    detail=f"{len(workers)} RQ worker(s) registered: {', '.join(names)}",
                )
            return _result(
                "worker",
                STATUS_UNAVAILABLE,
                detail="Redis is reachable but no RQ workers are registered",
            )
        finally:
            client.close()
    except Exception:
        return _result("worker", STATUS_UNAVAILABLE, detail="Could not query RQ workers")


def check_provider(settings: Settings) -> dict[str, Any]:
    provider = (settings.payment_provider or "simulator").strip().lower()
    if provider in {"simulator", "local", "sim"}:
        return _result(
            "provider",
            STATUS_OK,
            detail="Local payment simulator is the configured provider",
        )
    return _result(
        "provider",
        STATUS_UNAVAILABLE,
        detail=f"Provider '{provider}' is not implemented (Razorpay is Phase 10)",
    )


def check_llm(settings: Settings) -> dict[str, Any]:
    provider = (settings.llm_provider or "stub").strip().lower()
    if provider in {"stub", "none", "disabled"}:
        return _result(
            "llm",
            STATUS_UNAVAILABLE,
            detail="LLM provider is stubbed; agents use DETERMINISTIC_FALLBACK",
        )
    if not settings.llm_api_key:
        return _result(
            "llm",
            STATUS_UNAVAILABLE,
            detail=f"LLM provider '{provider}' has no API key configured",
        )
    return _result(
        "llm",
        STATUS_DEGRADED,
        detail=f"LLM provider '{provider}' is configured but not live-probed",
    )


def system_health_payload(settings: Settings, ready_results: list[CheckResult]) -> dict[str, Any]:
    mapped = {
        item.name: _result(
            item.name,
            item.status,
            detail="Configured dependency check",
            required=item.required,
        )
        for item in ready_results
    }
    mapped["api"] = _result("api", STATUS_OK, detail="RecoverAI API process is up", required=True)
    mapped["worker"] = check_worker(settings)
    mapped["provider"] = check_provider(settings)
    mapped["llm"] = check_llm(settings)
    order = ["api", "application", "database", "redis", "worker", "provider", "llm"]
    checks = [mapped[name] for name in order if name in mapped]
    failing = [
        item for item in checks if item["status"] == STATUS_UNAVAILABLE and item.get("required")
    ]
    status = "healthy"
    if any(item["status"] == STATUS_UNAVAILABLE for item in checks):
        status = "degraded"
    if failing:
        status = "unavailable"
    return {"status": status, "checks": checks, "synthetic": False}
