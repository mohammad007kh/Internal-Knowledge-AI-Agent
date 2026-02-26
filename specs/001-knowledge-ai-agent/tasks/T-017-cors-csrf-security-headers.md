# T-017 — CORS + CSRF + Security Headers Middleware

---
id: T-017
title: CORS, CSRF Protection, and Security Response Headers
status: Not Started
created: 2026-02-26
phase: Phase 0 — Foundation
user_story: cross
requirements: []
priority: P1
depends_on: [T-015]
blocks: [T-026, T-038]
estimated_effort: 1.5h
---

## Goal

Configure the three security layers that must be active before any authenticated endpoint is exposed: (1) CORS restricted to the frontend origin, (2) CSRF protection via `SameSite=Strict` httpOnly cookie strategy + custom header check, and (3) a set of hardening response headers (`X-Content-Type-Options`, `X-Frame-Options`, `Strict-Transport-Security`, `Referrer-Policy`, `Content-Security-Policy`).

---

## Acceptance Criteria

- [ ] `CORSMiddleware` only allows origins matching `settings.FRONTEND_URL` (no wildcard in production)
- [ ] Allowed methods: `GET, POST, PUT, PATCH, DELETE, OPTIONS`
- [ ] Allowed headers: `Content-Type, Authorization, X-Request-ID, X-CSRF-Token`
- [ ] `allow_credentials=True` — required for the httpOnly refresh cookie
- [ ] Every response includes:
  - `X-Content-Type-Options: nosniff`
  - `X-Frame-Options: DENY`
  - `Referrer-Policy: strict-origin-when-cross-origin`
  - `Strict-Transport-Security: max-age=31536000; includeSubDomains` (HTTPS only)
  - `Content-Security-Policy: default-src 'self'; script-src 'self'; style-src 'self' 'unsafe-inline'; img-src 'self' data:; font-src 'self'; connect-src 'self'`
- [ ] State-mutating requests (`POST`, `PUT`, `PATCH`, `DELETE`) from browser clients must include `X-CSRF-Token: <value>` header that matches the CSRF token embedded in the HttpOnly cookie or a double-submit cookie value
- [ ] Requests without a valid CSRF token return `403 Forbidden` (RFC 7807)
- [ ] Exemptions: requests using `Authorization: Bearer ...` header (API clients, not browsers) skip CSRF check
- [ ] Unit tests: CORS preflight, correct headers present, CSRF pass/fail, Bearer exemption

---

## Files to Create / Update

| Path | Action |
|------|---------|
| `backend/src/middleware/security_headers.py` | Create — security headers + CSRF |
| `backend/src/main.py` | Update — register CORS + security headers middleware |
| `backend/tests/unit/test_security_headers.py` | Create |

---

## Implementation

### CSRF Strategy

This project uses a **double-submit header check** (lightweight CSRF protection compatible with JWT/cookie hybrid auth):

1. On login, backend sets **two** cookies:
   - `refresh_token` — httpOnly, SameSite=Strict (not readable by JS)
   - `csrf_token` — httpOnly=False, SameSite=Strict (readable by JS)
