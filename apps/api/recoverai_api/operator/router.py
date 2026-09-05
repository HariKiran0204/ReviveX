from __future__ import annotations

from datetime import datetime
from decimal import Decimal
from typing import Annotated, Any
from uuid import UUID

from fastapi import APIRouter, Depends, Query, Request
from sqlalchemy.orm import Session
from starlette.responses import JSONResponse

from recoverai_api.config import Settings
from recoverai_api.deps import get_db_session, get_event_queue, get_request_settings
from recoverai_api.health.checks import run_readiness_checks
from recoverai_api.operator.demo import run_operator_demo
from recoverai_api.operator.health import system_health_payload
from recoverai_api.operator.merchant import resolve_merchant
from recoverai_api.operator.schemas import ApprovalDecisionRequest, DemoRequest, PolicyUpdateRequest
from recoverai_api.operator.service import (
    OperatorError,
    case_timeline,
    command_center_metrics,
    get_case_decision,
    get_case_detail,
    get_policy,
    latest_evaluation,
    list_agent_runs,
    list_approvals,
    list_audit_events,
    list_cases,
    list_tool_calls,
    run_batch_evaluation_service,
    update_policy,
)
from recoverai_api.schemas import error_response
from recoverai_db.models import Approval
from recoverai_domain.errors import DomainError, IdempotencyConflictError, InvalidTransitionError
from recoverai_domain.ingestion import EventQueue
from recoverai_domain.tools.approvals import ApprovalService

router = APIRouter()
DbSession = Annotated[Session, Depends(get_db_session)]
QueueDep = Annotated[EventQueue, Depends(get_event_queue)]
SettingsDep = Annotated[Settings, Depends(get_request_settings)]



def _error(exc: DomainError) -> JSONResponse:
    status = 400
    if isinstance(exc, InvalidTransitionError) or isinstance(exc, IdempotencyConflictError):
        status = 409
    if exc.code in {
        "RECOVERY_CASE_NOT_FOUND",
        "ACTION_NOT_FOUND",
        "APPROVAL_NOT_FOUND",
        "MERCHANT_NOT_FOUND",
    }:
        status = 404
    if exc.code == "MERCHANT_MISMATCH":
        status = 403
    payload = error_response(exc.code, exc.message)
    return JSONResponse(status_code=status, content=payload.model_dump())


@router.get("/v1/metrics/command-center", response_model=None)
def get_command_center(
    session: DbSession,
    merchant_id: Annotated[UUID | None, Query()] = None,
    merchant_slug: Annotated[str | None, Query()] = None,
) -> dict[str, Any] | JSONResponse:
    try:
        return command_center_metrics(session, merchant_id=merchant_id, merchant_slug=merchant_slug)
    except DomainError as exc:
        return _error(exc)


@router.get("/v1/recovery-cases", response_model=None)
def get_recovery_cases(
    session: DbSession,
    merchant_id: Annotated[UUID | None, Query()] = None,
    merchant_slug: Annotated[str | None, Query()] = None,
    status: Annotated[str | None, Query()] = None,
    case_type: Annotated[str | None, Query()] = None,
    min_amount: Annotated[Decimal | None, Query()] = None,
    max_amount: Annotated[Decimal | None, Query()] = None,
    sort: Annotated[str, Query()] = "created_at",
    direction: Annotated[str, Query()] = "desc",
    page: Annotated[int, Query(ge=1)] = 1,
    page_size: Annotated[int, Query(ge=1, le=100)] = 25,
) -> dict[str, Any] | JSONResponse:
    try:
        return list_cases(
            session,
            merchant_id=merchant_id,
            merchant_slug=merchant_slug,
            status=status,
            case_type=case_type,
            min_amount=min_amount,
            max_amount=max_amount,
            sort=sort,
            direction=direction,
            page=page,
            page_size=page_size,
        )
    except DomainError as exc:
        return _error(exc)


@router.get("/v1/recovery-cases/{case_id}", response_model=None)
def get_recovery_case(
    case_id: UUID,
    session: DbSession,
    merchant_id: Annotated[UUID | None, Query()] = None,
    merchant_slug: Annotated[str | None, Query()] = None,
) -> dict[str, Any] | JSONResponse:
    try:
        merchant = None
        if merchant_id or merchant_slug:
            merchant = resolve_merchant(
                session, merchant_id=merchant_id, merchant_slug=merchant_slug
            )
        return get_case_detail(session, case_id, merchant)
    except DomainError as exc:
        return _error(exc)


