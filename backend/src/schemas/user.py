"""Pydantic v2 schemas for user-management endpoints (T-024).

Every endpoint handler MUST call ``UserResponse.model_validate(orm_obj)``
before returning — never expose raw ORM objects.
"""

import uuid
from datetime import datetime

from pydantic import BaseModel, ConfigDict, EmailStr

from src.models.user import UserRole

# ---------------------------------------------------------------------------
# Response
# ---------------------------------------------------------------------------

class UserResponse(BaseModel):
    """Public representation of a user — hashed_password is never exposed."""

    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    email: EmailStr
    full_name: str
    role: UserRole
    is_active: bool
    created_at: datetime
    last_login_at: datetime | None = None


class UserListResponse(BaseModel):
    """Paginated list of users."""

    items: list[UserResponse]
    total: int
    limit: int
    offset: int


# ---------------------------------------------------------------------------
# Request
# ---------------------------------------------------------------------------

class UpdateUserRequest(BaseModel):
    """PATCH /users/{id} body — all fields optional."""

    full_name: str | None = None
    is_active: bool | None = None


class InvitationCreateRequest(BaseModel):
    """POST /users/invitations body."""

    email: EmailStr
    role: UserRole = UserRole.user


class RoleChangeRequest(BaseModel):
    """PATCH /users/{id}/role body."""

    role: UserRole
