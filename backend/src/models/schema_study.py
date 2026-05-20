"""ORM models for the DB-source studying-agent.

Phase 1 — Deliverable #1.

Two tables:

* ``schema_studies`` — one row per study run for a given source.  Holds the
  finished :class:`SchemaDocument` JSON, the fingerprint, the terminal state,
  and a couple of denormalised error fields for fast admin triage.
* ``schema_study_phases`` — one row per phase per study, used by the live
  progress UI and by the orchestrator to resume / retry granular phases.

Phase 1 deliberately ships only the persistence layer.  The orchestrator,
inspectors, and Celery wiring are added in subsequent phases — see
``specs/`` for the rollout plan.
"""

from __future__ import annotations

import uuid
from datetime import datetime

from sqlalchemy import (
    DateTime,
    ForeignKey,
    Index,
    Integer,
    String,
    Text,
    text,
)
from sqlalchemy.dialects.postgresql import JSONB, UUID
from sqlalchemy.orm import Mapped, mapped_column, relationship

from src.models.base import Base, TimestampMixin


# ---------------------------------------------------------------------------
# State / phase string vocabularies
# ---------------------------------------------------------------------------
#
# These are kept as module-level frozensets (not Enum) for two reasons:
#   1. The studying-agent treats them as strings on the wire (REST + Celery)
#      and persists them verbatim; an Enum would force everything through a
#      type-marshalling layer for very little value.
#   2. The set is expected to grow per-phase as new dialects come online,
#      and adding values to a Postgres ENUM requires a migration.

STUDY_STATES: frozenset[str] = frozenset(
    {
        "QUEUED",
        "CONNECTING",
        "INVENTORY",
        "COLUMNS",
        "SAMPLING",
        "DESCRIBING",
        "INDEXING",
        "READY",
        "READY_PARTIAL",
        "CONNECT_FAILED",
        "INVENTORY_FAILED",
        "COLUMNS_FAILED",
        "SAMPLING_FAILED",
        "DESCRIBING_FAILED",
        "INDEXING_FAILED",
    }
)

STUDY_PHASES: frozenset[str] = frozenset(
    {
        "CONNECTING",
        "INVENTORY",
        "COLUMNS",
        "SAMPLING",
        "DESCRIBING",
        "INDEXING",
    }
)

PHASE_STATUSES: frozenset[str] = frozenset(
    {"pending", "running", "success", "failed", "skipped", "timeout"}
)


# ---------------------------------------------------------------------------
# SchemaStudy
# ---------------------------------------------------------------------------


class SchemaStudy(Base, TimestampMixin):
    """A single study run for a configured source."""

    __tablename__ = "schema_studies"

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        primary_key=True,
        default=uuid.uuid4,
        server_default=text("gen_random_uuid()"),
    )
    source_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("sources.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )

    # --- pipeline state ----------------------------------------------------
    state: Mapped[str] = mapped_column(
        String(64),
        nullable=False,
        default="QUEUED",
        server_default=text("'QUEUED'"),
        index=True,
    )

    # --- output ------------------------------------------------------------
    fingerprint: Mapped[str | None] = mapped_column(
        String(64),
        nullable=True,
        doc="sha256 hex digest; populated once the COLUMNS phase succeeds.",
    )
    schema_document_json: Mapped[dict | None] = mapped_column(
        JSONB,
        nullable=True,
        doc=(
            "Fully validated SchemaDocument as JSON; null until READY or "
            "READY_PARTIAL."
        ),
    )

    # --- metadata ----------------------------------------------------------
    agent_version: Mapped[str] = mapped_column(String(32), nullable=False)
    started_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        server_default=text("NOW()"),
    )
    finished_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True),
        nullable=True,
    )
    partial: Mapped[bool] = mapped_column(
        nullable=False,
        default=False,
        server_default=text("false"),
    )

    # --- denormalised last-error for fast triage ---------------------------
    last_error_phase: Mapped[str | None] = mapped_column(String(32), nullable=True)
    last_error_message: Mapped[str | None] = mapped_column(Text, nullable=True)

    # --- relationships -----------------------------------------------------
    phases: Mapped[list[SchemaStudyPhase]] = relationship(
        "SchemaStudyPhase",
        back_populates="study",
        cascade="all, delete-orphan",
        lazy="raise",
    )

    def __repr__(self) -> str:  # pragma: no cover
        return (
            f"<SchemaStudy id={self.id} source_id={self.source_id} "
            f"state={self.state!r}>"
        )


# ---------------------------------------------------------------------------
# SchemaStudyPhase
# ---------------------------------------------------------------------------


class SchemaStudyPhase(Base):
    """One phase row inside a study, used for live progress + retries."""

    __tablename__ = "schema_study_phases"

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        primary_key=True,
        default=uuid.uuid4,
        server_default=text("gen_random_uuid()"),
    )
    study_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("schema_studies.id", ondelete="CASCADE"),
        nullable=False,
    )
    phase: Mapped[str] = mapped_column(String(32), nullable=False)
    status: Mapped[str] = mapped_column(
        String(16),
        nullable=False,
        default="pending",
        server_default=text("'pending'"),
    )

    # --- error surface (admin-readable, NEVER includes connection strings)
    error_key: Mapped[str | None] = mapped_column(String(64), nullable=True)
    error_message: Mapped[str | None] = mapped_column(Text, nullable=True)

    # --- timing ------------------------------------------------------------
    started_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True),
        nullable=True,
    )
    finished_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True),
        nullable=True,
    )

    # --- live progress -----------------------------------------------------
    progress_n: Mapped[int | None] = mapped_column(Integer, nullable=True)
    progress_total: Mapped[int | None] = mapped_column(Integer, nullable=True)

    # --- relationships -----------------------------------------------------
    study: Mapped[SchemaStudy] = relationship(
        "SchemaStudy",
        back_populates="phases",
        lazy="raise",
    )

    __table_args__ = (
        Index("ix_schema_study_phases_study_phase", "study_id", "phase"),
    )

    def __repr__(self) -> str:  # pragma: no cover
        return (
            f"<SchemaStudyPhase id={self.id} study_id={self.study_id} "
            f"phase={self.phase!r} status={self.status!r}>"
        )
