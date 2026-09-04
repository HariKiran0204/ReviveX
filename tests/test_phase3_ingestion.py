from __future__ import annotations

from collections.abc import Iterator
from decimal import Decimal
from uuid import UUID

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import select
from sqlalchemy.orm import Session

from recoverai_api.config import Settings
from recoverai_api.main import create_app
from recoverai_db.enums import (
    PaymentStatus,
    RecoveryCaseStatus,
    RecoveryCaseType,
    WebhookEventStatus,
)
from recoverai_db.models import AuditEvent, RecoveryCase, WebhookEvent
from recoverai_db.repositories import (
    AuditEventRepository,
    PaymentRepository,
    RecoveryCaseRepository,
)
from recoverai_domain.audit import AuditEventType
from recoverai_domain.fixtures import (
    SIMULATOR_MERCHANT_SLUG,
    ensure_simulator_fixtures,
    simulator_merchant_id,
)
from recoverai_domain.ingestion import ImmediateEventQueue
from recoverai_domain.processing import internal_payment_uuid, process_webhook_event
from recoverai_providers.models import ProviderName


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


def _process_queue(session: Session, queue: ImmediateEventQueue) -> None:
    for webhook_id in list(queue.enqueued):
        process_webhook_event(session, webhook_id)


def test_failed_payment_ingestion_creates_detected_case(
    client: TestClient, db_session: Session, queue: ImmediateEventQueue
) -> None:
    merchant, customer = ensure_simulator_fixtures(db_session)
    response = client.post(
        "/v1/simulation/events",
        json={
            "event_type": "payment.failed",
            "failure_reason": "TEMPORARY_BANK_ERROR",
            "amount": "499.00",
            "merchant_id": str(merchant.id),
            "customer_id": str(customer.id),
            "seed": 42,
            "intended_status": "FAILED",
        },
    )
    assert response.status_code == 200
    body = response.json()
    assert body["duplicate"] is False
    assert body["queued"] is True
    _process_queue(db_session, queue)

    webhook = db_session.get(WebhookEvent, UUID(body["webhook_event_id"]))
    assert webhook is not None
    assert webhook.provider == ProviderName.SIMULATOR
    assert webhook.status == WebhookEventStatus.PROCESSED

    payments = PaymentRepository(db_session).list_for_customer(merchant.id, customer.id)
    assert len(payments) == 1
    payment = payments[0]
    assert payment.status == PaymentStatus.FAILED
    assert payment.id != UUID(int=0)
    assert payment.provider_payment_id is not None
    assert str(payment.id) != payment.provider_payment_id
    assert payment.merchant_id == merchant.id

    cases = RecoveryCaseRepository(db_session).list_open_for_payment(merchant.id, payment.id)
    assert len(cases) == 1
    case = cases[0]
    assert case.case_type == RecoveryCaseType.FAILED_PAYMENT
    assert case.status == RecoveryCaseStatus.DETECTED
    assert case.amount_at_risk == Decimal("499.00")
    assert case.amount_recovered == Decimal("0.00")
    assert case.source_event_id == webhook.id
    assert case.merchant_id == merchant.id
    assert case.customer_id == customer.id

    created = AuditEventRepository(db_session).list_by_type(
        merchant.id, AuditEventType.RECOVERY_CASE_CREATED
    )
    assert created
    received = AuditEventRepository(db_session).list_by_type(
        merchant.id, AuditEventType.PROVIDER_EVENT_RECEIVED
    )
    assert received


def test_duplicate_event_is_idempotent(
    client: TestClient, db_session: Session, queue: ImmediateEventQueue
) -> None:
    merchant, customer = ensure_simulator_fixtures(db_session)
    payload = {
        "event_id": "evt_dup_1",
        "event_type": "payment.failed",
        "provider_resource_id": "pay_sim_dup_1",
        "merchant_id": str(merchant.id),
        "customer_id": str(customer.id),
        "amount": "120.00",
        "failure_reason": "TEMPORARY_BANK_ERROR",
        "status": "FAILED",
    }
    first = client.post("/v1/webhooks/simulator", json=payload)
    second = client.post("/v1/webhooks/simulator", json=payload)
    assert first.status_code == 200
    assert second.status_code == 200
    assert first.json()["webhook_event_id"] == second.json()["webhook_event_id"]
    assert second.json()["duplicate"] is True
    _process_queue(db_session, queue)

    events = list(
        db_session.scalars(select(WebhookEvent).where(WebhookEvent.event_id == "evt_dup_1")).all()
    )
    assert len(events) == 1
    payments = PaymentRepository(db_session).list_for_customer(merchant.id, customer.id)
    assert len(payments) == 1
    cases = RecoveryCaseRepository(db_session).list_open_for_payment(merchant.id, payments[0].id)
    assert len(cases) == 1
    ignored = AuditEventRepository(db_session).list_by_type(
        merchant.id, AuditEventType.DUPLICATE_EVENT_IGNORED
    )
    assert ignored


