"""SyncJob ORM model.

Implements T-060: SyncJob ORM Model.

Each SyncJob represents a single sync run for a Source.  The row tracks
lifecycle status, timing, and outcome counters so the API layer can report
progress and history without hitting the queue/worker directly.
"""

from __future__ import annotations

import uuid
from typing import TYPE_CHECKING

import sqlalchemy as sa
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column, relationship

from src.models.base import Base, TimestampMixin, UUIDMixin
from src.models.enums import SyncStatus

if TYPE_CHECKING:
    from src.models.source import Source


class SyncJob(UUIDMixin, TimestampMixin, Base):
    """Represents a single sync run for a data source.

    Attributes:
        source_id:         FK → sources.id.  Cascade-deleted with the source.
        status:            Current lifecycle state (pending → running → success/failed).
        started_at:        UTC timestamp when the worker picked up the job.
        finished_at:       UTC timestamp when the worker finished (success or failure).
        error_message:     Human-readable error detail populated on failure.
        documents_synced:  Number of documents upserted during the run.
        chunks_created:    Number of text chunks created or replaced during the run.
        source:            Back-reference to the owning Source row.
    """

    __tablename__ = "sync_jobs"

    source_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        sa.ForeignKey("sources.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    status: Mapped[SyncStatus] = mapped_column(
        sa.Enum(SyncStatus, name="syncstatus", create_type=False),
        nullable=False,
        default=SyncStatus.PENDING,
        server_default="pending",
        index=True,
    )
    started_at: Mapped[sa.DateTime | None] = mapped_column(
        sa.TIMESTAMP(timezone=True),
        nullable=True,
    )
    finished_at: Mapped[sa.DateTime | None] = mapped_column(
        sa.TIMESTAMP(timezone=True),
        nullable=True,
    )
    error_message: Mapped[str | None] = mapped_column(
        sa.Text,
        nullable=True,
    )
    documents_synced: Mapped[int] = mapped_column(
        sa.Integer,
        nullable=False,
        default=0,
        server_default="0",
    )
    chunks_created: Mapped[int] = mapped_column(
        sa.Integer,
        nullable=False,
        default=0,
        server_default="0",
    )

    # ------------------------------------------------------------------ #
    # Relationships                                                        #
    # ------------------------------------------------------------------ #

    source: Mapped[Source] = relationship(
        "Source",
        back_populates="sync_jobs",
        lazy="raise",
    )

    # ------------------------------------------------------------------ #
    # Dunder helpers                                                       #
    # ------------------------------------------------------------------ #

    def __repr__(self) -> str:  # pragma: no cover
        return (
            f"<SyncJob id={self.id!r} source_id={self.source_id!r} "
            f"status={self.status!r}>"
        )
