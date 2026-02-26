---
id: T-024
title: Pydantic v2 Request/Response Schemas for Auth & User Endpoints
status: Not Started
created: 2026-02-25
phase: Phase 1 — Auth & User Management
user_story: US3, US4, US5, US6
requirements: [FR-AUTH-1, FR-AUTH-2, FR-AUTH-3, FR-USER-1, FR-USER-2]
priority: P1
depends_on: [T-021, T-022]
blocks: [T-025, T-026]
estimated_effort: 1.5h
---

## Goal

Define all Pydantic v2 request and response schemas for the auth and user-management domain. Schemas are the API contract — they are the only place where JSON serialization/deserialization logic lives. No ORM model is ever returned directly from an endpoint.

---

## Acceptance Criteria

- [ ] All schemas use `model_config = ConfigDict(from_attributes=True)`
- [ ] Response schemas exclude `hashed_password`, `deleted_at` by default
- [ ] `password` fields always have `@field_validator` calling `validate_password_policy`
- [ ] All email fields are lowercased and stripped via `@field_validator`
- [ ] `UserResponse` does NOT expose `hashed_password` — validator test enforces this
- [ ] Unit tests: schema validation + `model_validate` from ORM objects

---

## Files to Create

| Path | Purpose |
|------|---------|
| `backend/src/schemas/auth.py` | Login, tokens, registration, invitation schemas |
| `backend/src/schemas/user.py` | User CRUD request/response schemas |
| `backend/tests/unit/test_schemas_auth.py` | Schema validation tests |

---

## Schema Reference

### `backend/src/schemas/auth.py`

```python
from pydantic import BaseModel, ConfigDict, EmailStr, field_validator
from src.services.password_service import PasswordService


class LoginRequest(BaseModel):
    email: EmailStr
    password: str

    @field_validator("email", mode="before")
    @classmethod
    def normalise_email(cls, v: str) -> str:
        return v.strip().lower()


class TokenResponse(BaseModel):
    access_token: str
    token_type: str = "bearer"
    expires_in: int  # seconds


class RegisterRequest(BaseModel):
    email: EmailStr
    password: str
    full_name: str

    @field_validator("email", mode="before")
    @classmethod
    def normalise_email(cls, v: str) -> str:
        return v.strip().lower()

    @field_validator("password")
    @classmethod
    def validate_pw(cls, v: str) -> str:
        PasswordService.validate_password_policy(v)
        return v


class InviteRequest(BaseModel):
    email: EmailStr
    role: str = "user"

    @field_validator("email", mode="before")
    @classmethod
    def normalise_email(cls, v: str) -> str:
        return v.strip().lower()


class AcceptInvitationRequest(BaseModel):
    token: str
    full_name: str
    password: str

    @field_validator("password")
    @classmethod
    def validate_pw(cls, v: str) -> str:
        PasswordService.validate_password_policy(v)
        return v


class ChangePasswordRequest(BaseModel):
    current_password: str
    new_password: str

    @field_validator("new_password")
    @classmethod
    def validate_pw(cls, v: str) -> str:
        PasswordService.validate_password_policy(v)
        return v
```

### `backend/src/schemas/user.py`

```python
import uuid
from datetime import datetime
from pydantic import BaseModel, ConfigDict, EmailStr
from src.models.user import UserRole


class UserResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    email: EmailStr
    full_name: str
    role: UserRole
    is_active: bool
    created_at: datetime


class UserListResponse(BaseModel):
    items: list[UserResponse]
    total: int
    limit: int
    offset: int


class UpdateUserRequest(BaseModel):
    full_name: str | None = None
    is_active: bool | None = None
```

---

## Rule: No Raw ORM in Responses

Every endpoint handler must call `UserResponse.model_validate(orm_obj)` before returning.  
Returning an ORM object directly bypasses the schema and may leak `hashed_password`.

```python
# ✅ Correct
return UserResponse.model_validate(user)

# ❌ Never
return user
```

---

## 📝 Completion Log

- [ ] Schemas implemented
- [ ] `UserResponse` cannot be constructed with `hashed_password` field
- [ ] Round-trip test: `UserResponse.model_validate(User(...))` succeeds
- [ ] Linter passed
