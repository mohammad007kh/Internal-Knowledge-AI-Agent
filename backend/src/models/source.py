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
from datetime import datetime
from typing import TYPE_CHECKING

from sqlalchemy import Boolean, DateTime, Enum, ForeignKey, String, Text
from sqlalchemy.dialects.postgresql import BYTEA, UUID
from sqlalchemy.orm import Mapped, mapped_column, relationship

from src.models.base import Base, SoftDeleteMixin, TimestampMixin, UUIDMixin
from src.models.enums import SourceType

if TYPE_CHECKING:
    from src.models.chunk import Chunk
    from src.models.document import Document
    from src.models.source_permission import SourcePermission
    from src.models.sync_job import SyncJob
    from src.models.user import User


class Source(Base, UUIDMixin, TimestampMixin, SoftDeleteMixin):
    """A configured data source owned by a user.

    Visibility / lifecycle semantics:

    * ``deleted_at`` (from :class:`SoftDeleteMixin`) — soft-delete marker.
      ``deleted_at IS NULL`` means the source exists in the system.
      :meth:`SourceRepository.soft_delete` sets it to ``func.now()``.
    * ``is_active`` — admin approval flag ("approved/available to users").
      Defaults to ``False`` at the ORM level so freshly created rows must
      be explicitly approved by an admin. The DB-level server default is
      ``TRUE`` (legacy backfill) so historical rows remain approved.
    """

    __tablename__ = "sources"

    name: Mapped[str] = mapped_column(String(255), nullable=False, index=True)
    source_type: Mapped[SourceType] = mapped_column(
        # values_callable: bind the lowercase enum VALUE ("file_upload"), not
        # the uppercase NAME ("FILE_UPLOAD"). The Postgres enum is created
        # with the lowercase values; without this, asyncpg raises
        # InvalidTextRepresentationError on insert. Same fix as messagerole
        # in chat.py (Slice A).
        Enum(
            SourceType,
            name="sourcetype",
            create_constraint=True,
            values_callable=lambda enum_cls: [m.value for m in enum_cls],
        ),
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
    # is_active = "approved/available to users". Default False so admins
    # explicitly review/approve. deleted_at IS NULL means "not soft-deleted".
    # The DB-level server default is still TRUE (legacy backfill); the
    # ORM-level default is False so new rows created via the API land
    # pending approval.
    is_active: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)

    # -- Phase 2 fields ------------------------------------------------------
    source_mode: Mapped[str] = mapped_column(String, nullable=False, default="snapshot")
    retrieval_mode: Mapped[str] = mapped_column(String, nullable=False, default="vector_only")
    description: Mapped[str | None] = mapped_column(Text, nullable=True)
    sync_mode: Mapped[str] = mapped_column(String, nullable=False, default="manual")
    sync_schedule: Mapped[str | None] = mapped_column(String, nullable=True)
    # DB column is TIMESTAMP WITH TIME ZONE (migration 0018). Bind the ORM
    # type accordingly so asyncpg sees aware datetimes when comparing
    # against ``datetime.now(tz=timezone.utc)`` in scheduled-sync polling.
    last_synced_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    status: Mapped[str] = mapped_column(String, nullable=False, default="pending")
    citations_enabled: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)
    # Internal MinIO object key — NEVER exposed in API responses
    file_storage_path: Mapped[str | None] = mapped_column(String, nullable=True)
    next_sync_due_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    # Embedder pinned at Source creation; immutable once chunks exist.
    embedder_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("embedders.id", ondelete="RESTRICT"),
        nullable=True,
        index=True,
    )

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
    permissions: Mapped[list[SourcePermission]] = relationship(
        "SourcePermission",
        back_populates="source",
        cascade="all, delete-orphan",
        lazy="raise",
    )
    sync_jobs: Mapped[list[SyncJob]] = relationship(
        "SyncJob",
        back_populates="source",
        cascade="all, delete-orphan",
        lazy="raise",
    )

    def __repr__(self) -> str:  # pragma: no cover
        return (
            f"<Source id={self.id} name={self.name!r} type={self.source_type}>"
        )