def test_second_failure_event_attaches_existing_case(
    client: TestClient, db_session: Session, queue: ImmediateEventQueue
) -> None:
    merchant, customer = ensure_simulator_fixtures(db_session)
    shared_payment_id = "pay_sim_same_payment"
    for event_id in ("evt_fail_a", "evt_fail_b"):
        response = client.post(
            "/v1/webhooks/simulator",
            json={
                "event_id": event_id,
                "event_type": "payment.failed",
                "provider_resource_id": shared_payment_id,
                "merchant_id": str(merchant.id),
                "customer_id": str(customer.id),
                "amount": "80.00",
                "failure_reason": "INSUFFICIENT_FUNDS",
                "status": "FAILED",
            },
        )
        assert response.status_code == 200
        assert response.json()["duplicate"] is False
    _process_queue(db_session, queue)
    payment = PaymentRepository(db_session).get_by_provider_payment_id(
        merchant.id, ProviderName.SIMULATOR, shared_payment_id
    )
    assert payment is not None
    cases = RecoveryCaseRepository(db_session).list_cases(merchant.id)
    payment_cases = [case for case in cases if case.payment_id == payment.id]
    assert len(payment_cases) == 1
    attached = AuditEventRepository(db_session).list_by_type(
        merchant.id, AuditEventType.RECOVERY_CASE_ATTACHED
    )
    assert attached


def test_captured_event_updates_payment_without_marking_recovered(
    client: TestClient, db_session: Session, queue: ImmediateEventQueue
) -> None:
    merchant, customer = ensure_simulator_fixtures(db_session)
    fail = client.post(
        "/v1/webhooks/simulator",
        json={
            "event_id": "evt_then_capture_fail",
            "event_type": "payment.failed",
            "provider_resource_id": "pay_sim_capture",
            "merchant_id": str(merchant.id),
            "customer_id": str(customer.id),
            "amount": "200.00",
            "failure_reason": "NETWORK_TIMEOUT",
            "status": "FAILED",
        },
    )
    captured = client.post(
        "/v1/webhooks/simulator",
        json={
            "event_id": "evt_then_capture_ok",
            "event_type": "payment.captured",
            "provider_resource_id": "pay_sim_capture",
            "merchant_id": str(merchant.id),
            "customer_id": str(customer.id),
            "amount": "200.00",
            "status": "CAPTURED",
        },
    )
    assert fail.status_code == 200
    assert captured.status_code == 200
    _process_queue(db_session, queue)
    payment = PaymentRepository(db_session).get_by_provider_payment_id(
        merchant.id, ProviderName.SIMULATOR, "pay_sim_capture"
    )
    assert payment is not None
    assert payment.status == PaymentStatus.CAPTURED
    assert payment.captured_at is not None
    cases = RecoveryCaseRepository(db_session).list_open_for_payment(merchant.id, payment.id)
    assert len(cases) == 1
    assert cases[0].status == RecoveryCaseStatus.DETECTED
    assert cases[0].amount_recovered == Decimal("0.00")


