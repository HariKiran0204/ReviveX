from fastapi import APIRouter, Request
from fastapi.responses import JSONResponse

from recoverai_api.config import Settings
from recoverai_api.health.checks import run_readiness_checks
from recoverai_api.request_context import get_request_id
from recoverai_api.schemas import ApiErrorBody, HealthResponse, ReadyChecks, ReadyResponse

router = APIRouter()


@router.get("/health", response_model=HealthResponse)
def health(request: Request) -> HealthResponse:
    settings: Settings = request.app.state.settings
    return HealthResponse(status="ok", service=settings.service_name)


@router.get("/ready", response_model=ReadyResponse)
def ready(request: Request) -> ReadyResponse | JSONResponse:
    settings: Settings = request.app.state.settings
    results = run_readiness_checks(settings)
    checks = ReadyChecks(
        application=next(r.status for r in results if r.name == "application"),
        database=next(r.status for r in results if r.name == "database"),
        redis=next(r.status for r in results if r.name == "redis"),
    )
    failing = [r for r in results if not r.ok]
    if failing:
        body = ReadyResponse(
            status="not_ready",
            checks=checks,
            error=ApiErrorBody(
                code="SERVICE_NOT_READY",
                message="One or more dependencies are unavailable",
                request_id=get_request_id(),
            ),
        )
        return JSONResponse(status_code=503, content=body.model_dump())
    return ReadyResponse(status="ready", checks=checks)
