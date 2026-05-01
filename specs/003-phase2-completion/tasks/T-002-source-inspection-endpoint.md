# T-002: Source Inspection Service + Endpoint

| Field | Value |
|---|---|
| **Status** | Pending |
| **Created** | 2026-04-21 |
| **Feature** | 003-phase2-completion |
| **Branch** | `003-phase2-completion` |
| **User Story** | US-1 |
| **Requirements** | FR-004 (AI description generation), FR-003 (test connection) |
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

Implement a `SourceInspectionService` and `POST /api/v1/sources/inspect` endpoint that tests a connector's connection, inspects its schema, and generates an AI-authored natural-language description (Langfuse-traced) without persisting anything to the database.

---

## Implementation Details

### Files to Create

#### 1. `backend/src/services/source_inspection_service.py`

```python
"""Source inspection service: test connection + generate AI description."""
from __future__ import annotations

import logging
from typing import Any

from langfuse.decorators import observe

from src.connectors.factory import build_connector  # existing factory
from src.interfaces.llm_provider import ILLMProvider
from src.interfaces.connector import IConnector

logger = logging.getLogger(__name__)

SCHEMA_DESCRIPTION_PROMPT = """You are a technical writer. Given a data source schema,
produce a concise (2–3 sentence) natural-language description of what this data likely
contains and what questions it could answer. Be factual, avoid speculation.

Source type: {source_type}
Schema summary: {schema_summary}

Description:"""


class SourceInspectionService:
    """Test source connection, inspect schema, generate AI description.

    NEVER persists anything. Caller (wizard endpoint) decides whether to save.
    """

    def __init__(self, llm_provider: ILLMProvider) -> None:
        self._llm = llm_provider

    @observe(name="schema_inspector")
    async def inspect_source(
        self, source_type: str, connection: dict[str, Any]
    ) -> dict[str, Any]:
        """Inspect a source and return a description + schema summary.

        File source types return an empty payload — description generation
        for those is deferred to post-upload processing.
        """
        file_types = {"pdf", "docx", "xlsx", "csv", "txt", "markdown"}
        if source_type in file_types:
            return {"description": "", "schema_summary": {}}

        connector: IConnector = build_connector(source_type, connection)

        # Raises on failure — router translates to HTTP 422.
        await connector.test_connection()

        schema_info = await connector.inspect_schema()
        schema_summary = {
            "table_count": len(schema_info.get("tables", [])),
            "estimated_row_count": schema_info.get("estimated_row_count", 0),
        }

        try:
            prompt = SCHEMA_DESCRIPTION_PROMPT.format(
                source_type=source_type,
                schema_summary=schema_info,
            )
            description = await self._llm.complete(prompt=prompt, max_tokens=200)
        except Exception as exc:  # noqa: BLE001 — LLM failure is non-fatal
            logger.warning("LLM description generation failed: %s", exc)
            return {"description": "", "schema_summary": {}}

        return {
            "description": (description or "").strip(),
            "schema_summary": schema_summary,
        }
```

### Files to Update

#### 2. `backend/src/core/container.py`

Register `SourceInspectionService` as a singleton:

```python
from src.services.source_inspection_service import SourceInspectionService

class Container(containers.DeclarativeContainer):
    # ...existing providers...
    source_inspection_service = providers.Singleton(
        SourceInspectionService,
        llm_provider=llm_provider,  # existing provider
    )
```

#### 3. `backend/src/api/v1/sources.py`

Add request/response schemas and the inspect route.

```python
from fastapi import APIRouter, Depends, HTTPException, status
from pydantic import BaseModel, Field

from src.api.deps import require_admin
from src.core.container import Container
from src.services.source_inspection_service import SourceInspectionService


class SourceInspectRequest(BaseModel):
    source_type: str = Field(..., description="postgresql|mysql|mssql|mongodb|web_url|confluence|sharepoint|pdf|docx|xlsx|csv|txt|markdown")
    connection: dict = Field(default_factory=dict)


class SourceInspectResponse(BaseModel):
    description: str
    schema_summary: dict


@router.post(
    "/inspect",
    response_model=SourceInspectResponse,
    dependencies=[Depends(require_admin)],
)
async def inspect_source(
    body: SourceInspectRequest,
    service: SourceInspectionService = Depends(
        lambda: Container.source_inspection_service()
    ),
) -> SourceInspectResponse:
    try:
        result = await service.inspect_source(body.source_type, body.connection)
    except ConnectionError as exc:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail=str(exc),
        ) from exc
    except ValueError as exc:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=str(exc),
        ) from exc
    return SourceInspectResponse(**result)
```

**Notes**:
- Langfuse tracing is applied via the `@observe(name="schema_inspector")` decorator on `inspect_source`.
- For file sources, the service short-circuits and returns an empty payload.
- LLM failure is non-fatal — returns empty description rather than propagating.
- Nothing is persisted — this endpoint is pure read/compute.

---

## Wiring Checklist (Web)

- [x] New service (`SourceInspectionService`) created under `backend/src/services/`
- [x] Service registered as singleton in `backend/src/core/container.py`
- [x] New API route `POST /api/v1/sources/inspect` added
- [x] Route protected by `require_admin`
- [x] Pydantic request/response schemas defined
- [x] LLM call wrapped with Langfuse `@observe` decorator
- [x] RFC 7807-style error responses via `HTTPException(detail=...)`
- [ ] No migration needed
- [ ] No Celery task needed
- [ ] No frontend route (wizard UI is separate task)

---

## Verification Command

```bash
cd backend && python -m pytest tests/ -xvs -k "test_source_inspect" 2>&1 | head -40
```

**Also verify** the module imports cleanly:

```bash
cd backend && python -c "from src.services.source_inspection_service import SourceInspectionService; print('OK')"
```

**Expected output:** Tests pass or "no tests ran"; the second command prints `OK`.

---

## Completion Log

- [ ] `source_inspection_service.py` created with `@observe` Langfuse decorator
- [ ] `SourceInspectionService` registered in container as singleton
- [ ] `POST /api/v1/sources/inspect` route added with `require_admin`
- [ ] Pydantic `SourceInspectRequest` / `SourceInspectResponse` models defined
- [ ] File source types return empty payload (no connector invocation)
- [ ] DB source types call `test_connection()` → `inspect_schema()` → LLM
- [ ] Connection failures return HTTP 422 with RFC 7807 `detail`
- [ ] LLM failures return empty description (non-fatal)
- [ ] No persistence — endpoint is idempotent/pure
- [ ] Module imports cleanly (verification command passes)
