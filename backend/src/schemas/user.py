"""Pydantic v2 schemas for user-management endpoints (T-024).

Every endpoint handler MUST call ``UserResponse.model_validate(orm_obj)``
before returning — never expose raw ORM objects.
"""

from __future__ import annotations

import uuid
from datetime import datetime

from pydantic import BaseModel, ConfigDict, EmailStr, model_validator

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
    """Paginated list of users (legacy ``limit``/``offset`` envelope).

    Retained for the service-layer ``UserService.list_users`` API and its
    tests. The admin list endpoint now returns :class:`UserPage` instead.
    """

    items: list[UserResponse]
    total: int
    limit: int
    offset: int


class UserPage(BaseModel):
    """Paginated response envelope for ``GET /api/v1/users``.

    Mirrors the ``{items, total, page, page_size}`` shape used by the other
    paginated admin endpoints (e.g. ``GET /api/v1/admin/audit-log``).
    """

    items: list[UserResponse]
    total: int
    page: int
    page_size: int


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


# ---------------------------------------------------------------------------
# /users/me schemas (T-013)
# ---------------------------------------------------------------------------


class UserPublic(BaseModel):
    """Self-view returned by ``GET /users/me`` and ``PATCH /users/me``."""

    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    email: EmailStr
    full_name: str | None
    role: UserRole
    show_citations_preference: bool
    created_at: datetime


class UserUpdateRequest(BaseModel):
    """PATCH /users/me body — all fields optional.

    Password changes require the caller to supply the current password so
    that a stolen access token alone cannot rotate the password.
    """

    full_name: str | None = None
    show_citations_preference: bool | None = None
    current_password: str | None = None
    new_password: str | None = None

    @model_validator(mode="after")
    def _password_change_requires_current(self) -> "UserUpdateRequest":
        if self.new_password and not self.current_password:
            raise ValueError(
                "current_password is required when setting new_password"
            )
        return self
