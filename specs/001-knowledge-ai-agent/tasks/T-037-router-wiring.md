# T-037 — Router Wiring and Container Registration (Phase 1 Completion)

## Metadata
| Field | Value |
|---|---|
| **ID** | T-037 |
| **Title** | Router Wiring and DI Container Registration — wire all Phase 1 services into the app |
| **Phase** | 1 — Authentication & User Management |
| **Domain** | Backend / Infrastructure |
| **Depends on** | T-004, T-015, T-019, T-022, T-023, T-024, T-025, T-026, T-027, T-028, T-029 |
| **Blocks** | T-039 |
| **Est. complexity** | S |

### Project Standards
| Standard | Value |
|---|---|
| Python | 3.12 |
| Backend | FastAPI · SQLAlchemy 2.x · Pydantic v2 · dependency-injector |
| DI | dependency-injector IoC container (constructor injection) |
| Error Format | RFC 7807 Problem Details — all non-2xx API responses |
| Logging | Structured · INFO level · X-Request-ID correlation |
| Infrastructure | Docker Compose 9 services |

### Domain Rules
- All services are wired via the IoC container — never instantiate services directly in routes
- bootstrap_admin executes once on startup only if zero users exist (FR-024)

---

## Goal
Finalize the dependency-injector `Container` with all Phase 1 service/repository bindings,
register the `auth` and `users` routers, and ensure the lifespan hook calls `bootstrap_admin`.
This ties together all the individually-built pieces into a running application.

---

## Deliverables

### 1. `app/core/container.py` — complete Phase 1 container
```python
from dependency_injector import containers, providers
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.db import get_db, AsyncSessionLocal
from app.core.config import settings
from app.repositories.user_repository import UserRepository
from app.repositories.invitation_repository import InvitationRepository
from app.services.password_service import PasswordService
from app.services.user_service import UserService
from app.services.auth_service import AuthService
from app.services.email_service import EmailService


class Container(containers.DeclarativeContainer):
    """
    Dependency-injector IoC container.

    All service instances are `Factory` providers so each request gets a
    fresh instance wired with the correct request-scoped DB session.
    """

    # ── Infrastructure ───────────────────────────────────────────────────────
    config = providers.Configuration()

    db_session = providers.Resource(get_db)   # FastAPI overrides this per-request

    # ── Repositories ─────────────────────────────────────────────────────────
    user_repository = providers.Factory(
        UserRepository,
        session=db_session,
    )

    invitation_repository = providers.Factory(
        InvitationRepository,
        session=db_session,
    )

    # ── Services ─────────────────────────────────────────────────────────────
    password_service = providers.Singleton(PasswordService)

    email_service = providers.Singleton(EmailService)

    user_service = providers.Factory(
        UserService,
        user_repo=user_repository,
        invitation_repo=invitation_repository,
        password_svc=password_service,
    )

    auth_service = providers.Factory(
        AuthService,
        user_repo=user_repository,
        password_svc=password_service,
    )
```

---

### 2. `app/core/deps.py` — container-aware provider functions
Add module-level provider functions that FastAPI `Depends()` calls can reference.
These bridge the IoC container to FastAPI's dependency system:

```python
# app/core/deps.py  — additions to T-027 base

from app.core.container import Container

# Container instance — initialised once per process in create_app()
_container: Container | None = None


def get_container() -> Container:
    if _container is None:
        raise RuntimeError("Container not initialised — call init_container() first")
    return _container


def init_container() -> Container:
    global _container
    _container = Container()
    _container.config.from_dict(
        {
            "jwt_secret": settings.JWT_SECRET_KEY,
            "jwt_algorithm": settings.JWT_ALGORITHM,
        }
    )
    return _container


# ── Convenience provider functions used in routers ───────────────────────────

def get_auth_service():
    return get_container().auth_service()


def get_user_service():
    return get_container().user_service()


def get_email_service():
    return get_container().email_service()
```

---

### 3. `app/main.py` — wire routers + lifespan
```python
from contextlib import asynccontextmanager

from fastapi import FastAPI

from app.core.config import settings
from app.core.deps import init_container
from app.core.errors import register_exception_handlers
from app.middleware.logging import RequestLoggingMiddleware
from app.middleware.rate_limit import RateLimitMiddleware
from app.middleware.security import SecurityHeadersMiddleware
from app.api.v1.health import router as health_router
from app.api.v1.auth import router as auth_router
from app.api.v1.users import router as users_router
from app.services.bootstrap import bootstrap_admin


@asynccontextmanager
async def lifespan(app: FastAPI):
    # ── Startup ───────────────────────────────────────────────────────────────
    init_container()
    await bootstrap_admin()
    yield
    # ── Shutdown (add cleanup here as needed) ────────────────────────────────


def create_app() -> FastAPI:
    app = FastAPI(
        title="Internal Knowledge AI Agent",
        version="0.1.0",
        docs_url="/api/docs" if settings.APP_ENV != "production" else None,
        redoc_url=None,
        lifespan=lifespan,
    )

    # ── Middleware (order matters — outermost first) ──────────────────────────
    app.add_middleware(SecurityHeadersMiddleware)
    app.add_middleware(RateLimitMiddleware)
    app.add_middleware(RequestLoggingMiddleware)

    # ── Exception handlers ───────────────────────────────────────────────────
    register_exception_handlers(app)

    # ── Routers ──────────────────────────────────────────────────────────────
    V1_PREFIX = "/api/v1"
    app.include_router(health_router, prefix=V1_PREFIX)
    app.include_router(auth_router, prefix=V1_PREFIX)
    app.include_router(users_router, prefix=V1_PREFIX)

    return app
```

---

### 4. `app/api/v1/users.py` — fix import references to use container
Update the users router (T-028) to import `get_user_service` / `get_email_service` from
`app.core.deps` instead of any ad-hoc stubs:

```python
# app/api/v1/users.py  — corrected imports

from app.core.deps import get_user_service, get_email_service, require_role
from app.models.user import UserRole

# The Depends() calls in T-028 router functions become:
#   user_svc: UserService = Depends(get_user_service)
#   email_svc: EmailService = Depends(get_email_service)
```

---

### 5. `app/api/v1/auth.py` — fix import references
```python
# app/api/v1/auth.py  — corrected imports (T-026 base)

from app.core.deps import get_auth_service, get_email_service, require_authenticated
```

---

## Files to Create / Modify

| Path | Action | Description |
|---|---|---|
| `app/core/container.py` | **Create** | Full Phase 1 IoC container |
| `app/core/deps.py` | **Modify** | Add container init, provider functions |
| `app/main.py` | **Modify** | Wire routers, call bootstrap_admin in lifespan |
| `app/api/v1/users.py` | **Modify** | Use container-provided deps |
| `app/api/v1/auth.py` | **Modify** | Use container-provided deps |

---

## Gate Criteria
- `GET /api/v1/health` returns 200 with full stack running (`make dev`)
- `POST /api/v1/auth/login` with bootstrap admin credentials returns 200
- `GET /api/v1/users` with admin token returns paginated list
- `dependency_injector` container wires without circular dependency errors on startup
- `mypy app/core/container.py app/core/deps.py app/main.py` passes with zero errors
- `bootstrap_admin` runs on first startup, skips gracefully on subsequent startups