@router.get("/v1/recovery-cases/{case_id}/timeline", response_model=None)
def get_case_timeline(
    case_id: UUID,
    session: DbSession,
    merchant_id: Annotated[UUID | None, Query()] = None,
    merchant_slug: Annotated[str | None, Query()] = None,
    since: Annotated[datetime | None, Query()] = None,
) -> dict[str, Any] | JSONResponse:
    try:
        merchant = None
        if merchant_id or merchant_slug:
            merchant = resolve_merchant(
                session, merchant_id=merchant_id, merchant_slug=merchant_slug
            )
        return case_timeline(session, case_id, merchant, since=since)
    except DomainError as exc:
        return _error(exc)


@router.get("/v1/recovery-cases/{case_id}/decision", response_model=None)
def get_decision(
    case_id: UUID,
    session: DbSession,
    merchant_id: Annotated[UUID | None, Query()] = None,
    merchant_slug: Annotated[str | None, Query()] = None,
) -> dict[str, Any] | JSONResponse:
    try:
        merchant = None
        if merchant_id or merchant_slug:
            merchant = resolve_merchant(
                session, merchant_id=merchant_id, merchant_slug=merchant_slug
            )
        return get_case_decision(session, case_id, merchant)
    except DomainError as exc:
        return _error(exc)


@router.get("/v1/recovery-cases/{case_id}/agent-runs", response_model=None)
def get_agent_runs(
    case_id: UUID,
    session: DbSession,
    merchant_id: Annotated[UUID | None, Query()] = None,
    merchant_slug: Annotated[str | None, Query()] = None,
) -> dict[str, Any] | JSONResponse:
    try:
        merchant = None
        if merchant_id or merchant_slug:
            merchant = resolve_merchant(
                session, merchant_id=merchant_id, merchant_slug=merchant_slug
            )
        return list_agent_runs(session, case_id, merchant)
    except DomainError as exc:
        return _error(exc)


@router.get("/v1/recovery-cases/{case_id}/tool-calls", response_model=None)
def get_tool_calls(
    case_id: UUID,
    session: DbSession,
    merchant_id: Annotated[UUID | None, Query()] = None,
    merchant_slug: Annotated[str | None, Query()] = None,
) -> dict[str, Any] | JSONResponse:
    try:
        merchant = None
        if merchant_id or merchant_slug:
            merchant = resolve_merchant(
                session, merchant_id=merchant_id, merchant_slug=merchant_slug
            )
        return list_tool_calls(session, case_id, merchant)
    except DomainError as exc:
        return _error(exc)


@router.get("/v1/approvals", response_model=None)
def get_approvals(
    session: DbSession,
    merchant_id: Annotated[UUID | None, Query()] = None,
    merchant_slug: Annotated[str | None, Query()] = None,
    status: Annotated[str | None, Query()] = None,
    page: Annotated[int, Query(ge=1)] = 1,
    page_size: Annotated[int, Query(ge=1, le=100)] = 25,
) -> dict[str, Any] | JSONResponse:
    try:
        return list_approvals(
            session,
            merchant_id=merchant_id,
            merchant_slug=merchant_slug,
            status=status,
            page=page,
            page_size=page_size,
        )
    except DomainError as exc:
        return _error(exc)


@router.post("/v1/approvals/{approval_id}/approve", response_model=None)
def approve_from_queue(
    approval_id: UUID,
    body: ApprovalDecisionRequest,
    session: DbSession,
) -> dict[str, Any] | JSONResponse:
    try:
        approval = _load_approval(session, approval_id)
        action_id = approval.recovery_action_id
        if action_id is None:
            raise OperatorError("ACTION_NOT_FOUND", "Approval has no recovery action")
        result = ApprovalService(session).approve_action(
            approval.recovery_case_id,
            action_id,
            actor_id=body.actor_id,
            merchant_id=body.merchant_id or approval.merchant_id,
        )
        return {
            "approval_id": str(approval_id),
            "case_id": str(approval.recovery_case_id),
            "result": result.to_public_dict(),
        }
    except DomainError as exc:
        return _error(exc)


@router.post("/v1/approvals/{approval_id}/reject", response_model=None)
def reject_from_queue(
    approval_id: UUID,
    body: ApprovalDecisionRequest,
    session: DbSession,
) -> dict[str, Any] | JSONResponse:
    try:
        approval = _load_approval(session, approval_id)
        if approval.recovery_action_id is None:
            raise OperatorError("ACTION_NOT_FOUND", "Approval has no recovery action")
        result = ApprovalService(session).reject_action(
            approval.recovery_case_id,
            approval.recovery_action_id,
            actor_id=body.actor_id,
            reason=body.reason,
            merchant_id=body.merchant_id or approval.merchant_id,
        )
        return {"approval_id": str(approval_id), "result": result}
    except DomainError as exc:
        return _error(exc)


