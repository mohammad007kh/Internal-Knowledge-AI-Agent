"""Analytics and detailed health-check router.

Endpoints:
  GET /admin/analytics/metrics      — aggregated platform metrics
  GET /admin/analytics/activity     — recent system health events
  GET /admin/analytics/queries      — daily query counts
  GET /admin/analytics/top-sources  — top sources by usage
  GET /health/detail                — detailed service health checks
"""

from __future__ import annotations

import asyncio
import time
from datetime import UTC, datetime, timedelta
from typing import Any

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

router = APIRouter()

AdminOnly = require_role(UserRole.admin)

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

    # active_sources
    active_sources_result = await db.execute(
        sa.select(sa.func.count()).select_from(Source).where(Source.is_active.is_(True))
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
    db: AsyncSession = Depends(get_db),
) -> dict[str, Any]:
    """Return concurrent health checks for database, Redis, and MinIO."""
    db_check, redis_check, minio_check = await asyncio.gather(
        _check_database(db),
        _check_redis(),
        _check_minio(),
    )
    return {"checks": [db_check, redis_check, minio_check]}
