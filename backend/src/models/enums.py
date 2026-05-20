"""Shared application-level enums.

Implements T-040: Source ORM Models.
Implements T-060: SyncJob ORM Model.

UserRole lives in src.models.user to avoid a circular-import chain;
only SourceType and SyncStatus are defined here.
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
