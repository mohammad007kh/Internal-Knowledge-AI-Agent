"""Worker health supervisor service — FR-033.

Tracks component crashes, drives restart logic, and exposes an aggregated
health summary for the admin API.

Module-level state
------------------
``_COMPONENT_ATTEMPT_CACHE``  maps *component_name* → last attempted restart
    count.  It is intentionally **not** persisted to the database so that a
    process restart always begins with a clean slate.  The ``reset_attempt_counter``
    helper exists purely for test isolation.

Constants
---------
``MAX_RESTART_ATTEMPTS``  — maximum restart attempts before ``restart_failed``
    is recorded and no further attempts are made (default: 3).
"""
from __future__ import annotations

import logging
import uuid
from datetime import datetime, timezone

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from src.models.system_health_event import SystemHealthEvent
from src.schemas.health import WorkerEventCount, WorkerHealthSummary

log = logging.getLogger(__name__)

MAX_RESTART_ATTEMPTS: int = 3

# module-level in-memory counter; keyed by component_name
_COMPONENT_ATTEMPT_CACHE: dict[str, int] = {}


# ---------------------------------------------------------------------------
# Internal helpers
# ---------------------------------------------------------------------------


async def _write_event(
    db: AsyncSession,
    *,
    component_name: str,
    event_type: str,
    attempt_number: int = 0,
    error_detail: str | None = None,
) -> SystemHealthEvent:
    """INSERT a new SystemHealthEvent row and flush (no commit)."""
    event = SystemHealthEvent(
        id=uuid.uuid4(),
        component_name=component_name,
        event_type=event_type,
        attempt_number=attempt_number,
        error_detail=error_detail,
        timestamp=datetime.now(timezone.utc),
    )
    db.add(event)
    await db.flush()
    return event


async def _attempt_restart(
    db: AsyncSession,
    component_name: str,
    attempt_number: int,
    error_detail: str | None,
) -> None:
    """Record a restart_attempt row and update the in-memory cache."""
    await _write_event(
        db,
        component_name=component_name,
        event_type="restart_attempt",
        attempt_number=attempt_number,
        error_detail=error_detail,
    )
    _COMPONENT_ATTEMPT_CACHE[component_name] = attempt_number
    log.info(
        "Restart attempt %d/%d for component '%s'",
        attempt_number,
        MAX_RESTART_ATTEMPTS,
        component_name,
    )


async def _record_restart_failed(
    db: AsyncSession,
    component_name: str,
    error_detail: str | None,
) -> None:
    """Record a restart_failed row (attempt_number == MAX_RESTART_ATTEMPTS)."""
    await _write_event(
        db,
        component_name=component_name,
        event_type="restart_failed",
        attempt_number=MAX_RESTART_ATTEMPTS,
        error_detail=error_detail,
    )
    log.warning(
        "Component '%s' exhausted all %d restart attempts.",
        component_name,
        MAX_RESTART_ATTEMPTS,
    )


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------


async def record_crash(
    db: AsyncSession,
    component_name: str,
    error_detail: str,
) -> SystemHealthEvent:
    """Persist a crash event and drive the restart state-machine.

    1.  Write a ``crash`` row and flush.
    2.  Consult the in-memory attempt counter and apply the state machine.
    3.  Commit and refresh the original crash event.
    4.  Return the crash event.

    State-machine rules (matching all 12 test expectations):
        current = _COMPONENT_ATTEMPT_CACHE.get(name, 0)

        crash 1  (current=0):  current < MAX → write restart_attempt(1), cache=1
        crash 2  (current=1):  current < MAX → write restart_attempt(2), cache=2
        crash 3  (current=2):  current < MAX → write restart_attempt(3), cache=3
        crash 4  (current=3):  current == MAX → write restart_failed,    cache=MAX+1
        crash 5+ (current=4):  current > MAX → skip entirely

    So test_fourth_crash expects: 3 restart_attempt rows + 1 restart_failed row.
    test_fifth_crash expects: still only 3 restart_attempt + 1 restart_failed.
    """
    crash_event = await _write_event(
        db,
        component_name=component_name,
        event_type="crash",
        error_detail=error_detail,
    )

    current = _COMPONENT_ATTEMPT_CACHE.get(component_name, 0)

    if current < MAX_RESTART_ATTEMPTS:
        # Still have restart slots — consume one
        await _attempt_restart(db, component_name, current + 1, error_detail)
    elif current == MAX_RESTART_ATTEMPTS:
        # Just exhausted all attempts — record permanent failure (only once)
        await _record_restart_failed(db, component_name, error_detail)
        _COMPONENT_ATTEMPT_CACHE[component_name] = MAX_RESTART_ATTEMPTS + 1
    # else current > MAX: already permanently exhausted, skip

    await db.commit()
    await db.refresh(crash_event)
    return crash_event


async def record_restart_ok(
    db: AsyncSession,
    component_name: str,
) -> SystemHealthEvent:
    """Persist a restart_ok event and clear the attempt counter.

    After a successful restart the component is considered healthy again,
    so subsequent crashes start the retry counter from zero.
    """
    _COMPONENT_ATTEMPT_CACHE.pop(component_name, None)

    event = await _write_event(
        db,
        component_name=component_name,
        event_type="restart_ok",
    )
    await db.commit()
    await db.refresh(event)
    log.info("Component '%s' reported healthy after restart.", component_name)
    return event


async def get_worker_health_summary(db: AsyncSession) -> WorkerHealthSummary:
    """Return aggregated event counts grouped by (component_name, event_type)."""
    stmt = (
        select(
            SystemHealthEvent.component_name,
            SystemHealthEvent.event_type,
            func.count().label("cnt"),
        )
        .group_by(SystemHealthEvent.component_name, SystemHealthEvent.event_type)
        .order_by(SystemHealthEvent.component_name, SystemHealthEvent.event_type)
    )
    result = await db.execute(stmt)
    rows = result.all()

    events = [
        WorkerEventCount(component=row.component_name, event_type=row.event_type, count=row.cnt)
        for row in rows
    ]
    return WorkerHealthSummary(events=events)


# ---------------------------------------------------------------------------
# Test helpers
# ---------------------------------------------------------------------------


def reset_attempt_counter(component_name: str) -> None:
    """Remove *component_name* from the in-memory attempt cache.

    Call this in test teardown / autouse fixtures to ensure each test starts
    with a clean state.
    """
    _COMPONENT_ATTEMPT_CACHE.pop(component_name, None)
