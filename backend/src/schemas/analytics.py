"""Pydantic v2 response models for the redesigned ``/api/v1/analytics`` surface.

All models are strict (``extra='forbid'``) so the wire contract stays in
lock-step with the frontend ``frontend/src/lib/api/analytics.ts`` types.

The endpoints are admin-only aggregation reads:

  * ``GET /analytics/overview``       — :class:`AnalyticsOverview`
  * ``GET /analytics/chat-volume``    — list[:class:`ChatVolumePoint`]
  * ``GET /analytics/feedback-trend`` — list[:class:`FeedbackTrendPoint`]
  * ``GET /analytics/sync-activity``  — list[:class:`SyncActivityPoint`]
  * ``GET /analytics/source-health``  — :class:`SourceHealthBreakdown`
  * ``GET /analytics/schema-studies`` — :class:`SchemaStudiesBreakdown`
  * ``GET /analytics/needs-attention``— list[:class:`NeedsAttentionItem`]
"""

from __future__ import annotations

import uuid
from datetime import date as date_, datetime

from pydantic import BaseModel, ConfigDict, Field

_STRICT = ConfigDict(extra="forbid")


# ---------------------------------------------------------------------------
# Shared building blocks
# ---------------------------------------------------------------------------


class CountByKey(BaseModel):
    """A ``{key, count}`` bucket from a GROUP BY."""

    model_config = _STRICT
    # generic key column; concrete payloads alias it to type/status/state.
    key: str
    count: int


class TypeCount(BaseModel):
    model_config = _STRICT
    type: str
    count: int


class StatusCount(BaseModel):
    model_config = _STRICT
    status: str
    count: int


# ---------------------------------------------------------------------------
# /analytics/overview
# ---------------------------------------------------------------------------


class ChatMessagesKpi(BaseModel):
    """Chat-message volume in the requested window + delta vs the prior window."""

    model_config = _STRICT
    count: int = Field(description="chat_messages (any role) created in the range.")
    previous_count: int = Field(description="Same metric over the immediately preceding equal-length window.")
    delta_pct: float | None = Field(
        default=None,
        description="Percent change vs previous_count; null when previous_count == 0.",
    )


class FeedbackKpi(BaseModel):
    """Answer-feedback thumbs-up rate over the range."""

    model_config = _STRICT
    up: int
    down: int
    rated: int = Field(description="Messages with a non-null feedback_rating.")
    answered: int = Field(description="Assistant messages in the range (the denominator universe).")
    up_rate: float | None = Field(
        default=None,
        description="up / rated as a 0..1 fraction; null when rated == 0.",
    )


class SourcesKpi(BaseModel):
    """Active (non-deleted) source counts, plus a failed-connection tally."""

    model_config = _STRICT
    active: int = Field(description="sources WHERE deleted_at IS NULL.")
    failed_connections: int = Field(description="…of which connection_status = 'failed'.")
    by_connection_status: list[StatusCount] = Field(default_factory=list)


class SyncKpi(BaseModel):
    """Sync-job success rate over the range."""

    model_config = _STRICT
    total: int
    success: int
    failed: int
    success_rate: float | None = Field(
        default=None,
        description="success / total as a 0..1 fraction; null when total == 0.",
    )


class SchemaStudiesKpi(BaseModel):
    """Schema studies finished in the range, bucketed by terminal state."""

    model_config = _STRICT
    ready: int = Field(description="state IN ('READY', 'READY_PARTIAL').")
    failed: int = Field(description="state LIKE '%FAILED%'.")
    stale: int = Field(description="state = 'STALE' (none currently, reserved).")
    by_state: list[CountByKey] = Field(default_factory=list)


class AnalyticsOverview(BaseModel):
    """The six KPI scalars bundled into a single round-trip."""

    model_config = _STRICT
    range: str
    chat_messages: ChatMessagesKpi
    feedback: FeedbackKpi
    sources: SourcesKpi
    sync: SyncKpi
    schema_studies: SchemaStudiesKpi
    privileged_actions_today: int


# ---------------------------------------------------------------------------
# Time-series points (all gap-filled to a continuous daily series)
# ---------------------------------------------------------------------------


class ChatVolumePoint(BaseModel):
    model_config = _STRICT
    date: date_
    count: int


class FeedbackTrendPoint(BaseModel):
    model_config = _STRICT
    date: date_
    answered: int
    up: int
    down: int


class SyncActivityPoint(BaseModel):
    model_config = _STRICT
    date: date_
    success: int
    failed: int
    documents: int
    chunks: int


# ---------------------------------------------------------------------------
# /analytics/source-health
# ---------------------------------------------------------------------------


class SourceHealthBreakdown(BaseModel):
    model_config = _STRICT
    by_type: list[TypeCount] = Field(default_factory=list)
    by_connection_status: list[StatusCount] = Field(default_factory=list)
    by_status: list[StatusCount] = Field(default_factory=list)


# ---------------------------------------------------------------------------
# /analytics/schema-studies
# ---------------------------------------------------------------------------


class RecentSchemaFailure(BaseModel):
    model_config = _STRICT
    source_id: uuid.UUID
    source_name: str
    last_error_phase: str | None = None
    last_error_message: str | None = None
    finished_at: datetime | None = None


class SchemaStudiesBreakdown(BaseModel):
    model_config = _STRICT
    by_schema_status: list[StatusCount] = Field(default_factory=list)
    recent_failures: list[RecentSchemaFailure] = Field(default_factory=list)


# ---------------------------------------------------------------------------
# /analytics/needs-attention
# ---------------------------------------------------------------------------


class NeedsAttentionItem(BaseModel):
    model_config = _STRICT
    source_id: uuid.UUID
    name: str
    kind: str = Field(description="One of 'connection' | 'sync' | 'study'.")
    detail: str | None = None