2. Browser JS reads `csrf_token` cookie and sends it as `X-CSRF-Token` header
3. Backend verifies `X-CSRF-Token` header == `csrf_token` cookie value
4. API-key / Bearer token clients bypass CSRF (they don't use cookie auth)

### `backend/src/middleware/security_headers.py`

```python
import secrets
import logging
from typing import Callable
from starlette.middleware.base import BaseHTTPMiddleware
from starlette.types import ASGIApp
from fastapi import Request, Response
from fastapi.responses import JSONResponse

logger = logging.getLogger(__name__)

MUTATION_METHODS = {"POST", "PUT", "PATCH", "DELETE"}
CSRF_HEADER = "X-CSRF-Token"
CSRF_COOKIE = "csrf_token"

# Routes that always bypass CSRF (pre-authentication)
CSRF_EXEMPT_PREFIXES = [
    "/api/v1/auth/login",
    "/api/v1/auth/refresh",
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
}


def _is_csrf_exempt(request: Request) -> bool:
    path = request.url.path
    # Bearer token clients are exempt (API/CLI access)
    if request.headers.get("Authorization", "").startswith("Bearer "):
        return True
    for prefix in CSRF_EXEMPT_PREFIXES:
        if path.startswith(prefix):
            return True
    return False


class SecurityHeadersMiddleware(BaseHTTPMiddleware):
    def __init__(self, app: ASGIApp, is_https: bool = False):
        super().__init__(app)
        self._is_https = is_https

    async def dispatch(self, request: Request, call_next: Callable) -> Response:
        # CSRF check for state-mutating browser requests
        if request.method in MUTATION_METHODS and not _is_csrf_exempt(request):
            csrf_header = request.headers.get(CSRF_HEADER)
            csrf_cookie = request.cookies.get(CSRF_COOKIE)

            if not csrf_header or not csrf_cookie or not secrets.compare_digest(
                csrf_header, csrf_cookie
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

        response = await call_next(request)

        # Inject security headers
        for header, value in SECURITY_HEADERS.items():
            response.headers[header] = value

        if self._is_https:
            response.headers["Strict-Transport-Security"] = (
                "max-age=31536000; includeSubDomains"
            )

        return response
```

### Wire into `backend/src/main.py`

```python
from fastapi.middleware.cors import CORSMiddleware
from src.middleware.security_headers import SecurityHeadersMiddleware
from src.core.config import settings

def create_app() -> FastAPI:
    app = FastAPI(...)

    # CORS must be registered BEFORE other middleware
    app.add_middleware(
        CORSMiddleware,
        allow_origins=[settings.FRONTEND_URL],
        allow_credentials=True,
        allow_methods=["GET", "POST", "PUT", "PATCH", "DELETE", "OPTIONS"],
        allow_headers=["Content-Type", "Authorization", "X-Request-ID", "X-CSRF-Token"],
        expose_headers=["X-Request-ID", "X-RateLimit-Limit", "X-RateLimit-Remaining"],
    )

    # Security headers + CSRF
    app.add_middleware(
        SecurityHeadersMiddleware,
        is_https=settings.ENVIRONMENT == "production",
    )
    # ... rest of middleware
```

### CSRF Token Set on Login

In the auth service (T-025), when setting the refresh cookie, also set:

```python
import secrets

def set_csrf_cookie(response: Response) -> str:
    """Generate and set a CSRF token cookie readable by JS."""
    token = secrets.token_urlsafe(32)
    response.set_cookie(
        key="csrf_token",
        value=token,
        httponly=False,       # JS must read this
        samesite="strict",
        secure=True,          # HTTPS only in production
        max_age=7 * 24 * 3600,
    )
    return token
```

---

## Tests

### `backend/tests/unit/test_security_headers.py`

```python
import pytest
from httpx import AsyncClient
from src.main import create_app

@pytest.mark.asyncio
async def test_security_headers_present():
    app = create_app()
    async with AsyncClient(app=app, base_url="http://test") as client:
        resp = await client.get("/health")
        assert resp.headers["x-frame-options"] == "DENY"
        assert resp.headers["x-content-type-options"] == "nosniff"
        assert "default-src 'self'" in resp.headers["content-security-policy"]

@pytest.mark.asyncio
async def test_csrf_check_blocks_post_without_token():
    app = create_app()
    async with AsyncClient(app=app, base_url="http://test") as client:
        resp = await client.post("/api/v1/users/", json={"email": "x@x.com"})
        assert resp.status_code == 403
        assert resp.headers["content-type"] == "application/problem+json"

@pytest.mark.asyncio
async def test_csrf_check_bypassed_for_bearer():
    app = create_app()
    async with AsyncClient(app=app, base_url="http://test") as client:
        # With Bearer token, CSRF check is skipped (will fail with 401/422 for other reasons, not 403)
        resp = await client.post(
            "/api/v1/users/",
            json={"email": "x@x.com"},
            headers={"Authorization": "Bearer sometoken"},
        )
        assert resp.status_code != 403
```

---

### Project Standards
| Standard | Value |
|---|---|
| Python | 3.12 |
| Backend | FastAPI · SQLAlchemy 2.x · Pydantic v2 · dependency-injector |
| Security | CORS strict · CSRF SameSite=Strict httpOnly · CSP moderate · rate-limit IP |
| Error Format | RFC 7807 Problem Details — all non-2xx API responses |
| Auth | JWT 15-min access + 7-day rotating httpOnly refresh cookie · bcrypt · RBAC (admin/user) |

### Domain Rules
- `allow_origins` MUST be `[settings.FRONTEND_URL]` — never `["*"]` in any environment
- CSRF exemption for Bearer-token clients is intentional — never remove it (breaks API integrations)
- `allow_credentials=True` is required for the httpOnly refresh cookie — do not remove
