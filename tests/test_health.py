from collections.abc import Iterator
from unittest.mock import MagicMock, patch

import pytest
from fastapi.testclient import TestClient

from recoverai_api.config import Settings
from recoverai_api.health.checks import CheckResult
from recoverai_api.main import create_app


@pytest.fixture
def settings() -> Settings:
    return Settings(
        app_env="development",
        database_url=None,
        redis_url=None,
        llm_api_key=None,
        razorpay_key_secret=None,
    )


@pytest.fixture
def client(settings: Settings) -> Iterator[TestClient]:
    app = create_app(settings)
    with TestClient(app) as test_client:
        yield test_client


def test_health_returns_200(client: TestClient) -> None:
    response = client.get("/health")
    assert response.status_code == 200
    body = response.json()
    assert body == {"status": "ok", "service": "recoverai-api"}
    assert "X-Request-ID" in response.headers


def test_health_echoes_request_id(client: TestClient) -> None:
    response = client.get("/health", headers={"X-Request-ID": "test-req-1"})
    assert response.headers["X-Request-ID"] == "test-req-1"


def test_ready_when_dependencies_unconfigured(client: TestClient) -> None:
    response = client.get("/ready")
    assert response.status_code == 200
    body = response.json()
    assert body["status"] == "ready"
    assert body["checks"]["application"] == "ok"
    assert body["checks"]["database"] == "skipped"
    assert body["checks"]["redis"] == "skipped"


def test_ready_when_dependencies_ok(settings: Settings) -> None:
    settings.database_url = "postgresql://recoverai:recoverai@localhost:5432/recoverai"
    settings.redis_url = "redis://localhost:6379/0"
    app = create_app(settings)
    with (
        patch("recoverai_api.health.router.run_readiness_checks") as mocked,
        TestClient(app) as client,
    ):
        mocked.return_value = [
            CheckResult(name="application", status="ok", required=True),
            CheckResult(name="database", status="ok", required=True),
            CheckResult(name="redis", status="ok", required=True),
        ]
        response = client.get("/ready")
    assert response.status_code == 200
    assert response.json()["status"] == "ready"
    assert response.json()["checks"] == {
        "application": "ok",
        "database": "ok",
        "redis": "ok",
    }


def test_ready_when_redis_unavailable(settings: Settings) -> None:
    settings.redis_url = "redis://localhost:6379/0"
    app = create_app(settings)
    with (
        patch("recoverai_api.health.router.run_readiness_checks") as mocked,
        TestClient(app) as client,
    ):
        mocked.return_value = [
            CheckResult(name="application", status="ok", required=True),
            CheckResult(name="database", status="skipped", required=False),
            CheckResult(name="redis", status="unavailable", required=True),
        ]
        response = client.get("/ready")
    assert response.status_code == 503
    body = response.json()
    assert body["status"] == "not_ready"
    assert body["checks"]["redis"] == "unavailable"
    assert body["error"]["code"] == "SERVICE_NOT_READY"
    assert "request_id" in body["error"]


def test_ready_reports_database_unavailable(settings: Settings) -> None:
    settings.database_url = "postgresql://recoverai:recoverai@127.0.0.1:1/recoverai"
    app = create_app(settings)
    with TestClient(app) as client:
        response = client.get("/ready")
    assert response.status_code == 503
    body = response.json()
    assert body["checks"]["database"] == "unavailable"


def test_database_check_reports_unavailable() -> None:
    settings = Settings(database_url="postgresql://recoverai:recoverai@127.0.0.1:1/recoverai")
    mock_connect = MagicMock(side_effect=OSError("connection refused"))
    with patch("recoverai_api.health.checks.psycopg.connect", mock_connect):
        from recoverai_api.health.checks import check_database

        result = check_database(settings)
    assert result.status == "unavailable"
    assert result.ok is False
