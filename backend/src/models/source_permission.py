"""SourcePermission join model — governs which user can access which source.

Implements T-053: SourcePermission ORM + Migration.

SourcePermission
----------------
Join table linking users to sources they are permitted to access.
Hard-deleted (no soft-delete); cascade deletes follow the parent FK.
"""

from __future__ import annotations

import uuid
from typing import TYPE_CHECKING

from sqlalchemy import ForeignKey, UniqueConstraint
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column, relationship

from src.models.base import Base, TimestampMixin, UUIDMixin

if TYPE_CHECKING:
    from src.models.source import Source
    from src.models.user import User


class SourcePermission(UUIDMixin, TimestampMixin, Base):
    """Join record granting a user access to a source."""

    __tablename__ = "source_permissions"
    __table_args__ = (
        UniqueConstraint("source_id", "user_id", name="uq_source_permissions"),
    )

    source_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("sources.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    user_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("users.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )

    # -- relationships -------------------------------------------------------
    source: Mapped[Source] = relationship(
        "Source",
        back_populates="permissions",
        lazy="raise",
    )
    user: Mapped[User] = relationship(
        "User",
        back_populates="source_permissions",
        lazy="raise",
    )

    def __repr__(self) -> str:  # pragma: no cover
        return (
            f"<SourcePermission id={self.id} "
            f"source_id={self.source_id} user_id={self.user_id}>"
        )
