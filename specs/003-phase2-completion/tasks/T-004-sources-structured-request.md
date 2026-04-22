# T-004: Refactor POST /sources to Accept Structured Body

| Field | Value |
|---|---|
| **Status** | Pending |
| **Created** | 2026-04-21 |
| **Feature** | 003-phase2-completion |
| **Branch** | `003-phase2-completion` |
| **User Story** | US-1 |
| **Requirements** | FR-001 (wizard), FR-002 (source types), FR-007 (sync/retrieval config) |
| **Priority** | P0 |

---

## Embedded Context

This task file is self-contained. Read only this file, `specs/003-phase2-completion/index.md`, and `specs/003-phase2-completion/traceability.md` during implementation (Context Pinning).

### Registry Standards (MUST follow)

| Key | Value |
|-----|-------|
| `architecture.pattern` | modular_monolith |
| `architecture.layers` | clean |
| `code_patterns.data_access` | repository |
| `code_patterns.dependency_injection` | container (dependency-injector IoC) |
| `code_patterns.error_handling` | exceptions |
| `code_patterns.validation_approach` | schema (Pydantic) |
| `database.tenancy_model` | single_tenant |
| `database.primary_key_type` | uuid |
| `database.migration_strategy` | versioned (Alembic) |
| `database.naming_tables` | snake_case |
| `database.naming_columns` | snake_case |
| `conventions.files` | snake_case (Python), kebab-case (Next.js) |
| `conventions.variables` | snake_case (Python) |
| `conventions.classes` | PascalCase |
| `api.versioning` | url (/api/v1/) |
| `api.error_format` | rfc7807 |
| `backend.language` | python |
| `backend.runtime_version` | python:3.12 |
| `backend.framework` | fastapi |
| `backend.orm` | sqlalchemy (async) |
| `backend.auth_method` | jwt |
| `backend.auth_pattern` | rbac (admin/user) |
| `backend.job_queue` | celery + redis |
| `backend.sse_pattern` | fastapi_streaming_response |
| `testing.unit_framework` | pytest |
| `testing.integration_framework` | httpx |

### Domain Rules (MUST follow)

- All new services MUST be registered in `backend/src/core/container.py` and injected via FastAPI `Depends()`
- All database access goes through a Repository class — no raw SQL in services or routers
- Alembic migration required for every schema change — never modify models without a migration
- New backend routes protected with `get_current_user` (any auth) or `require_admin` (admin-only)
- RFC 7807 error responses: `{"detail": "...", "type": "...", "status": 400}`
- File bytes NEVER pass through FastAPI — use MinIO presigned PUT URLs
- Every LLM call wrapped with Langfuse tracing
- `connection_config` and `file_storage_path` MUST NEVER appear in API responses

### Hard Constraints

1. File bytes must NEVER pass through the FastAPI backend (MinIO presigned PUT)
2. Every LLM call MUST be Langfuse-traced (Constitution §II)
3. Celery Beat runs as a single replica — no duplicate scheduled jobs

---

## Objective

Replace the untyped `config` blob on `POST /api/v1/sources` with a strict Pydantic `SourceCreateRequest` that supports all wizard source types (DB, file via `object_key`, web URL, integration) and dispatches initial ingestion via Celery.

---

## Implementation Details

### Files to Update

#### 1. `backend/src/schemas/source.py`

Add structured request models. If the file does not yet exist, create it.

