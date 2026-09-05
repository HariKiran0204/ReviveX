from __future__ import annotations

from collections.abc import Iterator
from uuid import UUID

import pytest
from fastapi.testclient import TestClient
from sqlalchemy.orm import Session

from recoverai_api.config import Settings
from recoverai_api.main import create_app
from recoverai_db.enums import ApprovalStatus
from recoverai_db.models import Approval
from recoverai_domain.fixtures import ensure_simulator_fixtures
from recoverai_domain.ingestion import ImmediateEventQueue


@pytest.fixture
def queue() -> ImmediateEventQueue:
    return ImmediateEventQueue()


@pytest.fixture
def client(db_session: Session, queue: ImmediateEventQueue) -> Iterator[TestClient]:
    settings = Settings(app_env="development", database_url=None, redis_url=None)
    app = create_app(settings)
    app.state.event_queue = queue
    app.state.db_session_factory = lambda: db_session
    with TestClient(app) as test_client:
        yield test_client


def test_command_center_empty_merchant(client: TestClient) -> None:
    response = client.get("/v1/metrics/command-center")
    assert response.status_code in {200, 404}
    if response.status_code == 200:
        body = response.json()
        assert body["revenue_recovered"] == "0.00"
        assert "expected_recovery" in body


def test_operator_flow_cases_detail_approval(
    client: TestClient, db_session: Session, queue: ImmediateEventQueue
) -> None:
    ensure_simulator_fixtures(db_session)
    demo = client.post("/v1/operator/demo", json={"kind": "approval", "seed": 901})
    assert demo.status_code == 200, demo.text
    payload = demo.json()
    assert payload["kind"] == "approval"
    assert payload["cases"]
    case_id = payload["cases"][0]["id"]

    listed = client.get("/v1/recovery-cases", params={"page": 1, "page_size": 25})
    assert listed.status_code == 200
    items = listed.json()["items"]
    assert any(row["id"] == case_id for row in items)

    detail = client.get(f"/v1/recovery-cases/{case_id}")
    assert detail.status_code == 200
    body = detail.json()
    assert body["case"]["amount_recovered"] == "0.00"

    metrics = client.get("/v1/metrics/command-center")
    assert metrics.status_code == 200
    assert metrics.json()["active_cases"] >= 1

    approvals = client.get("/v1/approvals", params={"status": "PENDING"})
    assert approvals.status_code == 200
    pending = approvals.json()["items"]
    assert pending, "approval demo should create a pending approval"
    approval_id = pending[0]["id"]
    action_id = pending[0]["action_id"]
    assert action_id

    decide = client.post(f"/v1/approvals/{approval_id}/approve", json={"actor_id": "demo-operator"})
    assert decide.status_code == 200, decide.text
    stored = db_session.get(Approval, UUID(approval_id))
    assert stored is not None
    db_session.refresh(stored)
    assert stored.status == ApprovalStatus.APPROVED

    after = client.get(f"/v1/recovery-cases/{case_id}")
    assert after.status_code == 200
    assert after.json()["case"]["id"] == case_id


def test_policy_get_and_patch(client: TestClient, db_session: Session) -> None:
    ensure_simulator_fixtures(db_session)
    current = client.get("/v1/policy")
    assert current.status_code == 200
    policy = current.json()["policy"]
    policy["max_retry_attempts"] = 2
    policy["max_discount_percent"] = "8"
    updated = client.patch("/v1/policy", json={"policy": policy})
    assert updated.status_code == 200, updated.text
    assert updated.json()["policy"]["max_retry_attempts"] == 2
    reread = client.get("/v1/policy")
    assert reread.json()["policy"]["max_retry_attempts"] == 2


def test_policy_rejects_illegal_blocked_action(client: TestClient, db_session: Session) -> None:
    ensure_simulator_fixtures(db_session)
    current = client.get("/v1/policy").json()["policy"]
    current["blocked_action_types"] = ["LAUNCH_MISSILES"]
    response = client.patch("/v1/policy", json={"policy": current})
    assert response.status_code == 400


def test_audit_and_evaluation_and_health(client: TestClient, db_session: Session) -> None:
    ensure_simulator_fixtures(db_session)
    audit = client.get("/v1/audit-events", params={"page": 1, "page_size": 10})
    assert audit.status_code == 200
    evaluation = client.get("/v1/evaluation/latest")
    assert evaluation.status_code == 200
    assert evaluation.json()["synthetic"] is True
    health = client.get("/v1/system-health")
    assert health.status_code == 200
    names = {item["name"] for item in health.json()["checks"]}
    assert {"api", "database", "redis", "worker", "provider", "llm"} <= names
    llm = next(item for item in health.json()["checks"] if item["name"] == "llm")
    assert llm["status"] == "unavailable"


def test_no_amount_recovered_write_route() -> None:
    settings = Settings(app_env="development", database_url=None, redis_url=None)
    app = create_app(settings)
    paths = [getattr(route, "path", "") for route in app.routes]
    assert not any("amount_recovered" in path for path in paths)


def test_demo_failed_payment_creates_case(client: TestClient, db_session: Session) -> None:
    ensure_simulator_fixtures(db_session)
    response = client.post("/v1/operator/demo", json={"kind": "failed_payment", "seed": 44})
    assert response.status_code == 200, response.text
    listed = client.get("/v1/recovery-cases")
    assert listed.status_code == 200
    assert listed.json()["total"] >= 1


def test_command_center_after_case(client: TestClient, db_session: Session) -> None:
    ensure_simulator_fixtures(db_session)
    client.post("/v1/operator/demo", json={"kind": "run_demo", "seed": 77, "amount": "199.00"})
    metrics = client.get("/v1/metrics/command-center").json()
    assert float(metrics["revenue_at_risk"]) >= 0
    assert float(metrics["revenue_recovered"]) >= 0


def test_batch_evaluation_route(client: TestClient) -> None:
    response = client.get("/v1/evaluation/batch", params={"cases": 100, "seed": 42, "revivex_mode": "ml"})
    assert response.status_code == 200
    body = response.json()
    assert body["n_cases"] == 100
    assert body["seed"] == 42
    assert body["revivex_mode"] == "ml"
    assert "revenue_at_risk" in body
    assert "baseline_recovered" in body
    assert "revivex_recovered" in body
    assert "incremental_revenue" in body
    assert "recovery_uplift_percent" in body
    assert body["ml_prediction_count"] == 100
    assert body["heuristic_fallback_count"] == 0
    assert isinstance(body.get("multi_seed_results"), list)
    assert len(body["multi_seed_results"]) == 5

