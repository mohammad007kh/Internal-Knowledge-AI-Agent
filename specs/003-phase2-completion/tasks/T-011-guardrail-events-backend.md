# T-011: Guardrail Events Backend (Audit Log)

- **Status**: Pending
- **Created**: 2026-04-21
- **Branch**: `003-phase2-completion`
- **User Story**: As an admin, I want to browse a paginated audit log of guardrail triggers and open any event for full detail, so I can investigate input/output guard decisions without exposing raw user content in the summary view.
- **Requirement**: FR-027 (paginated audit log), FR-028 (full event detail)
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
| `database.migration_strategy` | versioned (Alembic) |
| `conventions.files` | snake_case (Python) |
| `conventions.variables` | snake_case |
| `conventions.classes` | PascalCase |
| `api.versioning` | /api/v1/ |
| `api.error_format` | rfc7807 |
| `api.pagination` | offset (limit/offset/total) |
| `backend.language` | python |
| `backend.framework` | fastapi |
| `backend.orm` | sqlalchemy (async) |
| `backend.auth_method` | jwt |
| `backend.auth_pattern` | rbac (admin/user) |
| `testing.unit_framework` | pytest |

### Domain Rules
- All services registered in `backend/src/core/container.py` via `dependency-injector`.
- All DB access through Repository classes — no raw SQL in services or routers.
- Alembic for all schema changes.
- Admin endpoints protected with `require_admin`.
- RFC 7807 error responses.
- Privacy: `original_input` is sensitive and MUST NOT appear in list responses; only the detail endpoint returns it.

### API Context
- Base path: `/api/v1/admin/guardrail-events`
- Auth: `require_admin` on every route
- Error envelope: RFC 7807 problem+json
- Pagination: offset style (`limit`, `offset`, `total`)

### Feature Summary
Phase 2B admin experience: expose the guardrail audit log. List endpoint returns lightweight entries filterable by `guard_type` and `action`; detail endpoint returns the full record including `original_input` for investigation.

### Gate Criteria
- List response NEVER includes `original_input`.
- Detail response returns 404 when the id does not exist.
- Pagination envelope: `{items, total, limit, offset}`.
- Filtering supports `guard_type ∈ {input, output}` and `action ∈ {blocked, sanitized}`.

---

## 🎯 Objective

Deliver admin endpoints for the guardrail event audit log: a filtered/paginated list and a full-detail view. Reuse an existing `GuardrailEventRepository` if present; otherwise add a minimal repository.

---

## 🛠️ Implementation Details

### Files to Create

1. **`backend/src/api/v1/admin/guardrails.py`** — Router
   - `GET /` — `require_admin`
     - Query params: `limit: int = 20` (max 100), `offset: int = 0`, `guard_type: str | None = None`, `action: str | None = None`.
     - Calls repo method like `list_events(limit, offset, guard_type, action)`; returns `{items, total, limit, offset}`.
     - Each item joins `users` to include `user_email` but excludes `original_input`.
   - `GET /{id}` — `require_admin`
     - Returns full `GuardrailEventDetail`; 404 if not found.

### Files to Update

1. **`backend/src/core/container.py`** — If a `GuardrailEventRepository` is not yet registered, add it (providers.Factory with DB session).
2. **`backend/src/repositories/guardrail_event_repository.py`** — If not present, create with:
   - `async list_events(limit, offset, guard_type, action) -> tuple[list[Row], int]` — SELECT with optional WHERE filters, JOIN users for email, ORDER BY created_at DESC, LIMIT/OFFSET. Second return is the `COUNT(*)` for the same filters.
   - `async get_by_id(event_id: UUID) -> GuardrailEvent | None`.
3. **`backend/src/main.py`** — `include_router(admin_guardrails_router, prefix="/admin/guardrail-events", tags=["admin","guardrails"])`.

### Code / Logic Requirements

**Assumed schema for `guardrail_events`:**
```sql
id UUID PRIMARY KEY,
guard_type TEXT NOT NULL,         -- 'input' | 'output'
trigger_reason TEXT NOT NULL,
action TEXT NOT NULL,              -- 'blocked' | 'sanitized'
user_id UUID NOT NULL REFERENCES users(id),
original_input TEXT NOT NULL,
created_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
```
If any column is missing, add an Alembic migration `0020_guardrail_events_align.py`.

**Pydantic models (`backend/src/schemas/guardrail.py`):**

```python
from datetime import datetime
from pydantic import BaseModel

class GuardrailEventListItem(BaseModel):
    id: str
    guard_type: str
    trigger_reason: str
    action: str
    user_id: str
    user_email: str
    created_at: datetime

class GuardrailEventDetail(GuardrailEventListItem):
    original_input: str

class GuardrailEventListResponse(BaseModel):
    items: list[GuardrailEventListItem]
    total: int
    limit: int
    offset: int
```

**Filter validation:** Reject `guard_type` values outside `{input, output}` with 422; reject `action` outside `{blocked, sanitized}` with 422. Use Pydantic `Literal` or validator in the query-params model.

**Errors (RFC 7807):**
- Unknown id → 404 `{"title":"Guardrail event not found","status":404}`.

---

## 🔌 Wiring Checklist (Web backend)

- [ ] `GuardrailEventRepository` registered in `container.py` (if new).
- [ ] Router mounted at `/api/v1/admin/guardrail-events` in main app.
- [ ] Both routes guarded by `require_admin`.
- [ ] List response model `GuardrailEventListItem` does NOT contain `original_input` (enforced by schema).
- [ ] JOIN with `users` surfaces `user_email`.
- [ ] Filter values for `guard_type` / `action` validated.

---

## ✅ Verification

```bash
cd backend && python -c "from src.api.v1.admin.guardrails import router; print('routes:', [r.path for r in router.routes])"
```
Expected: prints paths for list and detail routes.

Additional manual checks:
- `GET /api/v1/admin/guardrail-events?limit=5&offset=0` returns up to 5 items with `total` integer present; no `original_input` in any list item.
- `GET /api/v1/admin/guardrail-events/<id>` returns full detail with `original_input` field populated.
- Non-admin JWT receives 403.

---

## 📝 Completion Log

- [ ] Repository implemented (or reused).
- [ ] Router mounted and protected with `require_admin`.
- [ ] List response excludes `original_input`.
- [ ] Filters validated.
- [ ] Verification command passes.
- [ ] Traceability: FR-027, FR-028 → this task → commit SHA _TBD_.
