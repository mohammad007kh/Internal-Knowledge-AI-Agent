import time
import uuid
from collections.abc import Awaitable, Callable

import structlog
from starlette.middleware.base import BaseHTTPMiddleware
from starlette.requests import Request
from starlette.responses import Response
from structlog.contextvars import bind_contextvars, clear_contextvars

logger = structlog.get_logger(__name__)


class LoggingMiddleware(BaseHTTPMiddleware):
    async def dispatch(self, request: Request, call_next: Callable[[Request], Awaitable[Response]]) -> Response:
        clear_contextvars()
        request_id = request.headers.get("X-Request-ID") or str(uuid.uuid4())
        bind_contextvars(request_id=request_id)

        start = time.perf_counter()
        response = None
        try:
            response = await call_next(request)
        except Exception:
            logger.exception("unhandled_exception", method=request.method, path=request.url.path)
            raise
        finally:
            duration_ms = (time.perf_counter() - start) * 1000
            logger.info(
                "request_completed",
                method=request.method,
                path=request.url.path,
                status_code=getattr(response, "status_code", 500),
                duration_ms=round(duration_ms, 2),
            )

        response.headers["X-Request-ID"] = request_id
        return response