def test_refund_event_updates_payment(
    client: TestClient, db_session: Session, queue: ImmediateEventQueue
) -> None:
    merchant, customer = ensure_simulator_fixtures(db_session)
    client.post(
        "/v1/webhooks/simulator",
        json={
            "event_id": "evt_refund_cap",
            "event_type": "payment.captured",
            "provider_resource_id": "pay_sim_refund",
            "merchant_id": str(merchant.id),
            "customer_id": str(customer.id),
            "amount": "75.00",
            "status": "CAPTURED",
        },
    )
    client.post(
        "/v1/webhooks/simulator",
        json={
            "event_id": "evt_refund_done",
            "event_type": "payment.refunded",
            "provider_resource_id": "pay_sim_refund",
            "merchant_id": str(merchant.id),
            "customer_id": str(customer.id),
            "amount": "75.00",
            "status": "REFUNDED",
        },
    )
    _process_queue(db_session, queue)
    payment = PaymentRepository(db_session).get_by_provider_payment_id(
        merchant.id, ProviderName.SIMULATOR, "pay_sim_refund"
    )
    assert payment is not None
    assert payment.status == PaymentStatus.REFUNDED


def test_malformed_event_rejected(client: TestClient, db_session: Session) -> None:
    response = client.post("/v1/webhooks/simulator", json={})
    assert response.status_code == 422
    assert db_session.scalar(select(WebhookEvent).limit(1)) is None
    assert db_session.scalar(select(RecoveryCase).limit(1)) is None


def test_unknown_event_stored_without_side_effects(
    client: TestClient, db_session: Session, queue: ImmediateEventQueue
) -> None:
    merchant, customer = ensure_simulator_fixtures(db_session)
    response = client.post(
        "/v1/webhooks/simulator",
        json={
            "event_id": "evt_unknown_1",
            "event_type": "payment.something_future",
            "provider_resource_id": "pay_sim_unknown",
            "merchant_id": str(merchant.id),
            "customer_id": str(customer.id),
            "amount": "10.00",
        },
    )
    assert response.status_code == 200
    _process_queue(db_session, queue)
    webhook = db_session.get(WebhookEvent, UUID(response.json()["webhook_event_id"]))
    assert webhook is not None
    assert webhook.status == WebhookEventStatus.PROCESSED
    assert PaymentRepository(db_session).list_for_customer(merchant.id, customer.id) == []
    assert RecoveryCaseRepository(db_session).list_cases(merchant.id) == []
    ignored = AuditEventRepository(db_session).list_by_type(
        merchant.id, AuditEventType.UNKNOWN_EVENT_IGNORED
    )
    assert ignored


def test_worker_duplicate_processing_is_harmless(
    client: TestClient, db_session: Session, queue: ImmediateEventQueue
) -> None:
    merchant, customer = ensure_simulator_fixtures(db_session)
    response = client.post(
        "/v1/webhooks/simulator",
        json={
            "event_id": "evt_worker_dup",
            "event_type": "payment.failed",
            "provider_resource_id": "pay_sim_worker_dup",
            "merchant_id": str(merchant.id),
            "customer_id": str(customer.id),
            "amount": "33.00",
            "failure_reason": "DECLINED",
            "status": "FAILED",
        },
    )
    webhook_id = UUID(response.json()["webhook_event_id"])
    first = process_webhook_event(db_session, webhook_id)
    second = process_webhook_event(db_session, webhook_id)
    assert first["status"] == "processed"
    assert second["status"] == "already_processed"
    payment = PaymentRepository(db_session).get_by_provider_payment_id(
        merchant.id, ProviderName.SIMULATOR, "pay_sim_worker_dup"
    )
    assert payment is not None
    open_cases = RecoveryCaseRepository(db_session).list_open_for_payment(merchant.id, payment.id)
    assert len(open_cases) == 1


def test_merchant_context_and_internal_ids(
    client: TestClient, db_session: Session, queue: ImmediateEventQueue
) -> None:
    merchant, customer = ensure_simulator_fixtures(db_session)
    client.post(
        "/v1/webhooks/simulator",
        json={
            "event_id": "evt_ids",
            "event_type": "payment.failed",
            "provider_resource_id": "pay_sim_ids",
            "provider_order_id": "order_sim_ids",
            "merchant_id": str(merchant.id),
            "customer_id": str(customer.id),
            "amount": "15.00",
            "failure_reason": "EXPIRED_CARD",
            "status": "FAILED",
        },
    )
    _process_queue(db_session, queue)
    payment = PaymentRepository(db_session).get_by_provider_payment_id(
        merchant.id, ProviderName.SIMULATOR, "pay_sim_ids"
    )
    assert payment is not None
    assert payment.provider_order_id == "order_sim_ids"
    assert payment.id == internal_payment_uuid(merchant.id, ProviderName.SIMULATOR, "pay_sim_ids")
    assert payment.merchant_id == merchant.id


