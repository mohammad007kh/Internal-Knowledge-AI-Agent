"""Pydantic schemas for SyncJob responses."""
from __future__ import annotations

import uuid
from datetime import datetime

from pydantic import BaseModel, ConfigDict, Field, model_validator

from src.models.enums import SyncStatus


class SyncJobResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True, populate_by_name=True)

    id: uuid.UUID
    source_id: uuid.UUID
    status: SyncStatus
    started_at: datetime | None = None
    finished_at: datetime | None = None
    error_message: str | None = None
    documents_synced: int = 0
    chunks_created: int = 0
    created_at: datetime
    updated_at: datetime

    # Alias fields — kept in sync via model_validator
    completed_at: datetime | None = Field(None, description="Alias for finished_at")
    documents_indexed: int = Field(0, description="Alias for documents_synced")

    @model_validator(mode="after")
    def _sync_aliases(self) -> "SyncJobResponse":
        object.__setattr__(self, "completed_at", self.finished_at)
        object.__setattr__(self, "documents_indexed", self.documents_synced)
        return self


class SyncJobListResponse(BaseModel):
    """Paginated list of sync-job responses."""

    items: list[SyncJobResponse]
    total: int
    limit: int
    offset: int
