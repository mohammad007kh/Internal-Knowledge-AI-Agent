"""Request-scoped structured logging middleware.

Attaches a unique ``request_id`` to every request context so that all log
lines emitted during request handling carry the same correlation identifier.
The ID is taken from the incoming ``x-request-id`` header when present;
otherwise a fresh UUID-4 is generated.  The value is echoed back in the
``x-request-id`` response header.

Two structured log events are emitted per request:

* ``request.start`` – when the request is first received
* ``request.end``   – after the response is fully sent, with the HTTP status
  code and elapsed wall-clock time in milliseconds
"""
from __future__ import annotations

import time
import uuid
from typing import Callable

import structlog
from starlette.middleware.base import BaseHTTPMiddleware
from starlette.requests import Request
from starlette.responses import Response

log = structlog.get_logger(__name__)


class RequestIDMiddleware(BaseHTTPMiddleware):
    """ASGI middleware that binds a ``request_id`` to the structlog context."""

    async def dispatch(self, request: Request, call_next: Callable) -> Response:
        request_id = request.headers.get("x-request-id") or str(uuid.uuid4())

        structlog.contextvars.clear_contextvars()
        structlog.contextvars.bind_contextvars(request_id=request_id)

        start = time.perf_counter()
        log.info("request.start", method=request.method, path=request.url.path)

        response = await call_next(request)

        elapsed_ms = round((time.perf_counter() - start) * 1000, 1)
        log.info(
            "request.end",
            method=request.method,
            path=request.url.path,
            status_code=response.status_code,
            elapsed_ms=elapsed_ms,
        )

        response.headers["x-request-id"] = request_id
        return response
