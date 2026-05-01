# T-010: Company Policy Backend (Versioned CRUD)

- **Status**: Pending
- **Created**: 2026-04-21
- **Branch**: `003-phase2-completion`
- **User Story**: As an admin, I want to read the current company policy and publish a new version without losing history, so prior policy text is always auditable.
- **Requirement**: FR-025 (read/update policy text), FR-026 (versioned — previous preserved)
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
- Policy updates MUST be immutable: a new version is created; previous rows are preserved with `is_active=FALSE`.

### API Context
- Base path: `/api/v1/admin/policy`
- Auth: `require_admin` on every route
- Error envelope: RFC 7807 problem+json

### Feature Summary
Phase 2B admin experience: read the active company policy and publish new versions. Every update creates a new row; `is_active=FALSE` is set on all previous rows. This preserves audit history.

### Gate Criteria
- `PUT /policy` creates a NEW row — never updates an existing one in place.
- Previous rows retain their content; only `is_active` flips to FALSE.
- `GET /policy` returns the single row where `is_active=TRUE`, highest version.
- Admin-only access enforced on both routes.

---

## 🎯 Objective

Deliver a clean-architecture admin backend for company policy with versioned, append-only writes. Reads return the active policy; writes create a new version atomically and deactivate prior versions.

---

## 🛠️ Implementation Details

### Files to Create

1. **`backend/src/repositories/policy_repository.py`** — `PolicyRepository`
   - `async get_active() -> CompanyPolicy | None` — `WHERE is_active = TRUE ORDER BY version DESC LIMIT 1`.
   - `async create_version(content: str, created_by_user_id: UUID) -> CompanyPolicy`
     - Compute next version: `SELECT COALESCE(MAX(version), 0) + 1 FROM company_policies`.
     - Inside a single transaction:
       1. `UPDATE company_policies SET is_active = FALSE WHERE is_active = TRUE`.
       2. Insert new row with `is_active=TRUE`, `version=next_version`, `content`, `created_by`, `created_at=now()`.
     - Return the new `CompanyPolicy` record.

2. **`backend/src/services/policy_service.py`** — `PolicyService`
   - `async get_active_policy() -> PolicyPublic` — wraps repo call; raises 404 if none exists.
   - `async update_policy(content: str, admin_user_id: UUID) -> PolicyPublic` — calls `repository.create_version()`; returns the new record as `PolicyPublic`. Does NOT overwrite.

3. **`backend/src/api/v1/admin/policy.py`** — Router
   - `GET /` — `require_admin` → `PolicyService.get_active_policy()`.
   - `PUT /` — `require_admin`, body `UpdatePolicyRequest` → `PolicyService.update_policy(content, current_user.id)`.

### Files to Update

1. **`backend/src/core/container.py`** — Register `PolicyRepository` (providers.Factory with DB session) and `PolicyService` (providers.Factory with repo).
2. **`backend/src/main.py`** (or admin router aggregator) — `include_router(admin_policy_router, prefix="/admin/policy", tags=["admin","policy"])`.

### Code / Logic Requirements

**Assumed schema for `company_policies`:**
```sql
id UUID PRIMARY KEY,
content TEXT NOT NULL,
version INT NOT NULL,
is_active BOOLEAN NOT NULL DEFAULT TRUE,
created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
created_by UUID NOT NULL REFERENCES users(id)
```
If the table does not already carry these columns, add an Alembic migration `0019_policy_versioned.py` to align.

**Pydantic models (`backend/src/schemas/policy.py`):**

```python
from datetime import datetime
from pydantic import BaseModel, Field

class UpdatePolicyRequest(BaseModel):
    content: str = Field(min_length=1)

class PolicyPublic(BaseModel):
    id: str
    content: str
    version: int
    created_at: datetime
```

**Atomicity:** `create_version` MUST run the deactivate + insert inside one transaction (use the injected async session's `begin()` context or nested `begin_nested()` depending on existing conventions in the repo layer).

**Errors (RFC 7807):**
- `GET /policy` when table is empty → 404 `{"title":"No active policy","status":404}`.
- Empty `content` → 422 (handled by Pydantic min_length).

---

## 🔌 Wiring Checklist (Web backend)

- [ ] `PolicyRepository` registered in `container.py`.
- [ ] `PolicyService` registered in `container.py`.
- [ ] Router mounted at `/api/v1/admin/policy` in main app.
- [ ] Both routes guarded by `require_admin`.
- [ ] Transaction wraps deactivate + insert in `create_version`.
- [ ] Alembic migration added only if schema drift is detected.

---

## ✅ Verification

```bash
cd backend && python -c "from src.api.v1.admin.policy import router; print('OK:', [r.path for r in router.routes])"
```
Expected: prints route paths including `/` (GET) and `/` (PUT).

Additional manual checks:
- `PUT /api/v1/admin/policy` twice with different content → SELECT returns 2 rows, one with `is_active=TRUE` (higher version).
- `GET /api/v1/admin/policy` returns only the active (latest) version.
- Non-admin JWT receives 403.

---

## 📝 Completion Log

- [ ] Repository implemented with transactional `create_version`.
- [ ] Service implemented and wired.
- [ ] Router mounted and protected with `require_admin`.
- [ ] Container wiring updated.
- [ ] Verification command passes.
- [ ] Traceability: FR-025, FR-026 → this task → commit SHA _TBD_.
