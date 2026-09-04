from collections.abc import Awaitable, Callable
from uuid import uuid4

from starlette.middleware.base import BaseHTTPMiddleware
from starlette.requests import Request
from starlette.responses import Response

from recoverai_api.request_context import set_request_id

HEADER = "X-Request-ID"


class RequestIdMiddleware(BaseHTTPMiddleware):
    async def dispatch(
        self, request: Request, call_next: Callable[[Request], Awaitable[Response]]
    ) -> Response:
        incoming = request.headers.get(HEADER)
        request_id = incoming.strip() if incoming and incoming.strip() else str(uuid4())
        set_request_id(request_id)
        response = await call_next(request)
        response.headers[HEADER] = request_id
        return response
