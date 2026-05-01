# T-014: Backend — Source Stats + Refresh Description Endpoints

- **Status**: Pending
- **Created**: 2026-04-22
- **Branch**: `003-phase2-completion`
- **User Story**: As an admin, I want to see live stats for each source and trigger a fresh AI-generated description without leaving the detail page.
- **Requirement**: FR-012 (view source stats), FR-013 (refresh AI description)
- **Priority**: P1

---

## 📋 Embedded Context

### Registry Standards (locked for this project)
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
| `conventions.files` | snake_case (Python) |
| `api.versioning` | /api/v1/ |
| `api.error_format` | rfc7807 |
| `backend.language` | python |
| `backend.framework` | fastapi |
| `backend.orm` | sqlalchemy (async) |
| `backend.auth_pattern` | rbac (admin/user) |
| `testing.unit_framework` | pytest |

### Domain Rules
- All DB access through Repository classes — no raw SQL in routers/services.
- Both endpoints are admin-only (`require_admin`).
- `SourceInspectionService` was introduced in T-002 for the inspect flow; reuse it here for the refresh-description endpoint.
- `connection_config` and `file_storage_path` MUST NOT appear in any response.
- `refresh-description` does NOT save — it returns `proposed_description` for admin review. Admin saves via `PATCH /sources/{id}` (separate flow).
- Every LLM call must pass through Langfuse-traced code (Constitution §II).

### API Context
- `GET /api/v1/sources/{id}/stats` — Admin only
- `POST /api/v1/sources/{id}/refresh-description` — Admin only
- Auth: `require_admin` on both
- Source must exist; 404 if not found

### Gate Criteria
- `GET /sources/{id}/stats` returns `document_count`, `chunk_count`, `last_synced_at`, `sync_job_count`.
- `POST /sources/{id}/refresh-description` calls `SourceInspectionService` and returns `proposed_description`.
- Neither endpoint leaks `connection_config` or `file_storage_path`.
- Both return 404 for unknown source id.

---

## 🎯 Objective

Add `GET /sources/{id}/stats` and `POST /sources/{id}/refresh-description` routes to the existing sources router. Stats come from the DB; refresh description re-runs inspection without persisting.

---

## 🛠️ Implementation Details

### Files to Update

1. **`backend/src/api/v1/sources.py`** — Add two routes:

   **`GET /{id}/stats`**:
   ```python
   @router.get("/{source_id}/stats", response_model=SourceStatsResponse)
   async def get_source_stats(
       source_id: UUID,
       stats_service: SourceStatsService = Depends(container.source_stats_service),
       _: User = Depends(require_admin),
   ) -> SourceStatsResponse:
       return await stats_service.get_stats(source_id)
   ```

   **`POST /{id}/refresh-description`**:
   ```python
   @router.post("/{source_id}/refresh-description")
   async def refresh_description(
       source_id: UUID,
       inspection_service: SourceInspectionService = Depends(container.source_inspection_service),
       source_repo: SourceRepository = Depends(container.source_repository),
       _: User = Depends(require_admin),
   ) -> dict:
       source = await source_repo.get_by_id(source_id)
       if not source:
           raise HTTPException(status_code=404, detail={"title":"Source not found","status":404})
       proposed = await inspection_service.generate_description(source)
       return {"proposed_description": proposed}
   ```

2. **`backend/src/schemas/source.py`** — Add:
```python
class SourceStatsResponse(BaseModel):
    document_count: int
    chunk_count: int
    last_synced_at: datetime | None
    sync_job_count: int
```

3. **`backend/src/repositories/source_repository.py`** — Add `get_stats(source_id)`:
```python
async def get_stats(self, source_id: UUID) -> dict:
    # SELECT document_count, chunk_count, last_synced_at from sources WHERE id=:id
    # SELECT COUNT(*) FROM sync_jobs WHERE source_id=:id
    ...
```

4. **`backend/src/services/source_stats_service.py`** (new if not existing):
   - Wraps `SourceRepository.get_stats`.
   - Raises 404 if source not found.
   - Returns `SourceStatsResponse`.

5. **`backend/src/core/container.py`** — Register `SourceStatsService` if new.

---

## 🔌 Wiring Checklist (Web backend)

- [ ] `GET /{id}/stats` route added to sources router.
- [ ] `POST /{id}/refresh-description` route added to sources router.
- [ ] Both routes guarded with `require_admin`.
- [ ] `SourceStatsResponse` Pydantic model created.
- [ ] `SourceStatsService` registered in `container.py`.
- [ ] `SourceInspectionService.generate_description` accepts a source ORM model (not just a raw config dict).
- [ ] Both return 404 for unknown source id.

---

## ✅ Verification

```bash
cd backend && python -c "
from src.api.v1.sources import router
paths = [r.path for r in router.routes]
assert any('stats' in p for p in paths), 'missing stats route'
assert any('refresh-description' in p for p in paths), 'missing refresh-description route'
print('OK:', [p for p in paths if 'stats' in p or 'refresh' in p])
"
```

Manual checks:
- `GET /api/v1/sources/{valid-id}/stats` → 200 with `document_count`, `chunk_count`, `last_synced_at`, `sync_job_count`.
- `POST /api/v1/sources/{valid-id}/refresh-description` → 200 with `proposed_description`.
- Both → 404 for unknown id.
- Both → 403 for non-admin JWT.

---

## 📝 Completion Log

- [ ] `GET /{id}/stats` route implemented.
- [ ] `POST /{id}/refresh-description` route implemented.
- [ ] `SourceStatsResponse` schema defined.
- [ ] 404 guard on unknown source id.
- [ ] No `connection_config` or `file_storage_path` in response.
- [ ] Verification command passes.
- [ ] Traceability: FR-012, FR-013 → this task → commit SHA _TBD_.
