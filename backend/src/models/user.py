"""User and Invitation ORM models.

Implements T-021: User & Invitation ORM Models.

User
----
Core identity table.  Extends UUIDMixin, TimestampMixin, SoftDeleteMixin.

Invitation
----------
Tracks invitations sent to new users.  Extends UUIDMixin, TimestampMixin only
(accepted / expired tokens are kept for audit — no soft delete).
"""

from __future__ import annotations

import enum
import uuid
from datetime import datetime

from sqlalchemy import Boolean, DateTime, Enum, ForeignKey, String
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column, relationship

from src.models.base import Base, SoftDeleteMixin, TimestampMixin, UUIDMixin


# ---------------------------------------------------------------------------
# Enum
# ---------------------------------------------------------------------------

class UserRole(str, enum.Enum):
    """Application-level roles used for RBAC."""

    admin = "admin"
    user = "user"


# ---------------------------------------------------------------------------
# User
# ---------------------------------------------------------------------------

class User(Base, UUIDMixin, TimestampMixin, SoftDeleteMixin):
    """Application user with soft-delete support."""

    __tablename__ = "users"

    email: Mapped[str] = mapped_column(
        String(254), unique=True, index=True, nullable=False,
    )
    hashed_password: Mapped[str] = mapped_column(String(60), nullable=False)
    full_name: Mapped[str] = mapped_column(String(200), nullable=False)
    role: Mapped[UserRole] = mapped_column(
        Enum(UserRole, name="userrole"), nullable=False, default=UserRole.user,
    )
    is_active: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)
    must_change_password: Mapped[bool] = mapped_column(
        Boolean, nullable=False, default=False,
    )

    # -- relationships -------------------------------------------------------
    refresh_tokens: Mapped[list["UserRefreshToken"]] = relationship(  # noqa: F821
        "UserRefreshToken",
        back_populates="user",
        cascade="all, delete-orphan",
    )
    invitations_sent: Mapped[list["Invitation"]] = relationship(
        "Invitation",
        back_populates="invited_by_user",
        foreign_keys="Invitation.invited_by",
    )


# ---------------------------------------------------------------------------
# Invitation
# ---------------------------------------------------------------------------

class Invitation(Base, UUIDMixin, TimestampMixin):
    """Pending or accepted invitation for a new user.

    No soft-delete — accepted / expired invitations are retained for audit.
    """

    __tablename__ = "invitations"

    email: Mapped[str] = mapped_column(
        String(254), index=True, nullable=False,
    )
    token: Mapped[str] = mapped_column(
        String(36), unique=True, index=True, nullable=False,
    )
    invited_by: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("users.id", ondelete="SET NULL"),
        nullable=True,
    )
    role: Mapped[UserRole] = mapped_column(
        Enum(UserRole, name="userrole"), nullable=False, default=UserRole.user,
    )
    expires_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False,
    )
    accepted_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True,
    )

    # -- relationships -------------------------------------------------------
    invited_by_user: Mapped["User | None"] = relationship(
        "User",
        back_populates="invitations_sent",
        foreign_keys=[invited_by],
    )
