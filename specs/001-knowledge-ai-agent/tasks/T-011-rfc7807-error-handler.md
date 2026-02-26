# T-011 — RFC 7807 Error Handler + FastAPI Exception Hierarchy

## Metadata
| Field | Value |
|---|---|
| **ID** | T-011 |
| **Title** | RFC 7807 Error Handler + FastAPI Exception Hierarchy |
| **Phase** | Foundation |
| **Domain** | Backend / Error Handling |
| **Depends on** | T-004 (FastAPI app factory + DI container) |
| **Blocks** | T-025, T-026, T-053, T-064, T-070 (all API routes) |
| **Estimated effort** | 2 h |
| **Priority** | P1 |

---

## Goal

Establish a **single, consistent error contract** for all non-2xx API responses using
[RFC 7807 Problem Details](https://www.rfc-editor.org/rfc/rfc7807).  
Every error the frontend or API client will ever receive must follow the same shape.

---

## Acceptance Criteria

1. `backend/src/core/exceptions.py` defines `AppError` base class and all standard
   sub-classes.
2. An `exception_handler` registered in `create_app()` converts any `AppError` into an
   RFC 7807 JSON body with `Content-Type: application/problem+json`.
3. FastAPI's built-in `RequestValidationError` is also caught and mapped to a 422 RFC
   7807 response.
4. A smoke test confirms that hitting an unknown route returns 404 in RFC 7807 format.
5. No route handler ever calls `raise HTTPException` directly — it raises an `AppError`
   sub-class instead.

---

## Implementation

### 1. Exception hierarchy — `backend/src/core/exceptions.py`

```python
from __future__ import annotations
from typing import Any


class AppError(Exception):
    """Base application error.  All sub-classes map to HTTP problem details."""

    status_code: int = 500
    error_type: str = "internal_error"
    title: str = "Internal Server Error"

    def __init__(
        self,
        detail: str = "An unexpected error occurred.",
        *,
        extra: dict[str, Any] | None = None,
    ) -> None:
        super().__init__(detail)
        self.detail = detail
        self.extra = extra or {}


# ── 4xx ──────────────────────────────────────────────────────────────────────

class BadRequestError(AppError):
    status_code = 400
    error_type = "bad_request"
    title = "Bad Request"


class UnauthorizedError(AppError):
    status_code = 401
    error_type = "unauthorized"
    title = "Unauthorized"


class ForbiddenError(AppError):
    status_code = 403
    error_type = "forbidden"
    title = "Forbidden"


class NotFoundError(AppError):
    status_code = 404
    error_type = "not_found"
    title = "Not Found"


class ConflictError(AppError):
    status_code = 409
    error_type = "conflict"
    title = "Conflict"


class UnprocessableError(AppError):
    """Semantic validation failure (distinct from 422 schema errors)."""
    status_code = 422
    error_type = "unprocessable"
    title = "Unprocessable Entity"


# ── 5xx ──────────────────────────────────────────────────────────────────────

class InternalError(AppError):
    status_code = 500
    error_type = "internal_error"
    title = "Internal Server Error"


class ServiceUnavailableError(AppError):
    status_code = 503
    error_type = "service_unavailable"
    title = "Service Unavailable"
```

---

### 2. Error handler middleware — `backend/src/api/middleware/error_handler.py`

```python
from __future__ import annotations

import logging
from typing import TYPE_CHECKING

from fastapi import Request
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse

from src.core.exceptions import AppError

if TYPE_CHECKING:
    from fastapi import FastAPI

logger = logging.getLogger(__name__)

_PROBLEM_CONTENT_TYPE = "application/problem+json"


def _problem_response(
    *,
    type_: str,
    title: str,
    status: int,
    detail: str,
    instance: str,
    extra: dict | None = None,
) -> JSONResponse:
    body: dict = {
        "type": f"https://knowledge-agent.internal/errors/{type_}",
        "title": title,
        "status": status,
        "detail": detail,
        "instance": instance,
    }
    if extra:
        body["extra"] = extra
    return JSONResponse(
        content=body,
        status_code=status,
        headers={"Content-Type": _PROBLEM_CONTENT_TYPE},
    )


def register_exception_handlers(app: "FastAPI") -> None:
    """Attach all exception handlers to the app.  Call from create_app()."""

    @app.exception_handler(AppError)
    async def app_error_handler(request: Request, exc: AppError) -> JSONResponse:
        # Log 5xx as ERROR, 4xx as WARNING
        if exc.status_code >= 500:
            logger.error("AppError [%s]: %s", exc.error_type, exc.detail, exc_info=exc)
        else:
            logger.warning("AppError [%s]: %s", exc.error_type, exc.detail)

        return _problem_response(
            type_=exc.error_type,
            title=exc.title,
            status=exc.status_code,
            detail=exc.detail,
            instance=str(request.url.path),
            extra=exc.extra or None,
        )

    @app.exception_handler(RequestValidationError)
    async def validation_error_handler(
        request: Request, exc: RequestValidationError
    ) -> JSONResponse:
        logger.warning("Validation error on [%s]: %s", request.url.path, exc.errors())
        return _problem_response(
            type_="validation_error",
            title="Validation Error",
            status=422,
            detail="Request body or parameters failed validation.",
            instance=str(request.url.path),
            extra={"errors": exc.errors()},
        )

    @app.exception_handler(404)
    async def not_found_handler(request: Request, exc: Exception) -> JSONResponse:
        return _problem_response(
            type_="not_found",
            title="Not Found",
            status=404,
            detail=f"The requested resource '{request.url.path}' was not found.",
            instance=str(request.url.path),
        )

    @app.exception_handler(405)
    async def method_not_allowed_handler(
        request: Request, exc: Exception
    ) -> JSONResponse:
        return _problem_response(
            type_="method_not_allowed",
            title="Method Not Allowed",
            status=405,
            detail=f"Method '{request.method}' is not allowed for '{request.url.path}'.",
            instance=str(request.url.path),
        )
```

---

### 3. Wire into `create_app()` — `backend/src/app.py`

Add a single import and call **before** routers are registered and **after** the app
instance is created:

```python
from src.api.middleware.error_handler import register_exception_handlers

def create_app() -> FastAPI:
    app = FastAPI(...)

    # ── Exception handlers (FIRST — before anything else) ──
    register_exception_handlers(app)

    # ── Middleware ──
    app.add_middleware(LoggingMiddleware)   # from T-010
    # … other middleware …

    # ── Routers ──
    # app.include_router(...)

    return app
```

> **Order matters:** FastAPI resolves exception handlers by registration order.
> Register them before adding middleware and routers.

---

### 4. Unit / integration test — `backend/tests/unit/test_error_handler.py`

```python
import pytest
from httpx import AsyncClient


@pytest.mark.asyncio
async def test_unknown_route_returns_404_problem_json(client: AsyncClient) -> None:
    response = await client.get("/api/v1/does-not-exist")
    assert response.status_code == 404
    ct = response.headers["content-type"]
    assert "application/problem+json" in ct
    body = response.json()
    assert body["status"] == 404
    assert "type" in body
    assert "title" in body
    assert "detail" in body
    assert "instance" in body


@pytest.mark.asyncio
async def test_app_error_returns_problem_json(client: AsyncClient) -> None:
    # A test route that raises NotFoundError (added only in test configuration)
    response = await client.get("/api/v1/_test/not-found")
    assert response.status_code == 404
    body = response.json()
    assert body["type"].endswith("not_found")


@pytest.mark.asyncio
async def test_validation_error_returns_422_problem_json(client: AsyncClient) -> None:
    # POST to any endpoint that expects a body; send garbage JSON
    response = await client.post(
        "/api/v1/auth/login",
        json={"not_email": "bad"},
    )
    assert response.status_code == 422
    body = response.json()
    assert body["status"] == 422
    assert "errors" in body.get("extra", {})
```

---

## File Checklist

- [ ] `backend/src/core/exceptions.py`
- [ ] `backend/src/api/middleware/error_handler.py`
- [ ] `backend/src/app.py` — updated `create_app()` to call `register_exception_handlers`
- [ ] `backend/tests/unit/test_error_handler.py`

---

## Project Standards
| Standard | Value |
|---|---|
| Python | 3.12 |
| Backend | FastAPI · SQLAlchemy 2.x · Pydantic v2 · dependency-injector |
| Frontend | Next.js 15 App Router · shadcn/ui · Tailwind CSS |
| State | React Context · TanStack Query · react-hook-form · Zod |
| Database | PostgreSQL 16 + pgvector · HNSW m=16 ef_construction=64 · UUID PKs · soft-delete + audit columns |
| Migrations | Alembic versioned |
| Background | Celery + Redis · Beat replicas=1 STRICT |
| File Storage | MinIO · presigned PUT pattern |
| Auth | JWT 15-min access + 7-day rotating httpOnly refresh cookie · bcrypt · RBAC (admin/user) |
| Encryption | Fernet (connection configs at rest) |
| AI Pipeline | LangGraph 8-node · interrupt() for clarification · SSE streaming |
| Tracing | Langfuse self-hosted · every pipeline run must emit a trace |
| Error Format | RFC 7807 Problem Details — all non-2xx API responses |
| Logging | Structured · INFO level · X-Request-ID correlation |
| Security | CORS strict · CSRF SameSite=Strict httpOnly · CSP moderate · rate-limit IP |
| UI | Dark mode · responsive · WCAG-AA · no animations · Lucide icons · Sonner toasts |
| Naming | snake_case vars/files/tables · PascalCase classes · SCREAMING_SNAKE_CASE constants |
| Commits | Conventional commits · branch pattern: NNN-description |
| Testing | pytest + httpx + Playwright · ≥80% coverage |
| Infrastructure | Docker Compose 9 services: frontend, backend, worker, beat, db, redis, minio, langfuse, langfuse-db |

### Domain Rules
- Source access is per-user per-source; never expose unapproved source data (FR-019)
- Connection strings and file paths MUST NEVER appear in user-facing output, API responses, or AI content (FR-020)
- Celery Beat MUST run with exactly 1 replica — duplicate-schedule prevention is critical
- File size limit is defined in `app_config.yaml`; default 50 MB — NOT in .env, NOT hardcoded (FR-035)
- `bootstrap_admin` executes once on startup only if zero users exist (FR-024)
- Auto-restart is capped at 3 consecutive attempts with increasing wait; stop and alert admins on failure (FR-033)
- All passwords validated via `validate_password_policy()` — min 8 chars, ≥1 uppercase, ≥1 lowercase, ≥1 number (FR-034)
- Invitations are the only path to new accounts — no self-registration endpoint exists (FR-021)
- Every LangGraph pipeline run MUST emit a Langfuse trace with spans per node