@router.post("/v1/approvals/{approval_id}/cancel", response_model=None)
def cancel_from_queue(
    approval_id: UUID,
    body: ApprovalDecisionRequest,
    session: DbSession,
) -> dict[str, Any] | JSONResponse:
    try:
        approval = _load_approval(session, approval_id)
        if approval.recovery_action_id is None:
            raise OperatorError("ACTION_NOT_FOUND", "Approval has no recovery action")
        result = ApprovalService(session).cancel_action(
            approval.recovery_case_id,
            approval.recovery_action_id,
            actor_id=body.actor_id,
            reason=body.reason,
            merchant_id=body.merchant_id or approval.merchant_id,
        )
        return {"approval_id": str(approval_id), "result": result}
    except DomainError as exc:
        return _error(exc)


@router.get("/v1/audit-events", response_model=None)
def get_audit_events(
    session: DbSession,
    merchant_id: Annotated[UUID | None, Query()] = None,
    merchant_slug: Annotated[str | None, Query()] = None,
    case_id: Annotated[UUID | None, Query()] = None,
    event_type: Annotated[str | None, Query()] = None,
    actor_id: Annotated[str | None, Query()] = None,
    since: Annotated[datetime | None, Query()] = None,
    until: Annotated[datetime | None, Query()] = None,
    page: Annotated[int, Query(ge=1)] = 1,
    page_size: Annotated[int, Query(ge=1, le=100)] = 50,
) -> dict[str, Any] | JSONResponse:
    try:
        return list_audit_events(
            session,
            merchant_id=merchant_id,
            merchant_slug=merchant_slug,
            case_id=case_id,
            event_type=event_type,
            actor_id=actor_id,
            since=since,
            until=until,
            page=page,
            page_size=page_size,
        )
    except DomainError as exc:
        return _error(exc)


@router.get("/v1/policy", response_model=None)
def read_policy(
    session: DbSession,
    merchant_id: Annotated[UUID | None, Query()] = None,
    merchant_slug: Annotated[str | None, Query()] = None,
) -> dict[str, Any] | JSONResponse:
    try:
        merchant = resolve_merchant(session, merchant_id=merchant_id, merchant_slug=merchant_slug)
        assert merchant is not None
        return get_policy(session, merchant)
    except DomainError as exc:
        return _error(exc)


@router.patch("/v1/policy", response_model=None)
def patch_policy(body: PolicyUpdateRequest, session: DbSession) -> dict[str, Any] | JSONResponse:
    try:
        merchant = resolve_merchant(
            session, merchant_id=body.merchant_id, merchant_slug=body.merchant_slug
        )
        assert merchant is not None
        return update_policy(session, merchant, body.policy)
    except DomainError as exc:
        return _error(exc)


@router.get("/v1/evaluation/latest", response_model=None)
def get_evaluation_latest(session: DbSession) -> dict[str, Any]:
    return latest_evaluation(session)


@router.get("/v1/evaluation/batch", response_model=None)
def get_evaluation_batch(
    cases: Annotated[int, Query(ge=1, le=1000)] = 100,
    seed: Annotated[int, Query()] = 42,
    revivex_mode: Annotated[str, Query()] = "ml",
    include_multi_seed: Annotated[bool, Query()] = True,
) -> dict[str, Any]:
    return run_batch_evaluation_service(
        n_cases=cases,
        seed=seed,
        revivex_mode=revivex_mode,
        include_multi_seed=include_multi_seed,
    )


@router.get("/v1/system-health", response_model=None)
def get_system_health(request: Request) -> dict[str, Any]:
    settings: Settings = request.app.state.settings
    return system_health_payload(settings, run_readiness_checks(settings))


@router.post("/v1/operator/demo", response_model=None)
def operator_demo(
    body: DemoRequest,
    session: DbSession,
    queue: QueueDep,
    settings: SettingsDep,
) -> dict[str, Any] | JSONResponse:
    try:
        return run_operator_demo(
            session,
            queue,
            settings,
            kind=body.kind,
            merchant_slug=body.merchant_slug,
            seed=body.seed,
            amount=body.amount,
        )
    except DomainError as exc:
        return _error(exc)
    except ValueError as exc:
        payload = error_response("INVALID_DEMO", str(exc))
        return JSONResponse(status_code=400, content=payload.model_dump())


def _load_approval(session: Session, approval_id: UUID) -> Approval:
    approval = session.get(Approval, approval_id)
    if approval is None:
        raise OperatorError("APPROVAL_NOT_FOUND", "Approval was not found")
    if approval.recovery_action_id is None:
        raise OperatorError("ACTION_NOT_FOUND", "Approval has no recovery action")
    return approval
