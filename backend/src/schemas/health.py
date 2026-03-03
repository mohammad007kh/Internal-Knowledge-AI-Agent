"""Pydantic schemas for worker health — FR-033."""
from __future__ import annotations

from pydantic import BaseModel


class WorkerEventCount(BaseModel):
    """Aggregated count of a specific event type for one component."""

    component: str
    event_type: str
    count: int


class WorkerHealthSummary(BaseModel):
    """Top-level response for GET /health/workers."""

    events: list[WorkerEventCount]