def test_missing_merchant_is_rejected(client: TestClient) -> None:
    response = client.post(
        "/v1/webhooks/simulator",
        json={
            "event_id": "evt_no_merchant",
            "event_type": "payment.failed",
            "provider_resource_id": "pay_x",
            "merchant_slug": "does-not-exist",
            "amount": "10.00",
        },
    )
    assert response.status_code == 404
    assert response.json()["error"]["code"] == "MISSING_MERCHANT"


def test_missing_customer_fails_processing(
    client: TestClient, db_session: Session, queue: ImmediateEventQueue
) -> None:
    merchant, _customer = ensure_simulator_fixtures(db_session)
    response = client.post(
        "/v1/webhooks/simulator",
        json={
            "event_id": "evt_no_customer",
            "event_type": "payment.failed",
            "provider_resource_id": "pay_no_cust",
            "merchant_id": str(merchant.id),
            "amount": "10.00",
            "status": "FAILED",
        },
    )
    assert response.status_code == 200
    webhook_id = UUID(response.json()["webhook_event_id"])
    result = process_webhook_event(db_session, webhook_id)
    assert result["status"] == "dead_letter"
    webhook = db_session.get(WebhookEvent, webhook_id)
    assert webhook is not None
    assert webhook.status == WebhookEventStatus.DEAD_LETTER
    assert webhook.error_code == "MISSING_CUSTOMER"


def test_list_events_and_scenario_a(
    client: TestClient, db_session: Session, queue: ImmediateEventQueue
) -> None:
    response = client.post("/v1/simulation/scenarios", json={"scenario": "A", "seed": 42})
    assert response.status_code == 200
    _process_queue(db_session, queue)
    listed = client.get("/v1/events")
    assert listed.status_code == 200
    events = listed.json()["events"]
    assert events
    assert events[0]["provider"] == ProviderName.SIMULATOR
    assert "payload" not in events[0]


def test_health_still_works_with_phase3_routes(client: TestClient) -> None:
    response = client.get("/health")
    assert response.status_code == 200
    assert response.json()["status"] == "ok"


def test_audit_events_have_no_secrets(
    client: TestClient, db_session: Session, queue: ImmediateEventQueue
) -> None:
    merchant, customer = ensure_simulator_fixtures(db_session)
    client.post(
        "/v1/webhooks/simulator",
        json={
            "event_id": "evt_secret",
            "event_type": "payment.failed",
            "provider_resource_id": "pay_secret",
            "merchant_id": str(merchant.id),
            "customer_id": str(customer.id),
            "amount": "9.00",
            "status": "FAILED",
            "payload": {"secret": "should-be-stripped", "authorization": "nope"},
        },
    )
    _process_queue(db_session, queue)
    webhook = db_session.scalars(
        select(WebhookEvent).where(WebhookEvent.event_id == "evt_secret")
    ).one()
    assert "secret" not in webhook.payload
    assert "authorization" not in webhook.payload
    audits = list(
        db_session.scalars(select(AuditEvent).where(AuditEvent.merchant_id == merchant.id)).all()
    )
    dumped = str([row.metadata_json for row in audits])
    assert "should-be-stripped" not in dumped


def test_demo_fixture_is_idempotent(db_session: Session) -> None:
    first_merchant, first_customer = ensure_simulator_fixtures(db_session)
    second_merchant, second_customer = ensure_simulator_fixtures(db_session)
    assert first_merchant.id == second_merchant.id == simulator_merchant_id()
    assert first_customer.id == second_customer.id
    assert first_merchant.slug == SIMULATOR_MERCHANT_SLUG
    from recoverai_db.models import Merchant

    merchants = list(
        db_session.scalars(select(Merchant).where(Merchant.id == simulator_merchant_id())).all()
    )
    assert len(merchants) == 1


