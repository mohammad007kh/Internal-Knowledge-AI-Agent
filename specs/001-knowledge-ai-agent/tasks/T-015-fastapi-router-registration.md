---
id: T-015
title: FastAPI v1 Router Registration Pattern + Main.py Wiring
status: Done
created: 2026-02-25
phase: Phase 0 â€” Foundation
user_story: cross
requirements: []
priority: P1
depends_on: [T-004, T-010, T-011]
blocks: [T-025, T-026, T-053, T-064, T-070, T-083, T-086]
---

## Goal

Establish the canonical router-registration pattern so every new API route added in subsequent tasks follows the same structure. The `main.py` / `create_app()` function must be the single place where all routers are registered. This task documents the pattern and creates the v1 router aggregation module.

---

## Acceptance Criteria

- [ ] `backend/src/api/v1/router.py` exports a single `api_v1_router` that sub-includes all v1 sub-routers
- [ ] `create_app()` calls `app.include_router(api_v1_router, prefix="/api/v1")` exactly once
- [ ] The health check at `/health` (no prefix) is registered separately from v1 routes
- [ ] All routes automatically inherit the `X-Request-ID` response header (from T-010 middleware)
- [ ] All non-2xx responses are RFC 7807 (from T-011 handlers)
- [ ] OpenAPI schema is accessible at `/docs` and `/openapi.json`
- [ ] A stub `GET /api/v1/ping` route confirms the pattern works end-to-end

---

## Files to Create / Update

| Path | Action |
|------|--------|
| `backend/src/api/v1/router.py` | Create â€” aggregates all v1 sub-routers |
| `backend/src/api/v1/ping.py` | Create â€” stub endpoint for pattern verification |
| `backend/src/main.py` | Update â€” include api_v1_router |

---

## Implementation

### `backend/src/api/v1/router.py`

```python
from fastapi import APIRouter
from src.api.v1.ping import router as ping_router
# Future routers imported here (auth, users, sources, chat, etc.)
# from src.api.v1.auth import router as auth_router    # T-025
# from src.api.v1.users import router as users_router  # T-026
# from src.api.v1.sources import router as sources_router  # T-053
# from src.api.v1.chat import router as chat_router    # T-070

api_v1_router = APIRouter()
api_v1_router.include_router(ping_router, prefix="/ping", tags=["system"])
# api_v1_router.include_router(auth_router, prefix="/auth", tags=["auth"])
# api_v1_router.include_router(users_router, prefix="/users", tags=["users"])
# api_v1_router.include_router(sources_router, prefix="/sources", tags=["sources"])
# api_v1_router.include_router(chat_router, prefix="/chat", tags=["chat"])
```

### `backend/src/api/v1/ping.py`

```python
from fastapi import APIRouter
router = APIRouter()

@router.get("")
async def ping():
    """Verification endpoint â€” confirms v1 router is wired."""
    return {"ping": "pong", "api_version": "v1"}
```

### `backend/src/main.py` (updated create_app)

```python
from contextlib import asynccontextmanager
from fastapi import FastAPI
from src.core.container import container
from src.core.logging import configure_logging
from src.api.middleware.logging_middleware import LoggingMiddleware
from src.api.middleware.error_handler import register_exception_handlers
from src.api.v1.health import router as health_router
from src.api.v1.router import api_v1_router

@asynccontextmanager
async def lifespan(app: FastAPI):
    container.wire(packages=["src.api"])
    # Run migrations (idempotent)
    from alembic.config import Config
    from alembic import command
    cfg = Config("alembic.ini")
    command.upgrade(cfg, "head")
    yield

def create_app() -> FastAPI:
    configure_logging()

    app = FastAPI(
        title="Knowledge AI Agent",
        version="0.1.0",
        lifespan=lifespan,
        docs_url="/docs",
        openapi_url="/openapi.json",
    )

    # â”€â”€ Exception handlers (before middleware + routers) â”€â”€
    register_exception_handlers(app)

    # â”€â”€ Middleware â”€â”€
    app.add_middleware(LoggingMiddleware)

    # â”€â”€ Routes â”€â”€
    app.include_router(health_router, tags=["health"])
    app.include_router(api_v1_router, prefix="/api/v1")

    return app

app = create_app()
```

---

## Router Registration Rule for All Future Tasks

When adding a new router (e.g. `auth`, `users`, `sources`, `chat`):
1. Create `backend/src/api/v1/<domain>.py` with `router = APIRouter()`
2. Import it in `backend/src/api/v1/router.py`
3. Add `api_v1_router.include_router(router, prefix="/<domain>", tags=["<domain>"])`
4. NEVER call `app.include_router(...)` from individual domain files

---

## Verification

```bash
curl -s http://localhost:8000/api/v1/ping | python -m json.tool
# Expected: {"ping": "pong", "api_version": "v1"}

curl -s http://localhost:8000/openapi.json | python -m json.tool | grep '"ping"'
# Expected: route appears in schema

curl -s http://localhost:8000/api/v1/does-not-exist | python -m json.tool
# Expected: RFC 7807 404 response with Content-Type: application/problem+json
```

---

## ðŸ“ Completion Log

- [ ] Code implemented
- [ ] `GET /api/v1/ping` â†’ `{"ping":"pong"}`
- [ ] `GET /api/v1/unknown` â†’ RFC 7807 404
- [ ] Linter passed
- [ ] All future router stubs added as comments to `router.py`
