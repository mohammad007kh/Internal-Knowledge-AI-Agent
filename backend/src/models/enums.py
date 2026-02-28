"""Shared application-level enums.

Implements T-040: Source ORM Models.

UserRole lives in src.models.user to avoid a circular-import chain;
only SourceType is defined here.
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
