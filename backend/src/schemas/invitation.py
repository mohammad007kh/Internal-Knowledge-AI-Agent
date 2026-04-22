"""Pydantic v2 schemas for invitation management endpoints (T-012)."""

from __future__ import annotations

import uuid
from datetime import datetime

from pydantic import BaseModel, ConfigDict


class InvitationPublic(BaseModel):
    """Public, admin-facing view of a pending invitation.

    ``invited_by_email`` is resolved from the joined ``User`` row in the
    repository — the router must not rely on lazy loading.
    """

    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    email: str
    role: str
    invited_by_email: str | None
    expires_at: datetime
    created_at: datetime

    @classmethod
    def from_orm_row(cls, invitation: object) -> "InvitationPublic":
        """Construct from an ORM ``Invitation`` with eager-loaded ``invited_by_user``."""
        invited_by_user = getattr(invitation, "invited_by_user", None)
        invited_by_email = (
            getattr(invited_by_user, "email", None) if invited_by_user else None
        )
        return cls(
            id=getattr(invitation, "id"),
            email=getattr(invitation, "email"),
            role=str(getattr(invitation, "role")),
            invited_by_email=invited_by_email,
            expires_at=getattr(invitation, "expires_at"),
            created_at=getattr(invitation, "created_at"),
        )


class InvitationListResponse(BaseModel):
    """Paginated list of pending invitations."""

    items: list[InvitationPublic]
    total: int
    limit: int
    offset: int
