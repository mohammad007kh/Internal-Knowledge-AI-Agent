"""Beat-scheduled task: poll sources whose ``next_sync_due_at`` has elapsed
and dispatch :pyfunc:`src.tasks.sync_source.sync_source` for each one.

Runs under Celery Beat (single replica — hard constraint) every 60 s.
Relies on the partial index ``ix_sources_sync_poll`` introduced in
migration 0018 for efficient polling.
"""
from __future__ import annotations

import asyncio
import logging
from datetime import datetime, timezone

from sqlalchemy import select, update
from sqlalchemy.exc import DBAPIError

from src.core.database import task_session
from src.models.enums import SourceStatus
from src.models.source import Source
from src.tasks import celery_app

logger = logging.getLogger(__name__)


@celery_app.task(name="tasks.check_scheduled_syncs")  # type: ignore[untyped-decorator]
def check_scheduled_syncs() -> int:
    """Poll sources where ``next_sync_due_at <= NOW()`` and kick off sync tasks.

    Returns
    -------
    int
        The number of sources scheduled for sync during this invocation.
    """
    return asyncio.run(_check_scheduled_syncs_async())


async def _check_scheduled_syncs_async() -> int:
    """Async worker body — separate to keep Celery entrypoint thin and testable."""
    now = datetime.now(tz=timezone.utc)

    # Per-task engine — see src.core.database.task_session for the rationale.
    async with task_session() as db:
        # Matches partial index ``ix_sources_sync_poll``:
        #   sync_mode = 'scheduled' AND next_sync_due_at <= now AND status != 'syncing'
        stmt = select(Source).where(
            Source.sync_mode == "scheduled",
            Source.next_sync_due_at.isnot(None),
            Source.next_sync_due_at <= now,
            Source.status != "syncing",
        )
        try:
            result = await db.execute(stmt)
        except DBAPIError as exc:
            # FX22: previously a tz mismatch on ``next_sync_due_at`` raised
            # here every 60 s and propagated as an unhandled task failure.
            # The column type is now TZ-aware, so this branch should only
            # fire on genuine DB outages (broker/asyncpg connectivity loss,
            # schema drift). Log + skip the tick rather than re-raising so
            # Beat keeps polling and a transient blip doesn't break the
            # entire scheduled-sync loop. We log only ``exc.__class__`` and
            # ``str(exc.orig)`` first line — never the SQL statement or
            # bind parameters, both of which can contain identifiers an
            # operator might consider sensitive.
            orig_msg = str(exc.orig).splitlines()[0] if exc.orig else exc.__class__.__name__
            logger.error(
                "check_scheduled_syncs query failed (%s); skipping tick: %s",
                exc.__class__.__name__,
                orig_msg[:200],
            )
            return 0

        due_sources = list(result.scalars().all())

        dispatched = 0
        for source in due_sources:
            try:
                celery_app.send_task("tasks.sync_source", args=[str(source.id)])
            except Exception as exc:  # pragma: no cover — broker failure path
                logger.error(
                    "Failed to dispatch sync for source %s: %s", source.id, exc
                )
                continue

            next_run = (
                _compute_next_run(source.sync_schedule, now)
                if source.sync_schedule
                else None
            )
            await db.execute(
                update(Source)
                .where(Source.id == source.id)
                .values(status=SourceStatus.SYNCING, next_sync_due_at=next_run)
            )
            dispatched += 1

        await db.commit()

    logger.info("check_scheduled_syncs dispatched %d sources", dispatched)
    return dispatched


def _compute_next_run(cron_expr: str, base: datetime) -> datetime | None:
    """Compute the next run time from a cron expression.

    Returns ``None`` if *cron_expr* is invalid; the caller stores ``None``
    into ``next_sync_due_at`` so the row is effectively parked until an
    admin corrects the schedule.
    """
    try:
        from croniter import croniter  # noqa: PLC0415

        itr = croniter(cron_expr, base)
        next_run: datetime = itr.get_next(datetime)
        return next_run
    except Exception as exc:  # pragma: no cover — croniter raises varied types
        logger.warning("Invalid cron expression '%s': %s", cron_expr, exc)
        return None
