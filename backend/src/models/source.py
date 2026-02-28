"""Source ORM model.

Implements T-040: Source ORM Models.

Source
------
Represents a data source configured by an admin user.  Connection credentials
are stored Fernet-encrypted in *config_encrypted* and MUST NOT be exposed to
unprivileged users or API responses.
"""

from __future__ import annotations

import uuid
from typing import TYPE_CHECKING

from sqlalchemy import Boolean, Enum, ForeignKey, String
from sqlalchemy.dialects.postgresql import BYTEA, UUID
from sqlalchemy.orm import Mapped, mapped_column, relationship

from src.models.base import Base, TimestampMixin, UUIDMixin
from src.models.enums import SourceType

if TYPE_CHECKING:
    from src.models.chunk import Chunk
    from src.models.document import Document
    from src.models.user import User


class Source(Base, UUIDMixin, TimestampMixin):
    """A configured data source owned by a user."""

    __tablename__ = "sources"

    name: Mapped[str] = mapped_column(String(255), nullable=False, index=True)
    source_type: Mapped[SourceType] = mapped_column(
        Enum(SourceType, name="sourcetype", create_constraint=True),
        nullable=False,
    )
    # Fernet-encrypted JSON blob: {"url": ..., "credentials": ...}
    # NEVER exposed to unprivileged API callers.
    config_encrypted: Mapped[bytes | None] = mapped_column(BYTEA, nullable=True)
    owner_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("users.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    is_active: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)

    # -- relationships -------------------------------------------------------
    owner: Mapped[User] = relationship(
        "User",
        back_populates="sources",
        lazy="selectin",
    )
    documents: Mapped[list[Document]] = relationship(
        "Document",
        back_populates="source",
        cascade="all, delete-orphan",
        lazy="raise",
    )
    chunks: Mapped[list[Chunk]] = relationship(
        "Chunk",
        back_populates="source",
        cascade="all, delete-orphan",
        lazy="raise",
    )

    def __repr__(self) -> str:  # pragma: no cover
        return (
            f"<Source id={self.id} name={self.name!r} type={self.source_type}>"
        )