def test_simulation_works_without_seeded_merchant(
    client: TestClient, db_session: Session, queue: ImmediateEventQueue
) -> None:
    response = client.post(
        "/v1/simulation/events",
        json={
            "event_type": "payment.failed",
            "failure_reason": "TEMPORARY_BANK_ERROR",
            "amount": "50.00",
            "seed": 7,
            "intended_status": "FAILED",
        },
    )
    assert response.status_code == 200
    assert response.json()["merchant_id"] == str(simulator_merchant_id())
    _process_queue(db_session, queue)
    webhook = db_session.get(WebhookEvent, UUID(response.json()["webhook_event_id"]))
    assert webhook is not None
    assert webhook.status == WebhookEventStatus.PROCESSED
    cases = RecoveryCaseRepository(db_session).list_cases(simulator_merchant_id())
    assert len(cases) == 1
    assert cases[0].status == RecoveryCaseStatus.DETECTED


def test_duplicate_processing_event_is_requeued(
    client: TestClient, db_session: Session, queue: ImmediateEventQueue
) -> None:
    merchant, customer = ensure_simulator_fixtures(db_session)
    payload = {
        "event_id": "evt_processing_dup",
        "event_type": "payment.failed",
        "provider_resource_id": "pay_processing_dup",
        "merchant_id": str(merchant.id),
        "customer_id": str(customer.id),
        "amount": "18.00",
        "status": "FAILED",
    }
    first = client.post("/v1/webhooks/simulator", json=payload)
    webhook_id = UUID(first.json()["webhook_event_id"])
    webhook = db_session.get(WebhookEvent, webhook_id)
    assert webhook is not None
    webhook.status = WebhookEventStatus.PROCESSING
    db_session.flush()
    queue.enqueued.clear()
    second = client.post("/v1/webhooks/simulator", json=payload)
    assert second.json()["duplicate"] is True
    assert second.json()["queued"] is True
    assert queue.enqueued == [webhook_id]


def test_processing_status_can_be_resumed(
    client: TestClient, db_session: Session, queue: ImmediateEventQueue
) -> None:
    merchant, customer = ensure_simulator_fixtures(db_session)
    response = client.post(
        "/v1/webhooks/simulator",
        json={
            "event_id": "evt_processing_resume",
            "event_type": "payment.failed",
            "provider_resource_id": "pay_processing_resume",
            "merchant_id": str(merchant.id),
            "customer_id": str(customer.id),
            "amount": "12.00",
            "status": "FAILED",
        },
    )
    webhook_id = UUID(response.json()["webhook_event_id"])
    webhook = db_session.get(WebhookEvent, webhook_id)
    assert webhook is not None
    webhook.status = WebhookEventStatus.PROCESSING
    db_session.flush()
    result = process_webhook_event(db_session, webhook_id)
    assert result["status"] == "processed"
    cases = RecoveryCaseRepository(db_session).list_cases(merchant.id)
    assert len(cases) == 1


def test_dead_letter_is_not_reprocessed(
    client: TestClient, db_session: Session, queue: ImmediateEventQueue
) -> None:
    merchant, _customer = ensure_simulator_fixtures(db_session)
    response = client.post(
        "/v1/webhooks/simulator",
        json={
            "event_id": "evt_dead",
            "event_type": "payment.failed",
            "provider_resource_id": "pay_dead",
            "merchant_id": str(merchant.id),
            "amount": "10.00",
            "status": "FAILED",
        },
    )
    webhook_id = UUID(response.json()["webhook_event_id"])
    process_webhook_event(db_session, webhook_id)
    again = process_webhook_event(db_session, webhook_id)
    assert again["status"] == "dead_letter"
    assert RecoveryCaseRepository(db_session).list_cases(merchant.id) == []


def test_duplicate_dead_letter_is_not_requeued(
    client: TestClient, db_session: Session, queue: ImmediateEventQueue
) -> None:
    merchant, _customer = ensure_simulator_fixtures(db_session)
    payload = {
        "event_id": "evt_dead_dup",
        "event_type": "payment.failed",
        "provider_resource_id": "pay_dead_dup",
        "merchant_id": str(merchant.id),
        "amount": "10.00",
        "status": "FAILED",
    }
    first = client.post("/v1/webhooks/simulator", json=payload)
    webhook_id = UUID(first.json()["webhook_event_id"])
    process_webhook_event(db_session, webhook_id)
    queue.enqueued.clear()
    second = client.post("/v1/webhooks/simulator", json=payload)
    assert second.json()["duplicate"] is True
    assert second.json()["queued"] is False
    assert queue.enqueued == []
