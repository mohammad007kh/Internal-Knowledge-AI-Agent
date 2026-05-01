# T-012: Invitation Management Backend

- **Status**: Pending
- **Created**: 2026-04-21
- **Branch**: `003-phase2-completion`
- **User Story**: As an admin, I want to list pending user invitations and revoke any that are no longer needed, so I can manage the onboarding queue without requiring a DB console.
- **Requirement**: FR-031 (pending invitations list, cancel)
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
- Admin endpoints protected with `require_admin`.
- RFC 7807 error responses.
- Soft-delete only for cancellation: set `status='revoked'`; never DELETE the row.
- `token_hash` is an internal secret — NEVER return it in any response body.

### API Context
- Mount path: `/api/v1/users/invitations` (two routes)
- Auth: `require_admin` on both routes
- Error envelope: RFC 7807 problem+json
- Pagination: offset style (`limit`, `offset`, `total`)

### Feature Summary
Phase 2B admin experience: expose pending-invitations list and cancel (revoke) actions on the existing `invitations` table. Accepted invitations cannot be revoked (409).

### Gate Criteria
- List returns ONLY `status='pending'` invitations.
- Cancel on `status='accepted'` returns 409.
- Cancel on unknown id returns 404.
- Cancel flips `status` to `'revoked'` and returns 204.
- `token_hash` is never leaked.

---

## 🎯 Objective

Add two admin endpoints to the existing users router: list pending invitations (paginated) and revoke a pending invitation by id. All DB access through a repository; no raw SQL in the router.

---

## 🛠️ Implementation Details

### Files to Update

1. **`backend/src/api/v1/users.py`** — Add two routes:
   - `GET /invitations` — `require_admin`
     - Query params: `limit: int = 20` (max 100), `offset: int = 0`.
     - Returns `{items: list[InvitationPublic], total, limit, offset}` — only pending invitations.
     - Items include `invited_by_email` via JOIN with `users`.
   - `DELETE /invitations/{id}` — `require_admin`
     - 404 if invitation not found.
     - 409 if `status='accepted'`.
     - Set `status='revoked'`.
     - Returns 204 No Content.

2. **`backend/src/repositories/invitation_repository.py`** — If not already present, add:
   - `async list_pending(limit, offset) -> tuple[list[Row], int]` — `WHERE status='pending'` plus JOIN users for inviter email. Second return is count.
   - `async get_by_id(invitation_id: UUID) -> Invitation | None`.
   - `async revoke(invitation_id: UUID) -> None` — `UPDATE invitations SET status='revoked' WHERE id=:id`.

3. **`backend/src/core/container.py`** — Register `InvitationRepository` if new. If an `InvitationService` is preferred (to match existing patterns), add it and wire both.

### Code / Logic Requirements

**Assumed schema for `invitations`:**
```sql
id UUID PRIMARY KEY,
email TEXT NOT NULL,
role TEXT NOT NULL,                 -- 'admin' | 'user'
token_hash TEXT NOT NULL,
invited_by UUID NOT NULL REFERENCES users(id),
expires_at TIMESTAMPTZ NOT NULL,
status TEXT NOT NULL,                -- 'pending' | 'accepted' | 'expired' | 'revoked'
created_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
```

**Pydantic model (`backend/src/schemas/invitation.py`):**

```python
from datetime import datetime
from pydantic import BaseModel

class InvitationPublic(BaseModel):
    id: str
    email: str
    role: str
    invited_by_email: str
    expires_at: datetime
    status: str
    created_at: datetime

class InvitationListResponse(BaseModel):
    items: list[InvitationPublic]
    total: int
    limit: int
    offset: int
```

**Errors (RFC 7807):**
- Not found → 404 `{"title":"Invitation not found","status":404}`.
- Already accepted → 409 `{"title":"Cannot revoke accepted invitation","status":409}`.

**Security:** The router MUST map DB rows to `InvitationPublic` explicitly; do NOT dump raw ORM objects (would leak `token_hash`).

---

## 🔌 Wiring Checklist (Web backend)

- [ ] `InvitationRepository` registered in `container.py` (if new).
- [ ] Two new routes added to `backend/src/api/v1/users.py`.
- [ ] Both routes guarded by `require_admin`.
- [ ] List response excludes `token_hash` (by virtue of `InvitationPublic`).
- [ ] 409 returned on accepted-status revoke attempts.
- [ ] DELETE returns 204 (no body).

---

## ✅ Verification

```bash
cd backend && python -c "
from src.api.v1.users import router
paths = [r.path for r in router.routes]
assert any('invitations' in p for p in paths), 'missing invitations routes'
print('OK:', paths)
"
```
Expected: prints `OK: [...]` with at least two paths containing `invitations`.

Additional manual checks:
- `GET /api/v1/users/invitations` as admin → only pending items.
- `DELETE /api/v1/users/invitations/<pending-id>` → 204; subsequent GET no longer lists the item.
- `DELETE /api/v1/users/invitations/<accepted-id>` → 409.
- `DELETE /api/v1/users/invitations/<unknown-id>` → 404.
- Non-admin JWT receives 403 on both routes.

---

## 📝 Completion Log

- [ ] Repository implemented / extended.
- [ ] Two new routes added under `/api/v1/users/invitations`.
- [ ] All routes guarded by `require_admin`.
- [ ] `token_hash` never leaked in responses.
- [ ] Verification command passes.
- [ ] Traceability: FR-031 → this task → commit SHA _TBD_.
