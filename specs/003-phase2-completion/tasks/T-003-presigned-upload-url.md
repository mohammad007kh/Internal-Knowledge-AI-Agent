# T-003: Presigned Upload URL Endpoint

| Field | Value |
|---|---|
| **Status** | Pending |
| **Created** | 2026-04-21 |
| **Feature** | 003-phase2-completion |
| **Branch** | `003-phase2-completion` |
| **User Story** | US-1 |
| **Requirements** | FR-006 (file bytes never pass through backend), FR-005 (file upload) |
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
- **File bytes NEVER pass through FastAPI — use MinIO presigned PUT URLs**
- Every LLM call wrapped with Langfuse tracing
- `connection_config` and `file_storage_path` MUST NEVER appear in API responses

### Hard Constraints

1. **File bytes must NEVER pass through the FastAPI backend (MinIO presigned PUT)** ← primary constraint for this task
2. Every LLM call MUST be Langfuse-traced (Constitution §II)
3. Celery Beat runs as a single replica — no duplicate scheduled jobs

---

## Objective

Add a `POST /api/v1/sources/upload-url` endpoint that generates a short-lived MinIO presigned PUT URL so the browser can upload a file directly to MinIO without the bytes ever passing through FastAPI.

---

## Implementation Details

### Files to Update

#### `backend/src/api/v1/sources.py`

Add request/response schemas and the upload-url route.

```python
from datetime import datetime, timezone
from uuid import uuid4

from fastapi import APIRouter, Depends, HTTPException, status
from pydantic import BaseModel, Field

from src.api.deps import require_admin
from src.core.container import Container
from src.interfaces.file_storage import IFileStorage


_ALLOWED_CONTENT_TYPES: frozenset[str] = frozenset({
    "application/pdf",
    "application/vnd.openxmlformats-officedocument.wordprocessingml.document",
    "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
    "text/csv",
    "text/plain",
    "text/markdown",
})

_PRESIGN_EXPIRES_MINUTES = 15


class UploadUrlRequest(BaseModel):
    filename: str = Field(..., min_length=1, max_length=255)
    content_type: str = Field(..., min_length=1, max_length=200)


class UploadUrlResponse(BaseModel):
    upload_url: str
    object_key: str


def _build_object_key(filename: str) -> str:
    now = datetime.now(tz=timezone.utc)
    safe_name = filename.replace("/", "_").replace("\\", "_")
    return f"uploads/{now.strftime('%Y/%m')}/{uuid4()}-{safe_name}"


@router.post(
    "/upload-url",
    response_model=UploadUrlResponse,
    dependencies=[Depends(require_admin)],
)
async def create_upload_url(
    body: UploadUrlRequest,
    storage: IFileStorage = Depends(lambda: Container.file_storage()),
) -> UploadUrlResponse:
    if body.content_type not in _ALLOWED_CONTENT_TYPES:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Unsupported file type",
        )

    object_key = _build_object_key(body.filename)
    upload_url = await storage.generate_presigned_put_url(
        object_key=object_key,
        content_type=body.content_type,
        expires_minutes=_PRESIGN_EXPIRES_MINUTES,
    )
    return UploadUrlResponse(upload_url=upload_url, object_key=object_key)
```

**Critical properties**:
- The endpoint **never** accepts or handles file bytes — only metadata.
- The presigned URL expires in 15 minutes (short-lived, single-use intent).
- The `object_key` is returned so the frontend can submit it back to `POST /api/v1/sources` (T-004), which stores it in the INTERNAL `file_storage_path` column.
- Response contains no sensitive internal state beyond the presigned URL itself (which is inherently short-lived).

**Wiring**:
- No new file required — extend the existing `backend/src/api/v1/sources.py` router.
- No container changes needed — `IFileStorage` is already registered in `backend/src/core/container.py` (from Phase 1).
- No migration, no new service class.

---

## Wiring Checklist (Web)

- [x] New API route `POST /api/v1/sources/upload-url` added
- [x] Route protected by `require_admin`
- [x] Pydantic `UploadUrlRequest` / `UploadUrlResponse` schemas defined
- [x] Allowed content types enforced (rejects with HTTP 400)
- [x] `IFileStorage` injected via `Depends()` — already registered in container
- [x] File bytes NEVER touch this endpoint
- [ ] No migration required
- [ ] No new service class
- [ ] No new Celery task
- [ ] No frontend route (wizard consumes endpoint in later task)

---

## Verification Command

```bash
cd backend && python -c "from src.api.v1.sources import router; routes = [r.path for r in router.routes]; print([r for r in routes if 'upload' in r])"
```

**Expected output:** A non-empty list containing an upload-url path, e.g. `['/upload-url']`.

---

## Completion Log

- [ ] `POST /api/v1/sources/upload-url` route added to existing router
- [ ] Route guarded by `require_admin` dependency
- [ ] `UploadUrlRequest` / `UploadUrlResponse` Pydantic models defined
- [ ] Allowed content types whitelist enforced (HTTP 400 on violation)
- [ ] `IFileStorage` dependency injected — no container changes required
- [ ] Object key format: `uploads/YYYY/MM/{uuid4}-{filename}`
- [ ] Presigned URL TTL set to 15 minutes
- [ ] Endpoint accepts no file bytes — metadata only
- [ ] Filename sanitized (no path traversal via `/` or `\`)
- [ ] Verification command prints the new route path
