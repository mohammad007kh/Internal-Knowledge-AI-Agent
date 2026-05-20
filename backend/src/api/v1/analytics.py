"""Analytics and detailed health-check router.

Endpoints:
  GET /admin/analytics/metrics      — aggregated platform metrics (legacy)
  GET /admin/analytics/activity     — recent system health events (legacy)
  GET /admin/analytics/queries      — daily query counts (legacy)
  GET /admin/analytics/top-sources  — top sources by usage (legacy)
  GET /health/detail                — detailed service health checks

  --- /admin/analytics redesign (v2) -----------------------------------
  GET /analytics/overview           — six KPI scalars in one round-trip
  GET /analytics/chat-volume        — daily user-message counts
  GET /analytics/feedback-trend     — daily answered / up / down
  GET /analytics/sync-activity      — daily sync success/failed + docs/chunks
  GET /analytics/source-health      — by type / connection / status
  GET /analytics/schema-studies     — by schema_status + recent failures
  GET /analytics/needs-attention    — ≤8 sources that need triage
"""

from __future__ import annotations

import asyncio
import time
from datetime import UTC, datetime, timedelta
from typing import Annotated, Any

import sqlalchemy as sa
from fastapi import APIRouter, Depends, Query
from sqlalchemy.ext.asyncio import AsyncSession

from src.core.database import get_db
from src.core.deps import require_role
from src.core.redis import redis_client
from src.models.chat import ChatMessage, ChatSession, MessageRole
from src.models.document import Document
from src.models.source import Source
from src.models.system_health_event import SystemHealthEvent
from src.models.user import User, UserRole
from src.repositories.analytics_repository import AnalyticsRepository, resolve_range
from src.schemas.analytics import (
    AnalyticsOverview,
    ChatMessagesKpi,
    ChatVolumePoint,
    CountByKey,
    FeedbackKpi,
    FeedbackTrendPoint,
    NeedsAttentionItem,
    RecentSchemaFailure,
    SchemaStudiesBreakdown,
    SchemaStudiesKpi,
    SourceHealthBreakdown,
    SourcesKpi,
    StatusCount,
    SyncActivityPoint,
    SyncKpi,
    TypeCount,
)

router = APIRouter()

AdminOnly = require_role(UserRole.admin)

# range query param — shared across the v2 time-series + delta endpoints.
RangeParam = Annotated[
    str,
    Query(pattern="^(24h|7d|30d|90d)$", description="Aggregation window."),
]


def _pct(numerator: int, denominator: int) -> float | None:
    """Round((num - prev) / prev * 100) — null when denominator is zero."""
    if denominator == 0:
        return None
    return round((numerator - denominator) / denominator * 100.0, 1)


def _rate(numerator: int, denominator: int) -> float | None:
    """numerator / denominator as a 0..1 fraction; null when denominator is 0."""
    if denominator == 0:
        return None
    return round(numerator / denominator, 4)


def _analytics_repo(db: AsyncSession = Depends(get_db)) -> AnalyticsRepository:
    return AnalyticsRepository(db)

# ---------------------------------------------------------------------------
# Severity mapping helper
# ---------------------------------------------------------------------------

_SEVERITY_MAP: dict[str, str] = {
    "crash": "error",
    "restart_failed": "error",
    "restart_attempt": "warning",
}


def _event_severity(event_type: str) -> str:
    return _SEVERITY_MAP.get(event_type, "info")


# ---------------------------------------------------------------------------
# 1. Metrics
# ---------------------------------------------------------------------------


