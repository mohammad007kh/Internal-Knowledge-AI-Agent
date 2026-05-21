"""Shared application-level enums.

Implements T-040: Source ORM Models.
Implements T-060: SyncJob ORM Model.

UserRole lives in src.models.user to avoid a circular-import chain.
SourceType, SyncStatus, SourceStatus, and ConnectionStatus are defined here.
"""

from __future__ import annotations

import enum


class SourceType(enum.StrEnum):
    """Type of data source connected to the knowledge agent."""

    WEB_URL = "web_url"
    FILE_UPLOAD = "file_upload"
    DATABASE = "database"
    CONFLUENCE = "confluence"
    SHAREPOINT = "sharepoint"


class SyncStatus(enum.StrEnum):
    """Lifecycle states for a SyncJob run.

    ``CANCELLED`` is a fifth terminal state introduced by U16 for cooperative
    cancellation. A task marked CANCELLED has exited at a safe checkpoint —
    work completed so far is retained, but no further steps will run.
    """

    PENDING = "pending"
    RUNNING = "running"
    SUCCESS = "success"
    FAILED = "failed"
    CANCELLED = "cancelled"


class SourceStatus(enum.StrEnum):
    """Lifecycle states for ``Source.status`` — the column the chat picker and
    admin-approval gate inspect.

    A source starts ``PENDING`` at creation and flips to ``READY`` once the
    pipeline that owns its type finishes successfully (the studying agent for
    DB sources, a successful sync for file/web sources). ``SYNCING`` is stamped
    by the scheduled-sync sweep while a run is in flight.

    Backed by a plain ``String`` column (no Postgres ENUM), so values are
    compared as strings; this StrEnum is the single source of truth for the
    vocabulary, not a DB-enforced constraint.
    """

    PENDING = "pending"
    READY = "ready"
    SYNCING = "syncing"


class ConnectionStatus(enum.StrEnum):
    """Reachability of a source, orthogonal to ``Source.is_active`` (admin
    approval). ``is_active`` says "the admin approved this source";
    ``connection_status`` says "the system can currently reach it".

    Backed by a plain ``String`` column; this StrEnum is the canonical
    vocabulary. ``DEGRADED`` is reserved for partial reachability and is not
    emitted by the current probe path (which only sets healthy/failed/unknown).
    """

    HEALTHY = "healthy"
    DEGRADED = "degraded"
    FAILED = "failed"
    UNKNOWN = "unknown"
