"""Correlation id propagation and access logging."""

from __future__ import annotations

import time
import uuid

from starlette.middleware.base import BaseHTTPMiddleware, RequestResponseEndpoint
from starlette.requests import Request
from starlette.responses import Response

from app.core.logging import get_logger, request_id_var

logger = get_logger("app.access")

REQUEST_ID_HEADER = "X-Request-Id"


class RequestContextMiddleware(BaseHTTPMiddleware):
    """Assign a request id, expose it on the response, and log the outcome."""

    async def dispatch(
        self, request: Request, call_next: RequestResponseEndpoint
    ) -> Response:
        incoming = request.headers.get(REQUEST_ID_HEADER, "")
        # An inbound id is only trusted for correlation, never for authorization,
        # so a client-supplied value is accepted but length-capped.
        request_id = incoming[:64] if incoming else str(uuid.uuid4())
        token = request_id_var.set(request_id)
        request.state.request_id = request_id

        started = time.perf_counter()
        # The context variable is reset only after the outcome has been logged,
        # so the access log line carries the same id as the response header.
        try:
            try:
                response = await call_next(request)
            except Exception:
                logger.exception(
                    "request_failed",
                    extra={
                        "method": request.method,
                        "path": _route_path(request),
                        "duration_ms": _elapsed_ms(started),
                    },
                )
                raise

            response.headers[REQUEST_ID_HEADER] = request_id
            logger.info(
                "request_completed",
                extra={
                    "method": request.method,
                    "path": _route_path(request),
                    "status_code": response.status_code,
                    "duration_ms": _elapsed_ms(started),
                },
            )
            return response
        finally:
            request_id_var.reset(token)


def _route_path(request: Request) -> str:
    """The matched route template (``/seniors/{senior_id}/doses``) rather than
    the raw path with resource ids inline — every request to that endpoint
    then aggregates under one log key instead of one per id, and no id leaks
    into logs incidentally. Falls back to the raw path for a genuine 404,
    where no route ever matched.
    """
    route = request.scope.get("route")
    path = getattr(route, "path", None)
    return path if isinstance(path, str) else request.url.path


def _elapsed_ms(started: float) -> float:
    return round((time.perf_counter() - started) * 1000, 2)
