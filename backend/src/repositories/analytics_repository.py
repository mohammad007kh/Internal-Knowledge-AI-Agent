"""Read-only aggregation queries backing the ``/api/v1/analytics`` surface.

Constructed per-request with ``AnalyticsRepository(db)`` where ``db`` is the
``Depends(get_db)`` session.  Every method returns plain Python primitives /
dicts so the route handlers stay thin — Pydantic shaping happens in the
router.

Gap-filling: the daily time-series helpers (``chat_volume``, ``feedback_trend``,
``sync_activity``) return a *continuous* day-by-day list from ``since`` to
*today* inclusive, inserting zero rows where the DB had no data. This keeps
the canvas charts on the frontend from drawing a jagged/discontinuous series.
"""

from __future__ import annotations

from datetime import UTC, date, datetime, timedelta

import sqlalchemy as sa
from sqlalchemy.ext.asyncio import AsyncSession

from src.models.admin_audit_log import AdminAuditLog
from src.models.chat import ChatMessage, MessageRole
from src.models.enums import SyncStatus
from src.models.schema_study import SchemaStudy
from src.models.source import Source
from src.models.sync_job import SyncJob

# range token → timedelta. Mirrored on the frontend (analytics.ts).
RANGE_TO_DELTA: dict[str, timedelta] = {
    "24h": timedelta(hours=24),
    "7d": timedelta(days=7),
    "30d": timedelta(days=30),
    "90d": timedelta(days=90),
}

_TERMINAL_READY = ("READY", "READY_PARTIAL")


def resolve_range(token: str) -> timedelta:
    """Map a ``range`` query token to its window; defaults to 7d for junk."""
    return RANGE_TO_DELTA.get(token, RANGE_TO_DELTA["7d"])


def _utcnow() -> datetime:
    return datetime.now(UTC)


def _day_series(since: datetime, until: datetime) -> list[date]:
    """Inclusive list of UTC dates from ``since`` to ``until``."""
    start = since.date()
    end = until.date()
    out: list[date] = []
    cur = start
    while cur <= end:
        out.append(cur)
        cur = cur + timedelta(days=1)
    return out


