from __future__ import annotations

from typing import Annotated

from fastapi import APIRouter, Depends, Query, Request
from sqlalchemy.orm import Session
from starlette.responses import JSONResponse

from recoverai_api.config import Settings
from recoverai_api.deps import get_db_session, get_event_queue, get_request_settings
from recoverai_api.events.schemas import (
    EventListResponse,
    EventSummary,
    IngestAcknowledgement,
    SimulationEventRequest,
    SimulationScenarioRequest,
    SimulatorWebhookRequest,
)
from recoverai_api.events.service import (
    ingest_simulated_payment,
    ingestion,
    resolve_merchant_id,
    resolve_simulation_parties,
    resolve_webhook_parties,
    run_scenario,
    webhook_to_provider_event,
)
from recoverai_api.request_context import get_request_id
from recoverai_api.schemas import error_response
from recoverai_db.repositories import WebhookEventRepository
from recoverai_domain.errors import IngestionError
from recoverai_domain.ingestion import EventQueue, IngestResult

router = APIRouter()

DbSession = Annotated[Session, Depends(get_db_session)]
QueueDep = Annotated[EventQueue, Depends(get_event_queue)]
SettingsDep = Annotated[Settings, Depends(get_request_settings)]


def _http_error(exc: IngestionError) -> JSONResponse:
    payload = error_response(exc.code, exc.message)
    return JSONResponse(status_code=exc.http_status, content=payload.model_dump())


def _ack(result: IngestResult) -> IngestAcknowledgement:
    return IngestAcknowledgement(
        accepted=True,
        duplicate=result.duplicate,
        queued=result.queued,
        event_id=result.event_id,
        webhook_event_id=result.webhook_event_id,
        status=result.status,
        merchant_id=result.merchant_id,
        correlation_id=result.correlation_id,
    )


@router.post("/v1/webhooks/simulator", response_model=IngestAcknowledgement)
def ingest_simulator_webhook(
    body: SimulatorWebhookRequest,
    session: DbSession,
    queue: QueueDep,
) -> IngestAcknowledgement | JSONResponse:
    try:
        merchant_id, customer_id, customer_external_id = resolve_webhook_parties(
            session,
            merchant_id=body.merchant_id,
            merchant_slug=body.merchant_slug,
            customer_id=body.customer_id,
            customer_external_id=body.customer_external_id,
        )
        event = webhook_to_provider_event(
            event_id=body.event_id,
            event_type=body.event_type,
            merchant_id=merchant_id,
            provider_resource_id=body.provider_resource_id,
            provider_payment_id=body.provider_payment_id,
            provider_order_id=body.provider_order_id,
            merchant_reference=body.merchant_reference,
            customer_id=customer_id,
            customer_external_id=customer_external_id,
            amount=body.amount,
            currency=body.currency,
            status=body.status,
            failure_reason=body.failure_reason,
            attempt_number=body.attempt_number,
            payment_method=body.payment_method,
            correlation_id=body.correlation_id,
            payload=body.payload,
            occurred_at=body.occurred_at,
        )
        result = ingestion.ingest(
            session,
            event,
            merchant_id=merchant_id,
            queue=queue,
            request_id=get_request_id(),
        )
        return _ack(result)
    except IngestionError as exc:
        return _http_error(exc)


@router.post("/v1/simulation/events", response_model=IngestAcknowledgement)
def simulate_event(
    body: SimulationEventRequest,
    session: DbSession,
    queue: QueueDep,
    settings: SettingsDep,
) -> IngestAcknowledgement | JSONResponse:
    try:
        merchant_id, customer_id, customer_external_id = resolve_simulation_parties(
            session,
            merchant_id=body.merchant_id,
            merchant_slug=body.merchant_slug,
            customer_id=body.customer_id,
            customer_external_id=body.customer_external_id,
        )
        seed = body.seed if body.seed is not None else settings.simulation_seed
        result = ingest_simulated_payment(
            session,
            queue,
            merchant_id=merchant_id,
            customer_id=customer_id,
            customer_external_id=customer_external_id,
            amount=body.amount,
            currency=body.currency,
            seed=seed,
            event_type=body.event_type,
            failure_reason=body.failure_reason,
            intended_status=body.intended_status,
            attempt_number=body.attempt_number,
            correlation_id=body.correlation_id or get_request_id(),
        )
        return _ack(result)
    except IngestionError as exc:
        return _http_error(exc)


@router.post("/v1/simulation/scenarios", response_model=None)
def simulate_scenario(
    body: SimulationScenarioRequest,
    session: DbSession,
    queue: QueueDep,
    settings: SettingsDep,
) -> dict[str, object] | JSONResponse:
    try:
        results = run_scenario(
            session,
            queue,
            scenario=body.scenario,
            settings=settings,
            merchant_slug=body.merchant_slug,
            seed=body.seed,
            amount=body.amount,
        )
        return {
            "scenario": body.scenario.strip().upper(),
            "acknowledgements": [_ack(item).model_dump(mode="json") for item in results],
        }
    except IngestionError as exc:
        return _http_error(exc)


@router.get("/v1/events", response_model=EventListResponse)
def list_events(
    request: Request,
    session: DbSession,
    merchant_slug: Annotated[str | None, Query()] = None,
    limit: Annotated[int, Query(ge=1, le=200)] = 50,
) -> EventListResponse | JSONResponse:
    del request
    try:
        merchant_id = None
        if merchant_slug:
            merchant_id = resolve_merchant_id(
                session, merchant_id=None, merchant_slug=merchant_slug, allow_fixture=False
            )
        rows = WebhookEventRepository(session).list_recent(merchant_id=merchant_id, limit=limit)
        return EventListResponse(
            events=[
                EventSummary(
                    id=row.id,
                    merchant_id=row.merchant_id,
                    provider=row.provider,
                    event_id=row.event_id,
                    event_type=row.event_type,
                    status=row.status,
                    received_at=row.received_at,
                    processed_at=row.processed_at,
                    correlation_id=row.correlation_id,
                    error_code=row.error_code,
                )
                for row in rows
            ]
        )
    except IngestionError as exc:
        return _http_error(exc)
