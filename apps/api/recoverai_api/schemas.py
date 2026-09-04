from __future__ import annotations

from pydantic import BaseModel, Field

from recoverai_api.request_context import get_request_id


class ApiErrorBody(BaseModel):
    code: str
    message: str
    request_id: str | None = None


class ApiErrorResponse(BaseModel):
    error: ApiErrorBody


def error_response(code: str, message: str) -> ApiErrorResponse:
    return ApiErrorResponse(
        error=ApiErrorBody(code=code, message=message, request_id=get_request_id())
    )


class HealthResponse(BaseModel):
    status: str = Field(examples=["ok"])
    service: str = Field(examples=["recoverai-api"])


class ReadyChecks(BaseModel):
    application: str
    database: str
    redis: str


class ReadyResponse(BaseModel):
    status: str = Field(examples=["ready"])
    checks: ReadyChecks
    error: ApiErrorBody | None = None
