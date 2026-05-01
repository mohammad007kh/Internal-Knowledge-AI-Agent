# T-013: Backend — GET/PATCH /users/me Enhancements

- **Status**: Pending
- **Created**: 2026-04-22
- **Branch**: `003-phase2-completion`
- **User Story**: As an authenticated user, I want to view and update my profile (name, password, citation preference) from the application.
- **Requirement**: FR-032 (view own profile), FR-033 (update name/preference), FR-034 (change password)
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
| `conventions.variables` | snake_case |
| `conventions.classes` | PascalCase |
| `api.versioning` | /api/v1/ |
| `api.error_format` | rfc7807 |
| `backend.language` | python |
| `backend.framework` | fastapi |
| `backend.orm` | sqlalchemy (async) |
| `backend.auth_method` | jwt |
| `backend.auth_pattern` | rbac (admin/user) |
| `testing.unit_framework` | pytest |

### Domain Rules
- Migration 0018 already adds `full_name` and `show_citations_preference` columns to `users` table (T-001).
- `GET /users/me` likely already exists — enhance its response schema to include new fields.
- `PATCH /users/me` must accept optional fields only; no partial update should fail if a field is missing.
- Password change: requires `current_password` + `new_password`. Verify current hash before setting new.
- Password update MUST use the same bcrypt hashing as the existing auth flow.
- Do NOT expose password hash in any response.
- All services registered in `backend/src/core/container.py` via `dependency-injector`.

### API Context
- `GET /api/v1/users/me` — Any authenticated user
- `PATCH /api/v1/users/me` — Any authenticated user (owner only — implicit from JWT subject)
- Auth: `get_current_user` dependency on both routes
- Error envelope: RFC 7807 problem+json

### Gate Criteria
- `GET /users/me` returns `full_name` and `show_citations_preference`.
- `PATCH /users/me` with only `full_name` updates name, leaves password unchanged.
- `PATCH /users/me` with `new_password` but wrong `current_password` → 400.
- `PATCH /users/me` with `new_password` and correct `current_password` → password updated, 200.
- `PATCH /users/me` with `show_citations_preference: false` → persisted on next `GET`.

---

## 🎯 Objective

Enhance the existing `GET /users/me` response to include `full_name` and `show_citations_preference`, and add or update `PATCH /users/me` to allow updating those fields plus optional password change.

---

## 🛠️ Implementation Details

### Files to Update

1. **`backend/src/schemas/user.py`** — Add / update schemas:

```python
class UserPublic(BaseModel):
    id: str
    email: str
    full_name: str | None
    role: str
    show_citations_preference: bool
    created_at: datetime

class UserUpdateRequest(BaseModel):
    full_name: str | None = None
    show_citations_preference: bool | None = None
    current_password: str | None = None
    new_password: str | None = None

    @model_validator(mode='after')
    def password_change_requires_current(self) -> 'UserUpdateRequest':
        if self.new_password and not self.current_password:
            raise ValueError('current_password required when setting new_password')
        return self
```

2. **`backend/src/repositories/user_repository.py`** — Add update method if not present:

```python
async def update_me(
    self,
    user_id: UUID,
    full_name: str | None,
    show_citations_preference: bool | None,
    new_password_hash: str | None,
) -> User:
    # Build partial UPDATE using SQLAlchemy update(); return refreshed row.
    ...
```

3. **`backend/src/services/user_service.py`** (or equivalent) — Add `update_me` method:
   - If `new_password`: verify `current_password` against stored hash using `bcrypt.checkpw`; raise 400 if mismatch.
   - Hash `new_password` if verification passes.
   - Delegate column writes to repository.

4. **`backend/src/api/v1/users.py`** — Update / add routes:
   - `GET /me` → return `UserPublic` (update serialisation to include new fields).
   - `PATCH /me` → accept `UserUpdateRequest`, call service, return updated `UserPublic`.

### Pydantic / Error Handling

```python
# 400 on wrong current password
raise HTTPException(
    status_code=400,
    detail={"title": "Invalid current password", "status": 400, "type": "invalid_credentials"}
)
```

---

## 🔌 Wiring Checklist (Web backend)

- [ ] `users` table has `full_name` and `show_citations_preference` columns (from T-001 migration 0018).
- [ ] `UserPublic` schema includes both new fields.
- [ ] `GET /users/me` serialises with `UserPublic`.
- [ ] `PATCH /users/me` route added / updated.
- [ ] Password change validates `current_password`; returns 400 on mismatch.
- [ ] `UserRepository.update_me` registered in `container.py`.

---

## ✅ Verification

```bash
cd backend && python -c "
from src.schemas.user import UserPublic, UserUpdateRequest
assert hasattr(UserPublic, 'full_name'), 'missing full_name'
assert hasattr(UserPublic, 'show_citations_preference'), 'missing pref'
print('schemas OK')
"
```

Manual checks:
- `GET /api/v1/users/me` → response includes `full_name` and `show_citations_preference`.
- `PATCH /api/v1/users/me` with `{"full_name": "Alice"}` → 200, name updated.
- `PATCH /api/v1/users/me` with `{"new_password":"newpass","current_password":"wrong"}` → 400.
- `PATCH /api/v1/users/me` with correct `current_password` + `new_password` → 200, login with new password succeeds.

---

## 📝 Completion Log

- [ ] `UserPublic` schema includes `full_name` and `show_citations_preference`.
- [ ] `PATCH /users/me` route implemented.
- [ ] Password change guard implemented (wrong `current_password` → 400).
- [ ] Repository `update_me` method added.
- [ ] Verification command passes.
- [ ] Traceability: FR-032, FR-033, FR-034 → this task → commit SHA _TBD_.