```python
from __future__ import annotations

from pydantic import BaseModel, Field, HttpUrl, field_validator


# ---- Connection sub-schemas ----

class DatabaseConnectionConfig(BaseModel):
    host: str
    port: int = Field(..., ge=1, le=65535)
    database: str
    username: str
    password: str
    ssl_mode: str = Field(default="require")  # disable|require|verify-ca|verify-full


class MongoConnectionConfig(BaseModel):
    uri: str
    database: str
    collections: str = ""  # comma-separated; empty string = all


class WebUrlConnectionConfig(BaseModel):
    url: HttpUrl
    crawl_depth: int = Field(default=0, ge=0, le=3)


# ---- Main request ----

_SOURCE_TYPES = {
    "postgresql", "mysql", "mssql", "mongodb",
    "pdf", "docx", "xlsx", "csv", "txt", "markdown",
    "web_url", "confluence", "sharepoint",
}
_FILE_TYPES = {"pdf", "docx", "xlsx", "csv", "txt", "markdown"}
_SYNC_MODES = {"manual", "scheduled", "delta"}
_RETRIEVAL_MODES = {"vector_only", "text_to_query", "hybrid"}


class SourceCreateRequest(BaseModel):
    name: str = Field(..., min_length=1, max_length=255)
    source_type: str
    connection: dict | None = None
    object_key: str | None = None
    description: str = ""
    sync_mode: str = "manual"
    sync_schedule: str | None = None  # cron expression, required if sync_mode == 'scheduled'
    retrieval_mode: str = "vector_only"
    citations_enabled: bool = True

    @field_validator("source_type")
    @classmethod
    def _validate_source_type(cls, v: str) -> str:
        if v not in _SOURCE_TYPES:
            raise ValueError(f"Unsupported source_type: {v}")
        return v

    @field_validator("sync_mode")
    @classmethod
    def _validate_sync_mode(cls, v: str) -> str:
        if v not in _SYNC_MODES:
            raise ValueError(f"Invalid sync_mode: {v}")
        return v

    @field_validator("retrieval_mode")
    @classmethod
    def _validate_retrieval_mode(cls, v: str) -> str:
        if v not in _RETRIEVAL_MODES:
            raise ValueError(f"Invalid retrieval_mode: {v}")
        return v


class SourcePublicResponse(BaseModel):
    """Public representation — NEVER exposes connection_config or file_storage_path."""
    id: str
    name: str
    source_type: str
    source_mode: str
    retrieval_mode: str
    description: str | None
    sync_mode: str
    sync_schedule: str | None
    last_synced_at: str | None
    status: str
    citations_enabled: bool
    created_at: str
    updated_at: str
```

#### 2. `backend/src/api/v1/sources.py`

Replace the existing `POST /api/v1/sources` handler.

```python
from celery import current_app as celery_app
from fastapi import Depends, HTTPException, status

from src.api.deps import require_admin, get_current_user
from src.core.container import Container
from src.schemas.source import (
    SourceCreateRequest,
    SourcePublicResponse,
    _FILE_TYPES,
)
from src.services.source_service import SourceService
from src.core.crypto import encrypt_connection_config  # Fernet helper


@router.post(
    "",
    response_model=SourcePublicResponse,
    status_code=status.HTTP_201_CREATED,
    dependencies=[Depends(require_admin)],
)
async def create_source(
    body: SourceCreateRequest,
    current_user = Depends(get_current_user),
    service: SourceService = Depends(lambda: Container.source_service()),
) -> SourcePublicResponse:
    is_file = body.source_type in _FILE_TYPES

    if is_file and not body.object_key:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="object_key required for file source types",
        )
    if not is_file and not body.connection:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="connection required for non-file source types",
        )
    if body.sync_mode == "scheduled" and not body.sync_schedule:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="sync_schedule (cron) required when sync_mode='scheduled'",
        )

    source_mode = "snapshot" if is_file else "live"
    encrypted_config = (
        encrypt_connection_config(body.connection) if body.connection else None
    )

    source = await service.create_source(
        name=body.name,
        source_type=body.source_type,
        source_mode=source_mode,
        retrieval_mode=body.retrieval_mode,
        description=body.description,
        sync_mode=body.sync_mode,
        sync_schedule=body.sync_schedule,
        citations_enabled=body.citations_enabled,
        connection_config=encrypted_config,     # INTERNAL
        file_storage_path=body.object_key,      # INTERNAL
        created_by=current_user.id,
        status="pending",
    )

    # Kick off initial ingestion.
    celery_app.send_task("sync_source", args=[str(source.id)])

    # Do NOT include connection_config / file_storage_path in response.
    return SourcePublicResponse(
        id=str(source.id),
        name=source.name,
        source_type=source.source_type,
        source_mode=source.source_mode,
        retrieval_mode=source.retrieval_mode,
        description=source.description,
        sync_mode=source.sync_mode,
        sync_schedule=source.sync_schedule,
        last_synced_at=source.last_synced_at.isoformat() if source.last_synced_at else None,
        status=source.status,
        citations_enabled=source.citations_enabled,
        created_at=source.created_at.isoformat(),
        updated_at=source.updated_at.isoformat(),
    )
```

