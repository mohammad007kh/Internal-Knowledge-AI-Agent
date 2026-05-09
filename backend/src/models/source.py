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

from sqlalchemy import Boolean, DateTime, Enum, ForeignKey, Integer, String, Text
from sqlalchemy.dialects.postgresql import BYTEA, UUID
from sqlalchemy.orm import Mapped, mapped_column, relationship

from src.models.base import Base, TimestampMixin, UUIDMixin
from src.models.enums import SourceType

if TYPE_CHECKING:
    from src.models.chunk import Chunk
    from src.models.document import Document
    from src.models.source_permission import SourcePermission
    from src.models.sync_job import SyncJob
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

    # -- Phase 2 fields ------------------------------------------------------
    source_mode: Mapped[str] = mapped_column(String, nullable=False, default="snapshot")
    retrieval_mode: Mapped[str] = mapped_column(String, nullable=False, default="vector_only")
    description: Mapped[str | None] = mapped_column(Text, nullable=True)
    sync_mode: Mapped[str] = mapped_column(String, nullable=False, default="manual")
    sync_schedule: Mapped[str | None] = mapped_column(String, nullable=True)
    last_synced_at: Mapped[datetime | None] = mapped_column(nullable=True)
    status: Mapped[str] = mapped_column(String, nullable=False, default="pending")
    citations_enabled: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)
    # Internal MinIO object key — NEVER exposed in API responses
    file_storage_path: Mapped[str | None] = mapped_column(String, nullable=True)
    next_sync_due_at: Mapped[datetime | None] = mapped_column(nullable=True)
    # Embedder pinned at Source creation; immutable once chunks exist.
    embedder_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("embedders.id", ondelete="RESTRICT"),
        nullable=True,
        index=True,
    )

    # -- DB-source studying-agent fields (Phase 1) --------------------------
    # ``schema_status`` mirrors the agent lifecycle for the *latest* study
    # and is the column the UI/list endpoints filter on.  Per-run history
    # lives in ``schema_studies``.
    schema_status: Mapped[str | None] = mapped_column(
        String,
        nullable=True,
        default=None,
        index=True,
        doc="One of QUEUED, STUDYING, READY, STALE, FAILED — null pre-Phase-1 sources.",
    )
    drift_signal_count: Mapped[int] = mapped_column(
        Integer,
        nullable=False,
        default=0,
        server_default="0",
        doc="Passive drift counter incremented when an inferred type mismatches.",
    )
    last_studied_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True),
        nullable=True,
        doc="Mirrors the most recent SchemaStudy.finished_at for fast UI sort.",
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
