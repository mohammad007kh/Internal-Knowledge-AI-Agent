"""Pydantic schemas for SyncJob responses."""
from __future__ import annotations

import uuid
from datetime import datetime

from pydantic import BaseModel, ConfigDict

from src.models.enums import SyncStatus


class SyncJobResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    source_id: uuid.UUID
    status: SyncStatus
    started_at: datetime | None
    finished_at: datetime | None
    error_message: str | None
    documents_synced: int
    chunks_created: int
    created_at: datetime
    updated_at: datetime
