from __future__ import annotations

import logging

from fastapi import FastAPI, Request
from fastapi.exceptions import RequestValidationError
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
from starlette.exceptions import HTTPException as StarletteHTTPException

from recoverai_api.config import Settings, get_settings
from recoverai_api.events.router import router as events_router
from recoverai_api.health.router import router as health_router
from recoverai_api.logging import configure_logging
from recoverai_api.middleware import RequestIdMiddleware
from recoverai_api.operator.router import router as operator_router
from recoverai_api.recovery.router import router as recovery_router
from recoverai_api.schemas import error_response

logger = logging.getLogger(__name__)


def create_app(settings: Settings | None = None) -> FastAPI:
    resolved = settings or get_settings()
    configure_logging(service=resolved.service_name, level=resolved.log_level)

    app = FastAPI(
        title="RecoverAI API",
        description="Autonomous Revenue Recovery Orchestrator — Phase 9 operator UI",
        version="0.1.0",
        docs_url="/docs",
        redoc_url=None,
    )
    app.state.settings = resolved

    app.add_middleware(RequestIdMiddleware)
    app.add_middleware(
        CORSMiddleware,
        allow_origins=resolved.cors_origin_list,
        allow_credentials=True,
        allow_methods=["GET", "POST", "PATCH", "OPTIONS"],
        allow_headers=["*"],
    )
    app.include_router(health_router)
    app.include_router(events_router)
    app.include_router(recovery_router)
    app.include_router(operator_router)

    @app.exception_handler(StarletteHTTPException)
    async def http_exception_handler(request: Request, exc: StarletteHTTPException) -> JSONResponse:
        del request
        payload = error_response("HTTP_ERROR", str(exc.detail))
        return JSONResponse(status_code=exc.status_code, content=payload.model_dump())

    @app.exception_handler(RequestValidationError)
    async def validation_exception_handler(
        request: Request, exc: RequestValidationError
    ) -> JSONResponse:
        del request, exc
        payload = error_response("VALIDATION_ERROR", "Request validation failed")
        return JSONResponse(status_code=422, content=payload.model_dump())

    @app.exception_handler(Exception)
    async def unhandled_exception_handler(request: Request, exc: Exception) -> JSONResponse:
        del request, exc
        logger.exception("unhandled application error")
        payload = error_response("INTERNAL_ERROR", "An unexpected error occurred")
        return JSONResponse(status_code=500, content=payload.model_dump())

    return app


app = create_app()