#### 3. `backend/src/repositories/source_repository.py`

Ensure the `create` method accepts all new fields. Repository stays thin — no SQL in service/router.

```python
async def create(
    self,
    *,
    name: str,
    source_type: str,
    source_mode: str,
    retrieval_mode: str,
    description: str | None,
    sync_mode: str,
    sync_schedule: str | None,
    citations_enabled: bool,
    connection_config: str | None,
    file_storage_path: str | None,
    created_by: UUID,
    status: str,
) -> Source:
    source = Source(
        name=name,
        source_type=source_type,
        source_mode=source_mode,
        retrieval_mode=retrieval_mode,
        description=description,
        sync_mode=sync_mode,
        sync_schedule=sync_schedule,
        citations_enabled=citations_enabled,
        connection_config=connection_config,
        file_storage_path=file_storage_path,
        created_by=created_by,
        status=status,
    )
    self._session.add(source)
    await self._session.flush()
    await self._session.refresh(source)
    return source
```

#### 4. `backend/src/services/source_service.py`

Expose a matching `create_source(**kwargs)` method that delegates to the repository. Business rules (e.g. uniqueness check on `name`) stay in the service layer — no SQL here.

**Critical response rules**:
- `SourcePublicResponse` MUST NOT contain `connection_config` or `file_storage_path`.
- Even internal error messages must not leak the encrypted connection blob or the MinIO object key.

---

## Wiring Checklist (Web)

- [x] Pydantic request model `SourceCreateRequest` created
- [x] Public response model `SourcePublicResponse` created (excludes internal fields)
- [x] `POST /api/v1/sources` handler refactored to accept structured body
- [x] Service method `SourceService.create_source(**kwargs)` updated
- [x] Repository `create(**kwargs)` updated
- [x] Connection dict Fernet-encrypted before persistence
- [x] `object_key` routed to `file_storage_path` (never returned to client)
- [x] Initial `sync_source` Celery task dispatched post-create
- [x] `require_admin` enforced on route
- [ ] Alembic migration applied first (done in T-001)

---

## Verification Command

```bash
cd backend && python -c "
from src.schemas.source import SourceCreateRequest
r = SourceCreateRequest(
    name='test',
    source_type='postgresql',
    connection={'host':'localhost','port':5432,'database':'test','username':'u','password':'p'},
)
print('validation OK:', r.name)
"
```

**Expected output:** `validation OK: test`

---

## Completion Log

- [ ] `SourceCreateRequest` Pydantic model with validators added
- [ ] `SourcePublicResponse` excludes `connection_config` and `file_storage_path`
- [ ] `POST /api/v1/sources` accepts structured body (no raw config blob)
- [ ] File types require `object_key`; DB/web/integration types require `connection`
- [ ] `sync_schedule` required when `sync_mode='scheduled'`
- [ ] `source_mode` auto-derived (`snapshot` for files, `live` for DB)
- [ ] Connection dict Fernet-encrypted before persistence
- [ ] `sync_source` Celery task dispatched after create
- [ ] Repository and service signatures updated consistently
- [ ] `SourceCreateRequest` validates via pydantic (verification command passes)