@router.get("/admin/analytics/metrics", summary="Platform metrics overview")
async def get_metrics(
    _: User = Depends(AdminOnly),
    db: AsyncSession = Depends(get_db),
) -> dict[str, Any]:
    """Return aggregated platform metrics for the admin dashboard."""
    now = datetime.now(UTC)
    seven_days_ago = now - timedelta(days=7)

    # total_users
    total_users_result = await db.execute(
        sa.select(sa.func.count()).select_from(User).where(User.deleted_at.is_(None))
    )
    total_users: int = total_users_result.scalar_one()

    # active_users_7d — users with last_login_at in last 7 days
    try:
        active_users_result = await db.execute(
            sa.select(sa.func.count())
            .select_from(User)
            .where(
                User.deleted_at.is_(None),
                User.last_login_at >= seven_days_ago,  # type: ignore[attr-defined]
            )
        )
        active_users_7d: int = active_users_result.scalar_one()
    except Exception:  # noqa: BLE001
        active_users_7d = 0

    # active_sources — non-deleted sources currently in the system. The
    # historical filter was ``is_active = TRUE`` (which previously meant
    # "not deleted"); after the is_active repurpose ("approved/available")
    # the equivalent "exists" filter is ``deleted_at IS NULL``.
    active_sources_result = await db.execute(
        sa.select(sa.func.count()).select_from(Source).where(Source.deleted_at.is_(None))
    )
    active_sources: int = active_sources_result.scalar_one()

    # total_documents
    total_docs_result = await db.execute(
        sa.select(sa.func.count()).select_from(Document).where(Document.is_active.is_(True))
    )
    total_documents: int = total_docs_result.scalar_one()

    # queries_7d — chat_messages with role='user' in last 7 days
    queries_result = await db.execute(
        sa.select(sa.func.count())
        .select_from(ChatMessage)
        .where(
            ChatMessage.role == MessageRole.USER,
            ChatMessage.created_at >= seven_days_ago,
        )
    )
    queries_7d: int = queries_result.scalar_one()

    return {
        "total_users": total_users,
        "active_users_7d": active_users_7d,
        "active_sources": active_sources,
        "total_documents": total_documents,
        "queries_7d": queries_7d,
        "avg_response_time_ms": 0,
    }


# ---------------------------------------------------------------------------
# 2. Activity — system health events
# ---------------------------------------------------------------------------


@router.get("/admin/analytics/activity", summary="Recent system activity events")
async def get_activity(
    limit: int = Query(20, ge=1, le=100),
    _: User = Depends(AdminOnly),
    db: AsyncSession = Depends(get_db),
) -> list[dict[str, Any]]:
    """Return recent system health events ordered by timestamp descending."""
    result = await db.execute(
        sa.select(SystemHealthEvent)
        .order_by(SystemHealthEvent.timestamp.desc())
        .limit(limit)
    )
    events = result.scalars().all()
    return [
        {
            "id": str(e.id),
            "message": e.error_detail or e.event_type,
            "severity": _event_severity(e.event_type),
            "created_at": e.timestamp.isoformat(),
        }
        for e in events
    ]


# ---------------------------------------------------------------------------
# 3. Queries — daily query counts
# ---------------------------------------------------------------------------


@router.get("/admin/analytics/queries", summary="Daily query counts")
async def get_query_counts(
    days: int = Query(14, ge=1, le=90),
    _: User = Depends(AdminOnly),
    db: AsyncSession = Depends(get_db),
) -> list[dict[str, Any]]:
    """Return per-day count of user queries over the last *days* days."""
    since = datetime.now(UTC) - timedelta(days=days)
    result = await db.execute(
        sa.select(
            sa.cast(ChatMessage.created_at, sa.Date).label("date"),
            sa.func.count().label("count"),
        )
        .where(
            ChatMessage.role == MessageRole.USER,
            ChatMessage.created_at >= since,
        )
        .group_by(sa.cast(ChatMessage.created_at, sa.Date))
        .order_by(sa.cast(ChatMessage.created_at, sa.Date).asc())
    )
    rows = result.all()
    return [{"date": str(row.date), "count": row.count} for row in rows]


# ---------------------------------------------------------------------------
# 4. Top sources
# ---------------------------------------------------------------------------


@router.get("/admin/analytics/top-sources", summary="Top sources by query usage")
async def get_top_sources(
    limit: int = Query(10, ge=1, le=50),
    _: User = Depends(AdminOnly),
    db: AsyncSession = Depends(get_db),
) -> list[dict[str, Any]]:
    """Return the most-referenced sources across chat sessions."""
    sql = sa.text(
        """
        SELECT s.id AS source_id, s.name AS source_name, COUNT(*) AS query_count
        FROM chat_sessions cs,
             jsonb_array_elements_text(cs.source_ids) AS sid
        JOIN sources s ON s.id::text = sid
        GROUP BY s.id, s.name
        ORDER BY query_count DESC
        LIMIT :limit
        """
    )
    result = await db.execute(sql, {"limit": limit})
    rows = result.mappings().all()
    return [
        {
            "source_id": str(row["source_id"]),
            "source_name": row["source_name"],
            "query_count": row["query_count"],
        }
        for row in rows
    ]


