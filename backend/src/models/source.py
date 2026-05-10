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
    * ``deleted_at IS NULL`` means the row is not soft-deleted; admin and
      user-facing list queries filter on this. ``SoftDeleteMixin`` provides
      both the column and the helper methods that the repositories rely on.
    * ``is_active = TRUE`` means "approved by an admin / available to
      non-admin users". Admin views show every non-deleted source regardless
      of approval; user-facing surfaces additionally restrict on is_active.

    NOTE: SoftDeleteMixin was previously dropped from this class twice (once
    in 171612e via the same regression class as the StrEnum binding fix, and
    again in 2f50a16 during the SchemaStudy refactor). The Source repository
    references ``Source.deleted_at`` in ~10 query sites; without the mixin,
    EVERY list endpoint fails with AttributeError and /admin/sources renders
    empty. The regression guard at
    tests/unit/models/test_source_required_mixins.py catches this class.
    """

    __tablename__ = "sources"

    name: Mapped[str] = mapped_column(String(255), nullable=False, index=True)
    source_type: Mapped[SourceType] = mapped_column(
        # values_callable: bind the lowercase enum VALUE ("file_upload"), not
        # the uppercase NAME ("FILE_UPLOAD"). The Postgres enum is created
        # with the lowercase values; without this, asyncpg raises
        # InvalidTextRepresentationError on insert AND SQLAlchemy raises
        # LookupError on read. Same fix as messagerole / userrole / syncstatus.
        # Originally added in 53de827, lost in 171612e during the soft-delete
        # refactor — restored here.
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

    # -- AI auto-naming fields ----------------------------------------------
    # Tracks whether the user typed the value, the system is waiting for AI,
    # or the AI has written it. Used by the auto-naming pipeline to avoid
    # silently overwriting human-typed values, and by the frontend to render
    # a "Naming…" shimmer placeholder while pending.
    name_status: Mapped[str] = mapped_column(
        String(16),
        nullable=False,
        default="user_set",
        server_default="user_set",
        doc="One of user_set | pending_ai | ai_set.",
    )
    description_status: Mapped[str] = mapped_column(
        String(16),
        nullable=False,
        default="user_set",
        server_default="user_set",
        doc="One of user_set | pending_ai | ai_set.",
    )
    # The user's intent at creation time. Persisted so a future explicit
    # 'Regenerate' knows whether the original creation requested AI naming.
    auto_name_and_description: Mapped[bool] = mapped_column(
        Boolean,
        nullable=False,
        default=False,
        server_default="false",
        doc="Set when the admin checked 'Let AI name and describe this source for me'.",
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

    # -- Connection health (Slice A) ----------------------------------------
    # ``connection_status`` is orthogonal to ``is_active`` (admin approval).
    # ``is_active`` says "the admin approved this source"; ``connection_status``
    # says "the system can currently reach it". The chat picker hides
    # connection_status='failed' rows even when is_active=True so unreachable
    # sources don't silently return empty answers, while admins still see
    # them in /admin/sources to debug.
    connection_status: Mapped[str] = mapped_column(
        String(16),
        nullable=False,
        default="unknown",
        server_default="unknown",
        index=True,
        doc=(
            "One of healthy | degraded | failed | unknown. "
            "TODO(slice-A): wire DB-source studying-agent finalisation "
            "(schema_status -> FAILED) to flip this to 'failed' directly. "
            "Currently the indirect path through mark_failed (sync runs that "
            "fail because the studying agent flagged the source) covers the "
            "common case."
        ),
    )
    connection_last_checked_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True),
        nullable=True,
        doc="UTC timestamp of the most recent connection probe (sync or manual test).",
    )
    connection_last_error: Mapped[str | None] = mapped_column(
        String(500),
        nullable=True,
        doc=(
            "Most recent failure message, truncated to 500 chars. NEVER include "
            "connection strings or credentials — callers MUST sanitize."
        ),
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
