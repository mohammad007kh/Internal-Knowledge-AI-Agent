"""User ORM model and role enumeration.

Stub created by T-020 (bootstrap admin).  Will be fully implemented in T-021.
"""

import enum

from sqlalchemy import Boolean, Enum, String
from sqlalchemy.orm import Mapped, mapped_column

from src.models.base import Base, SoftDeleteMixin, TimestampMixin, UUIDMixin


class UserRole(str, enum.Enum):
    """Application-level roles used for RBAC."""

    admin = "admin"
    user = "user"


class User(Base, UUIDMixin, TimestampMixin, SoftDeleteMixin):
    """Minimal user table — enough for bootstrap_admin (T-020).

    T-021 will add full_name, invitation columns, relationships, etc.
    """

    __tablename__ = "users"

    email: Mapped[str] = mapped_column(
        String(255), unique=True, nullable=False, index=True
    )
    hashed_password: Mapped[str] = mapped_column(String(255), nullable=False)
    role: Mapped[UserRole] = mapped_column(
        Enum(UserRole, name="userrole"), nullable=False, default=UserRole.user
    )
    is_active: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)
    must_change_password: Mapped[bool] = mapped_column(
        Boolean, nullable=False, default=False
    )
