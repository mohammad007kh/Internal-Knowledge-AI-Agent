import logging
import secrets
from collections.abc import Awaitable, Callable

from fastapi import Request, Response
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse
from starlette.middleware.base import BaseHTTPMiddleware
from starlette.types import ASGIApp

logger = logging.getLogger(__name__)

MUTATION_METHODS = {"POST", "PUT", "PATCH", "DELETE"}
CSRF_HEADER = "X-CSRF-Token"
CSRF_COOKIE = "csrf_token"

CSRF_EXEMPT_PREFIXES = [
    "/api/v1/auth/login",
    "/api/v1/auth/refresh",
    "/api/v1/auth/setup",
    "/api/v1/auth/password-reset",
    "/api/v1/auth/password-reset/confirm",
    "/health",
    "/docs",
    "/openapi.json",
    "/redoc",
]

SECURITY_HEADERS = {
    "X-Content-Type-Options": "nosniff",
    "X-Frame-Options": "DENY",
    "Referrer-Policy": "strict-origin-when-cross-origin",
    "Content-Security-Policy": (
        "default-src 'self'; "
        "script-src 'self'; "
        "style-src 'self' 'unsafe-inline'; "
        "img-src 'self' data:; "
        "font-src 'self'; "
        "connect-src 'self'"
    ),
    "Permissions-Policy": "camera=(), microphone=(), geolocation=()",
    "Strict-Transport-Security": "max-age=31536000; includeSubDomains",
}


def _is_csrf_exempt(request: Request) -> bool:
    """Check whether the request is exempt from CSRF validation."""
    path = request.url.path
    if request.headers.get("Authorization", "").startswith("Bearer "):
        return True
    for prefix in CSRF_EXEMPT_PREFIXES:
        if path.startswith(prefix):
            return True
    return False


class SecurityHeadersMiddleware(BaseHTTPMiddleware):
    """Middleware that enforces CSRF protection and adds security response headers."""

    def __init__(self, app: ASGIApp, is_https: bool = False) -> None:
        super().__init__(app)
        self._is_https = is_https

    async def dispatch(self, request: Request, call_next: Callable[[Request], Awaitable[Response]]) -> Response:
        # ── CSRF check for state-mutating methods ──
        if request.method in MUTATION_METHODS and not _is_csrf_exempt(request):
            csrf_header = request.headers.get(CSRF_HEADER)
            csrf_cookie = request.cookies.get(CSRF_COOKIE)

            if (
                not csrf_header
                or not csrf_cookie
                or not secrets.compare_digest(csrf_header, csrf_cookie)
            ):
                content = {
                    "type": "about:blank",
                    "title": "Forbidden",
                    "status": 403,
                    "detail": "CSRF token missing or invalid.",
                }
                return JSONResponse(
                    status_code=403,
                    content=content,
                    media_type="application/problem+json",
                )

        try:
            response = await call_next(request)
        except RequestValidationError as exc:
            return JSONResponse(
                status_code=422,
                content={"status": 422, "type": "validation_error", "detail": exc.errors()},
            )

        # ── Security headers ──
        for header, value in SECURITY_HEADERS.items():
            response.headers[header] = value

        # Suppress server fingerprinting
        response.headers["server"] = "webserver"

        # Echo or generate a request correlation ID
        request_id = request.headers.get("X-Request-ID", secrets.token_hex(16))
        response.headers["X-Request-ID"] = request_id

        return response
