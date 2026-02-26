---
id: T-004
title: FastAPI Application Factory, Dependency Injection Container, and Core Settings
status: Not Started
created: 2026-02-25
phase: Phase 0 — Foundation
user_story: cross
requirements: []
---

## 📋 Embedded Context (READ THIS FIRST)

### Project Standards
| Standard | Value |
|---|---|
| Python | 3.12 |
| Backend | FastAPI · SQLAlchemy 2.x · Pydantic v2 · dependency-injector |
| DI | dependency-injector IoC container (constructor injection) |
| Error Format | RFC 7807 Problem Details — all non-2xx API responses |
| Logging | Structured · INFO level · X-Request-ID correlation |
| Config | Pydantic Settings reads from .env + app_config.yaml |

### Domain Rules
- All services are wired via the IoC container — never instantiate services directly in routes
- `app_config.yaml` holds `file_upload.max_size_bytes`; Settings reads it via `pydantic_settings`
- `/health` endpoint must respond before any database is needed (liveness check)

### Feature Summary
FastAPI application factory with lifespan context manager, dependency-injector IoC container, Pydantic Settings for env/config, and the `/health` liveness endpoint.

### Gate Criteria
- `GET /health` returns `{"status": "ok", "version": "0.1.0"}` with HTTP 200
- Container wires without errors on startup
- `mypy src/core/` passes with strict mode
- `ruff check src/core/` returns zero errors

---

## 🎯 Objective

Create the FastAPI `create_app()` factory, wire the dependency-injector container with all service/repository bindings, define Pydantic Settings that read from both `.env` and `app_config.yaml`, and expose the `/health` liveness endpoint.

---

## 🛠️ Implementation Details

### Files to Create

| Path | Purpose |
|------|---------|
| `backend/src/core/config.py` | Pydantic Settings class: reads .env + app_config.yaml |
| `backend/src/core/container.py` | dependency-injector IoC container with all service bindings |
| `backend/src/main.py` | FastAPI app factory (`create_app()`), lifespan, router registration |
| `backend/src/api/v1/__init__.py` | v1 router package init |
| `backend/src/api/v1/health.py` | `GET /health` endpoint |

### Files to Update
- `backend/src/core/__init__.py` — export `settings`, `container`
- `backend/src/api/__init__.py` — export `create_api_router()`

### Code / Logic Requirements

**`backend/src/core/config.py`:**
```python
from pydantic_settings import BaseSettings, SettingsConfigDict
import yaml, os

class Settings(BaseSettings):
    # Database
    DATABASE_URL: str
    REDIS_URL: str = "redis://localhost:6379/0"
    # Auth
    JWT_SECRET_KEY: str
    JWT_REFRESH_SECRET_KEY: str
    JWT_ALGORITHM: str = "HS256"
    ACCESS_TOKEN_EXPIRE_MINUTES: int = 15
    REFRESH_TOKEN_EXPIRE_DAYS: int = 7
    # MinIO
    MINIO_ENDPOINT: str
    MINIO_ACCESS_KEY: str
    MINIO_SECRET_KEY: str
    MINIO_BUCKET: str = "knowledge-agent"
    MINIO_SECURE: bool = False
    # Langfuse
    LANGFUSE_SECRET_KEY: str = ""
    LANGFUSE_PUBLIC_KEY: str = ""
    LANGFUSE_HOST: str = "http://localhost:3001"
    # Bootstrap admin
    BOOTSTRAP_ADMIN_EMAIL: str
    BOOTSTRAP_ADMIN_PASSWORD: str
    # Encryption
    ENCRYPTION_KEY: str
    # App config (loaded from YAML)
    upload_max_size_bytes: int = 52428800
    upload_supported_formats: list[str] = ["pdf","docx","xlsx","csv","txt","md"]

    model_config = SettingsConfigDict(env_file=".env", case_sensitive=True)

    def model_post_init(self, __context):
        config_path = os.environ.get("APP_CONFIG_PATH", "app_config.yaml")
        if os.path.exists(config_path):
            with open(config_path) as f:
                data = yaml.safe_load(f)
            fu = data.get("file_upload", {})
            if "max_size_bytes" in fu:
                object.__setattr__(self, "upload_max_size_bytes", fu["max_size_bytes"])
            if "supported_formats" in fu:
                object.__setattr__(self, "upload_supported_formats", fu["supported_formats"])

settings = Settings()
```

**`backend/src/core/container.py`:**
```python
from dependency_injector import containers, providers
from src.core.config import settings
from src.core.database import AsyncSessionLocal

class Container(containers.DeclarativeContainer):
    wiring_config = containers.WiringConfiguration(packages=["src.api"])
    config = providers.Object(settings)
    db_session_factory = providers.Factory(lambda: AsyncSessionLocal)
    # Services added in later tasks (auth_service, user_service, etc.)

container = Container()
```

**`backend/src/main.py`:**
```python
from contextlib import asynccontextmanager
from fastapi import FastAPI
from src.core.container import container
from src.api.v1.health import router as health_router

@asynccontextmanager
async def lifespan(app: FastAPI):
    # Startup: wire container, run migrations, bootstrap admin
    container.wire(packages=["src.api"])
    yield
    # Shutdown: close DB connections

def create_app() -> FastAPI:
    app = FastAPI(title="Knowledge AI Agent", version="0.1.0", lifespan=lifespan)
    app.include_router(health_router, tags=["health"])
    return app

app = create_app()
```

**`backend/src/api/v1/health.py`:**
```python
from fastapi import APIRouter
router = APIRouter()

@router.get("/health")
async def health_check():
    return {"status": "ok", "version": "0.1.0"}
```

---

## 🔌 Wiring Checklist

- [ ] `settings` singleton exported from `src.core.config`
- [ ] `container` singleton exported from `src.core.container`
- [ ] `app = create_app()` in `src/main.py` — entry point for uvicorn
- [ ] `/health` route registered before any database dependency
- [ ] `lifespan` context manager runs `container.wire()` on startup

---

## ✅ Verification

```bash
# Start backend in dev mode
cd backend && uvicorn src.main:app --reload &
sleep 3

# Verify health endpoint
curl -s http://localhost:8000/health | python -m json.tool
# Expected: {"status": "ok", "version": "0.1.0"}

# Verify OpenAPI schema generates without errors
curl -s http://localhost:8000/openapi.json | python -m json.tool | grep '"title"'
# Expected: "title": "Knowledge AI Agent"

# Type check
cd backend && mypy src/core/ --strict
# Expected: Success: no issues found
```

**Success Criteria:**
- `GET /health` → HTTP 200 with `{"status": "ok", "version": "0.1.0"}`
- `mypy src/core/` → zero errors
- `ruff check src/core/` → zero errors
- Container instantiates without import errors

---

## 📝 Completion Log

- [ ] Code implemented
- [ ] Tests passed
- [ ] Linter passed
- [ ] Wiring verified
- [ ] Integration verification passed
