"""UserRefreshToken ORM model.

Each row represents one issued refresh token for a user.
Tokens are opaque UUID-4 strings (not JWTs).  They are rotated on every
successful token-refresh request and revoked on logout.

Relationships
-------------
user_id → users.id  (CASCADE DELETE — tokens are cleaned up with the user)
"""

import uuid
from datetime import datetime

from sqlalchemy import DateTime, ForeignKey, String
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column

from src.models.base import Base, TimestampMixin, UUIDMixin


class UserRefreshToken(Base, UUIDMixin, TimestampMixin):
    """Persisted refresh tokens for the rotating-refresh-token strategy."""

    __tablename__ = "user_refresh_tokens"

    user_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("users.id", ondelete="CASCADE"),
        nullable=False,
    )
    token: Mapped[str] = mapped_column(
        String(36),
        unique=True,
        index=True,
        nullable=False,
    )
    expires_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
    )
    revoked_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True),
        nullable=True,
        default=None,
    )