class AnalyticsRepository:
    """Aggregation queries for the admin analytics dashboard."""

    def __init__(self, session: AsyncSession) -> None:
        self._db = session

    # ------------------------------------------------------------------ #
    # Overview KPIs                                                       #
    # ------------------------------------------------------------------ #

    async def chat_messages_kpi(self, window: timedelta) -> dict[str, int]:
        """chat_messages count in the window + count in the prior equal window."""
        now = _utcnow()
        since = now - window
        prior_since = since - window

        cur = (
            await self._db.execute(
                sa.select(sa.func.count())
                .select_from(ChatMessage)
                .where(ChatMessage.created_at >= since)
            )
        ).scalar_one()
        prev = (
            await self._db.execute(
                sa.select(sa.func.count())
                .select_from(ChatMessage)
                .where(
                    ChatMessage.created_at >= prior_since,
                    ChatMessage.created_at < since,
                )
            )
        ).scalar_one()
        return {"count": int(cur), "previous_count": int(prev)}

    async def feedback_kpi(self, window: timedelta) -> dict[str, int]:
        """Thumbs-up/down counts + assistant-message universe over the window."""
        since = _utcnow() - window
        row = (
            await self._db.execute(
                sa.select(
                    sa.func.count()
                    .filter(ChatMessage.role == MessageRole.ASSISTANT)
                    .label("answered"),
                    sa.func.count()
                    .filter(ChatMessage.feedback_rating.is_not(None))
                    .label("rated"),
                    sa.func.count()
                    .filter(ChatMessage.feedback_rating == 1)
                    .label("up"),
                    sa.func.count()
                    .filter(ChatMessage.feedback_rating == -1)
                    .label("down"),
                )
                .select_from(ChatMessage)
                .where(ChatMessage.created_at >= since)
            )
        ).one()
        return {
            "answered": int(row.answered),
            "rated": int(row.rated),
            "up": int(row.up),
            "down": int(row.down),
        }

    async def sources_kpi(self) -> dict:
        """Active (non-deleted) source counts grouped by connection_status."""
        rows = (
            await self._db.execute(
                sa.select(Source.connection_status, sa.func.count())
                .where(Source.deleted_at.is_(None))
                .group_by(Source.connection_status)
            )
        ).all()
        by_status = [{"status": (s or "unknown"), "count": int(c)} for s, c in rows]
        active = sum(item["count"] for item in by_status)
        failed = sum(item["count"] for item in by_status if item["status"] == "failed")
        return {
            "active": active,
            "failed_connections": failed,
            "by_connection_status": by_status,
        }

    async def sync_kpi(self, window: timedelta) -> dict[str, int]:
        """Sync-job counts grouped by status over the window."""
        since = _utcnow() - window
        rows = (
            await self._db.execute(
                sa.select(SyncJob.status, sa.func.count())
                .where(SyncJob.created_at >= since)
                .group_by(SyncJob.status)
            )
        ).all()
        counts: dict[str, int] = {}
        for status, c in rows:
            # status is the SyncStatus enum member; normalise to its value.
            key = status.value if hasattr(status, "value") else str(status)
            counts[key] = counts.get(key, 0) + int(c)
        total = sum(counts.values())
        return {
            "total": total,
            "success": counts.get("success", 0),
            "failed": counts.get("failed", 0),
        }

    async def schema_studies_kpi(self, window: timedelta) -> dict:
        """schema_studies finished in the window grouped by terminal state."""
        since = _utcnow() - window
        rows = (
            await self._db.execute(
                sa.select(SchemaStudy.state, sa.func.count())
                .where(SchemaStudy.finished_at.is_not(None))
                .where(SchemaStudy.finished_at >= since)
                .group_by(SchemaStudy.state)
            )
        ).all()
        by_state = [{"key": str(state), "count": int(c)} for state, c in rows]
        ready = sum(b["count"] for b in by_state if b["key"] in _TERMINAL_READY)
        failed = sum(b["count"] for b in by_state if b["key"].endswith("FAILED"))
        stale = sum(b["count"] for b in by_state if b["key"] == "STALE")
        return {"ready": ready, "failed": failed, "stale": stale, "by_state": by_state}

    async def privileged_actions_today(self) -> int:
        """admin_audit_log rows created since 00:00 UTC today."""
        start_of_day = datetime.combine(_utcnow().date(), datetime.min.time(), tzinfo=UTC)
        return int(
            (
                await self._db.execute(
                    sa.select(sa.func.count())
                    .select_from(AdminAuditLog)
                    .where(AdminAuditLog.created_at >= start_of_day)
                )
            ).scalar_one()
        )

    # ------------------------------------------------------------------ #
    # Daily time series (gap-filled)                                      #
    # ------------------------------------------------------------------ #

    async def chat_volume_daily(self, window: timedelta) -> list[dict]:
        """[{date, count}] — user messages per day, zero-filled."""
        now = _utcnow()
        since = now - window
        day_col = sa.func.date_trunc("day", ChatMessage.created_at)
        rows = (
            await self._db.execute(
                sa.select(day_col.label("d"), sa.func.count().label("c"))
                .where(ChatMessage.role == MessageRole.USER)
                .where(ChatMessage.created_at >= since)
                .group_by(day_col)
            )
        ).all()
        seen = {self._as_date(r.d): int(r.c) for r in rows}
        return [{"date": d, "count": seen.get(d, 0)} for d in _day_series(since, now)]

    async def feedback_trend_daily(self, window: timedelta) -> list[dict]:
        """[{date, answered, up, down}] over assistant messages, zero-filled."""
        now = _utcnow()
        since = now - window
        day_col = sa.func.date_trunc("day", ChatMessage.created_at)
        rows = (
            await self._db.execute(
                sa.select(
                    day_col.label("d"),
                    sa.func.count().label("answered"),
                    sa.func.count().filter(ChatMessage.feedback_rating == 1).label("up"),
                    sa.func.count().filter(ChatMessage.feedback_rating == -1).label("down"),
                )
                .where(ChatMessage.role == MessageRole.ASSISTANT)
                .where(ChatMessage.created_at >= since)
                .group_by(day_col)
            )
        ).all()
        seen = {
            self._as_date(r.d): {"answered": int(r.answered), "up": int(r.up), "down": int(r.down)}
            for r in rows
        }
        out: list[dict] = []
        for d in _day_series(since, now):
            v = seen.get(d, {"answered": 0, "up": 0, "down": 0})
            out.append({"date": d, **v})
        return out

    async def sync_activity_daily(self, window: timedelta) -> list[dict]:
        """[{date, success, failed, documents, chunks}] per day, zero-filled."""
        now = _utcnow()
        since = now - window
        day_col = sa.func.date_trunc("day", SyncJob.created_at)
        rows = (
            await self._db.execute(
                sa.select(
                    day_col.label("d"),
                    sa.func.count()
                    .filter(SyncJob.status == SyncStatus.SUCCESS)
                    .label("success"),
                    sa.func.count()
                    .filter(SyncJob.status == SyncStatus.FAILED)
                    .label("failed"),
                    sa.func.coalesce(sa.func.sum(SyncJob.documents_synced), 0).label("documents"),
                    sa.func.coalesce(sa.func.sum(SyncJob.chunks_created), 0).label("chunks"),
                )
                .where(SyncJob.created_at >= since)
                .group_by(day_col)
            )
        ).all()
        seen = {
            self._as_date(r.d): {
                "success": int(r.success),
                "failed": int(r.failed),
                "documents": int(r.documents),
                "chunks": int(r.chunks),
            }
            for r in rows
        }
        out: list[dict] = []
        for d in _day_series(since, now):
            v = seen.get(
                d, {"success": 0, "failed": 0, "documents": 0, "chunks": 0}
            )
            out.append({"date": d, **v})
        return out

    # ------------------------------------------------------------------ #
    # Point-in-time snapshots                                             #
    # ------------------------------------------------------------------ #

    async def source_health(self) -> dict:
        """Three GROUP BYs over non-deleted sources."""
        by_type = (
            await self._db.execute(
                sa.select(Source.source_type, sa.func.count())
                .where(Source.deleted_at.is_(None))
                .group_by(Source.source_type)
            )
        ).all()
        by_conn = (
            await self._db.execute(
                sa.select(Source.connection_status, sa.func.count())
                .where(Source.deleted_at.is_(None))
                .group_by(Source.connection_status)
            )
        ).all()
        by_status = (
            await self._db.execute(
                sa.select(Source.status, sa.func.count())
                .where(Source.deleted_at.is_(None))
                .group_by(Source.status)
            )
        ).all()
        return {
            "by_type": [
                {"type": (t.value if hasattr(t, "value") else str(t)), "count": int(c)}
                for t, c in by_type
            ],
            "by_connection_status": [
                {"status": (s or "unknown"), "count": int(c)} for s, c in by_conn
            ],
            "by_status": [{"status": (s or "unknown"), "count": int(c)} for s, c in by_status],
        }

    async def schema_studies_breakdown(self) -> dict:
        """sources.schema_status GROUP BY + the 5 most-recent failed studies."""
        by_status = (
            await self._db.execute(
                sa.select(Source.schema_status, sa.func.count())
                .where(Source.deleted_at.is_(None))
                .group_by(Source.schema_status)
            )
        ).all()
        recent = (
            await self._db.execute(
                sa.select(
                    SchemaStudy.source_id,
                    Source.name,
                    SchemaStudy.last_error_phase,
                    SchemaStudy.last_error_message,
                    SchemaStudy.finished_at,
                )
                .join(Source, Source.id == SchemaStudy.source_id)
                .where(SchemaStudy.state.like("%FAILED%"))
                .order_by(SchemaStudy.finished_at.desc().nullslast())
                .limit(5)
            )
        ).all()
        return {
            "by_schema_status": [
                {"status": (s or "—"), "count": int(c)} for s, c in by_status
            ],
            "recent_failures": [
                {
                    "source_id": r.source_id,
                    "source_name": r.name,
                    "last_error_phase": r.last_error_phase,
                    "last_error_message": r.last_error_message,
                    "finished_at": r.finished_at,
                }
                for r in recent
            ],
        }

    async def needs_attention(self, limit: int = 8) -> list[dict]:
        """Up to ``limit`` rows: failed connections, failed last-sync, failed last-study."""
        items: list[dict] = []
        order_ts: list[datetime | None] = []

        # 1) Sources with connection_status = 'failed'.
        conn_rows = (
            await self._db.execute(
                sa.select(
                    Source.id,
                    Source.name,
                    Source.connection_last_error,
                    Source.connection_last_checked_at,
                )
                .where(Source.deleted_at.is_(None))
                .where(Source.connection_status == "failed")
            )
        ).all()
        for r in conn_rows:
            items.append(
                {
                    "source_id": r.id,
                    "name": r.name,
                    "kind": "connection",
                    "detail": r.connection_last_error,
                }
            )
            order_ts.append(r.connection_last_checked_at)

        # 2) Sources whose most-recent sync_jobs row is status='failed'.
        latest_sync = (
            sa.select(
                SyncJob.source_id.label("source_id"),
                SyncJob.status.label("status"),
                SyncJob.error_message.label("error_message"),
                SyncJob.created_at.label("created_at"),
            )
            .distinct(SyncJob.source_id)
            .order_by(SyncJob.source_id, SyncJob.created_at.desc())
            .subquery()
        )
        sync_rows = (
            await self._db.execute(
                sa.select(
                    Source.id,
                    Source.name,
                    latest_sync.c.error_message,
                    latest_sync.c.created_at,
                )
                .join(latest_sync, latest_sync.c.source_id == Source.id)
                .where(Source.deleted_at.is_(None))
                .where(latest_sync.c.status == SyncStatus.FAILED)
            )
        ).all()
        seen_ids = {it["source_id"] for it in items}
        for r in sync_rows:
            if r.id in seen_ids:
                continue
            items.append(
                {
                    "source_id": r.id,
                    "name": r.name,
                    "kind": "sync",
                    "detail": r.error_message,
                }
            )
            order_ts.append(r.created_at)
            seen_ids.add(r.id)

        # 3) Sources whose latest schema_studies row is *_FAILED.
        latest_study = (
            sa.select(
                SchemaStudy.source_id.label("source_id"),
                SchemaStudy.state.label("state"),
                SchemaStudy.last_error_phase.label("last_error_phase"),
                SchemaStudy.finished_at.label("finished_at"),
            )
            .distinct(SchemaStudy.source_id)
            .order_by(SchemaStudy.source_id, SchemaStudy.created_at.desc())
            .subquery()
        )
        study_rows = (
            await self._db.execute(
                sa.select(
                    Source.id,
                    Source.name,
                    latest_study.c.last_error_phase,
                    latest_study.c.finished_at,
                )
                .join(latest_study, latest_study.c.source_id == Source.id)
                .where(Source.deleted_at.is_(None))
                .where(latest_study.c.state.like("%FAILED%"))
            )
        ).all()
        for r in study_rows:
            if r.id in seen_ids:
                continue
            items.append(
                {
                    "source_id": r.id,
                    "name": r.name,
                    "kind": "study",
                    "detail": r.last_error_phase,
                }
            )
            order_ts.append(r.finished_at)
            seen_ids.add(r.id)

        # Sort by most-recent failure timestamp (None last) and trim.
        paired = list(zip(items, order_ts, strict=True))
        paired.sort(
            key=lambda p: (p[1] is None, -(p[1].timestamp() if p[1] is not None else 0))
        )
        return [it for it, _ in paired[:limit]]

    # ------------------------------------------------------------------ #
    # Helpers                                                             #
    # ------------------------------------------------------------------ #

    @staticmethod
    def _as_date(value: datetime | date) -> date:
        if isinstance(value, datetime):
            return value.date()
        return value