# ---------------------------------------------------------------------------
# 4b. /admin/analytics redesign (v2) — aggregation endpoints
# ---------------------------------------------------------------------------


@router.get(
    "/analytics/overview",
    summary="Analytics overview — six KPI scalars",
    response_model=AnalyticsOverview,
)
async def analytics_overview(
    range: RangeParam = "7d",
    _: User = Depends(AdminOnly),
    repo: AnalyticsRepository = Depends(_analytics_repo),
) -> AnalyticsOverview:
    """Bundle the six dashboard KPIs into a single round-trip."""
    window = resolve_range(range)

    chat = await repo.chat_messages_kpi(window)
    fb = await repo.feedback_kpi(window)
    src = await repo.sources_kpi()
    syn = await repo.sync_kpi(window)
    studies = await repo.schema_studies_kpi(window)
    privileged = await repo.privileged_actions_today()

    return AnalyticsOverview(
        range=range,
        chat_messages=ChatMessagesKpi(
            count=chat["count"],
            previous_count=chat["previous_count"],
            delta_pct=_pct(chat["count"], chat["previous_count"]),
        ),
        feedback=FeedbackKpi(
            up=fb["up"],
            down=fb["down"],
            rated=fb["rated"],
            answered=fb["answered"],
            up_rate=_rate(fb["up"], fb["rated"]),
        ),
        sources=SourcesKpi(
            active=src["active"],
            failed_connections=src["failed_connections"],
            by_connection_status=[StatusCount(**s) for s in src["by_connection_status"]],
        ),
        sync=SyncKpi(
            total=syn["total"],
            success=syn["success"],
            failed=syn["failed"],
            success_rate=_rate(syn["success"], syn["total"]),
        ),
        schema_studies=SchemaStudiesKpi(
            ready=studies["ready"],
            failed=studies["failed"],
            stale=studies["stale"],
            by_state=[CountByKey(**b) for b in studies["by_state"]],
        ),
        privileged_actions_today=privileged,
    )


@router.get(
    "/analytics/chat-volume",
    summary="Daily user-message counts (gap-filled)",
    response_model=list[ChatVolumePoint],
)
async def analytics_chat_volume(
    range: RangeParam = "30d",
    _: User = Depends(AdminOnly),
    repo: AnalyticsRepository = Depends(_analytics_repo),
) -> list[ChatVolumePoint]:
    rows = await repo.chat_volume_daily(resolve_range(range))
    return [ChatVolumePoint(**r) for r in rows]


@router.get(
    "/analytics/feedback-trend",
    summary="Daily answered / thumbs-up / thumbs-down (gap-filled)",
    response_model=list[FeedbackTrendPoint],
)
async def analytics_feedback_trend(
    range: RangeParam = "30d",
    _: User = Depends(AdminOnly),
    repo: AnalyticsRepository = Depends(_analytics_repo),
) -> list[FeedbackTrendPoint]:
    rows = await repo.feedback_trend_daily(resolve_range(range))
    return [FeedbackTrendPoint(**r) for r in rows]


@router.get(
    "/analytics/sync-activity",
    summary="Daily sync success/failed + documents/chunks (gap-filled)",
    response_model=list[SyncActivityPoint],
)
async def analytics_sync_activity(
    range: RangeParam = "30d",
    _: User = Depends(AdminOnly),
    repo: AnalyticsRepository = Depends(_analytics_repo),
) -> list[SyncActivityPoint]:
    rows = await repo.sync_activity_daily(resolve_range(range))
    return [SyncActivityPoint(**r) for r in rows]


