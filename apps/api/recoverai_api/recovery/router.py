from __future__ import annotations

from typing import Annotated, Any
from uuid import UUID

from fastapi import APIRouter, Depends
from pydantic import BaseModel, Field
from sqlalchemy.orm import Session
from starlette.responses import JSONResponse

from recoverai_api.deps import get_db_session
from recoverai_api.schemas import error_response
from recoverai_domain.agents.service import RecoveryAgentService
from recoverai_domain.errors import DomainError, IdempotencyConflictError, InvalidTransitionError
from recoverai_domain.optimizer.service import RecoveryOptimizer
from recoverai_domain.processor import (
    RecoveryCaseProcessor,
    process_recovery_case,
    verify_recovery_case,
)
from recoverai_domain.tools.approvals import ApprovalService
from recoverai_domain.tools.execution import ToolExecutionService
from recoverai_domain.transitions import lock_recovery_case

router = APIRouter()
DbSession = Annotated[Session, Depends(get_db_session)]


class EvaluateActionRequest(BaseModel):
    action: str
    merchant_id: UUID | None = None
    input: dict[str, Any] = Field(default_factory=dict)


class ExecuteActionRequest(BaseModel):
    idempotency_key: str
    tool_name: str | None = None
    action: str | None = None
    merchant_id: UUID | None = None
    input: dict[str, Any] = Field(default_factory=dict)
    actor_id: str | None = "demo-operator"


class DecisionRequest(BaseModel):
    merchant_id: UUID | None = None
    reason: str | None = None
    actor_id: str | None = "demo-operator"


class AgentRunRequest(BaseModel):
    merchant_id: UUID | None = None
    execute: bool = False


class AnalystRequest(BaseModel):
    question: str


def _error(exc: DomainError) -> JSONResponse:
    status = 400
    if isinstance(exc, InvalidTransitionError) or isinstance(exc, IdempotencyConflictError):
        status = 409
    if exc.code in {"RECOVERY_CASE_NOT_FOUND", "ACTION_NOT_FOUND", "APPROVAL_NOT_FOUND"}:
        status = 404
    if exc.code == "MERCHANT_MISMATCH":
        status = 403
    payload = error_response(exc.code, exc.message)
    return JSONResponse(status_code=status, content=payload.model_dump())


def _prepare_policy_check(session: Session, case_id: UUID) -> None:
    case = lock_recovery_case(session, case_id)
    RecoveryCaseProcessor(session).walk_to_policy_check(case)
    session.flush()


@router.post("/v1/recovery-cases/{case_id}/process", response_model=None)
def process_case(case_id: UUID, session: DbSession) -> dict[str, object] | JSONResponse:
    try:
        result = process_recovery_case(session, case_id)
        return {"case_id": str(case_id), "result": result}
    except DomainError as exc:
        return _error(exc)


@router.post("/v1/recovery-cases/{case_id}/verify", response_model=None)
def verify_case(case_id: UUID, session: DbSession) -> dict[str, object] | JSONResponse:
    try:
        result = verify_recovery_case(session, case_id)
        return {"case_id": str(case_id), "result": result}
    except DomainError as exc:
        return _error(exc)


@router.post("/v1/recovery-cases/{case_id}/optimize", response_model=None)
def optimize_case(case_id: UUID, session: DbSession) -> dict[str, object] | JSONResponse:
    try:
        result = RecoveryOptimizer().optimize_case(session, case_id)
        return {"case_id": str(case_id), "result": result.to_public_dict()}
    except DomainError as exc:
        return _error(exc)


@router.post("/v1/recovery-cases/{case_id}/agent-run", response_model=None)
def run_agents(
    case_id: UUID, body: AgentRunRequest, session: DbSession
) -> dict[str, object] | JSONResponse:
    try:
        result = RecoveryAgentService(session).run_case(
            case_id,
            body.merchant_id,
            execute=body.execute,
        )
        return {"case_id": str(case_id), "result": result.to_public_dict()}
    except DomainError as exc:
        return _error(exc)


@router.post("/v1/merchants/{merchant_id}/analyst", response_model=None)
def ask_analyst(
    merchant_id: UUID, body: AnalystRequest, session: DbSession
) -> dict[str, object] | JSONResponse:
    try:
        result = RecoveryAgentService(session).ask_analyst(merchant_id, body.question)
        return {"merchant_id": str(merchant_id), "result": result.model_dump(mode="json")}
    except DomainError as exc:
        return _error(exc)


@router.post("/v1/recovery-cases/{case_id}/actions/evaluate", response_model=None)
def evaluate_action(
    case_id: UUID, body: EvaluateActionRequest, session: DbSession
) -> dict[str, object] | JSONResponse:
    try:
        _prepare_policy_check(session, case_id)
        result = ToolExecutionService(session).evaluate(
            case_id,
            body.action,
            payload=body.input,
            merchant_id=body.merchant_id,
            actor_id="demo-operator",
        )
        return {"case_id": str(case_id), "result": result}
    except DomainError as exc:
        return _error(exc)


@router.post("/v1/recovery-cases/{case_id}/actions/{action_id}/approve", response_model=None)
def approve_action(
    case_id: UUID, action_id: UUID, body: DecisionRequest, session: DbSession
) -> dict[str, object] | JSONResponse:
    try:
        result = ApprovalService(session).approve_action(
            case_id,
            action_id,
            actor_id=body.actor_id,
            merchant_id=body.merchant_id,
        )
        return {"case_id": str(case_id), "result": result.to_public_dict()}
    except DomainError as exc:
        return _error(exc)


@router.post("/v1/recovery-cases/{case_id}/actions/{action_id}/reject", response_model=None)
def reject_action(
    case_id: UUID, action_id: UUID, body: DecisionRequest, session: DbSession
) -> dict[str, object] | JSONResponse:
    try:
        result = ApprovalService(session).reject_action(
            case_id,
            action_id,
            actor_id=body.actor_id,
            reason=body.reason,
            merchant_id=body.merchant_id,
        )
        return {"case_id": str(case_id), "result": result}
    except DomainError as exc:
        return _error(exc)


@router.post("/v1/recovery-cases/{case_id}/actions/{action_id}/cancel", response_model=None)
def cancel_action(
    case_id: UUID, action_id: UUID, body: DecisionRequest, session: DbSession
) -> dict[str, object] | JSONResponse:
    try:
        result = ApprovalService(session).cancel_action(
            case_id,
            action_id,
            actor_id=body.actor_id,
            reason=body.reason,
            merchant_id=body.merchant_id,
        )
        return {"case_id": str(case_id), "result": result}
    except DomainError as exc:
        return _error(exc)


@router.post("/v1/recovery-cases/{case_id}/actions/{action_id}/execute", response_model=None)
@router.post("/v1/recovery-cases/{case_id}/actions/execute", response_model=None)
def execute_action(
    case_id: UUID,
    body: ExecuteActionRequest,
    session: DbSession,
    action_id: UUID | None = None,
) -> dict[str, object] | JSONResponse:
    try:
        _prepare_policy_check(session, case_id)
        result = ToolExecutionService(session).execute(
            case_id,
            tool_name=body.tool_name,
            action=body.action,
            payload=body.input,
            idempotency_key=body.idempotency_key,
            merchant_id=body.merchant_id,
            actor_id=body.actor_id,
            existing_action_id=action_id,
        )
        return {"case_id": str(case_id), "result": result.to_public_dict()}
    except DomainError as exc:
        return _error(exc)