@router.get(
    "/analytics/source-health",
    summary="Source counts by type / connection-status / status",
    response_model=SourceHealthBreakdown,
)
async def analytics_source_health(
    _: User = Depends(AdminOnly),
    repo: AnalyticsRepository = Depends(_analytics_repo),
) -> SourceHealthBreakdown:
    data = await repo.source_health()
    return SourceHealthBreakdown(
        by_type=[TypeCount(**t) for t in data["by_type"]],
        by_connection_status=[StatusCount(**s) for s in data["by_connection_status"]],
        by_status=[StatusCount(**s) for s in data["by_status"]],
    )


@router.get(
    "/analytics/schema-studies",
    summary="schema_status breakdown + recent failed studies",
    response_model=SchemaStudiesBreakdown,
)
async def analytics_schema_studies(
    _: User = Depends(AdminOnly),
    repo: AnalyticsRepository = Depends(_analytics_repo),
) -> SchemaStudiesBreakdown:
    data = await repo.schema_studies_breakdown()
    return SchemaStudiesBreakdown(
        by_schema_status=[StatusCount(**s) for s in data["by_schema_status"]],
        recent_failures=[RecentSchemaFailure(**r) for r in data["recent_failures"]],
    )


@router.get(
    "/analytics/needs-attention",
    summary="Sources that need triage (failed connection / sync / study)",
    response_model=list[NeedsAttentionItem],
)
async def analytics_needs_attention(
    _: User = Depends(AdminOnly),
    repo: AnalyticsRepository = Depends(_analytics_repo),
) -> list[NeedsAttentionItem]:
    rows = await repo.needs_attention(limit=8)
    return [NeedsAttentionItem(**r) for r in rows]


# ---------------------------------------------------------------------------
# 5. Detailed health check
# ---------------------------------------------------------------------------


async def _check_database(db: AsyncSession) -> dict[str, Any]:
    """Check database connectivity and measure latency."""
    t0 = time.perf_counter()
    try:
        await db.execute(sa.text("SELECT 1"))
        latency_ms = (time.perf_counter() - t0) * 1000
        return {"service": "database", "status": "ok", "latency_ms": round(latency_ms, 2)}
    except Exception as exc:  # noqa: BLE001
        latency_ms = (time.perf_counter() - t0) * 1000
        return {
            "service": "database",
            "status": "error",
            "latency_ms": round(latency_ms, 2),
            "detail": str(exc),
        }


async def _check_redis() -> dict[str, Any]:
    """Check Redis connectivity and measure latency."""
    t0 = time.perf_counter()
    try:
        if redis_client is None:
            return {"service": "redis", "status": "error", "latency_ms": 0.0, "detail": "not initialised"}
        await redis_client.ping()
        latency_ms = (time.perf_counter() - t0) * 1000
        return {"service": "redis", "status": "ok", "latency_ms": round(latency_ms, 2)}
    except Exception as exc:  # noqa: BLE001
        latency_ms = (time.perf_counter() - t0) * 1000
        return {
            "service": "redis",
            "status": "error",
            "latency_ms": round(latency_ms, 2),
            "detail": str(exc),
        }


async def _check_minio() -> dict[str, Any]:
    """Check MinIO connectivity and measure latency."""
    from src.core.storage import minio_client  # noqa: PLC0415

    t0 = time.perf_counter()
    try:
        # MagicMock stub or real MinIO client — call list_buckets
        result = minio_client.list_buckets()
        # If async, await it
        if asyncio.iscoroutine(result):
            await result
        latency_ms = (time.perf_counter() - t0) * 1000
        return {"service": "minio", "status": "ok", "latency_ms": round(latency_ms, 2)}
    except Exception as exc:  # noqa: BLE001
        latency_ms = (time.perf_counter() - t0) * 1000
        return {
            "service": "minio",
            "status": "error",
            "latency_ms": round(latency_ms, 2),
            "detail": str(exc),
        }


@router.get("/health/detail", summary="Detailed service health checks")
async def health_detail(
    _: User = Depends(AdminOnly),
    db: AsyncSession = Depends(get_db),
) -> dict[str, Any]:
    """Return concurrent health checks for database, Redis, and MinIO."""
    db_check, redis_check, minio_check = await asyncio.gather(
        _check_database(db),
        _check_redis(),
        _check_minio(),
    )
    return {"checks": [db_check, redis_check, minio_check]}
