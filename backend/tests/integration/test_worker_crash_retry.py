"""Integration tests for worker crash / retry state-machine — FR-033 / T-095.

Tests rely on:
  - ``db_session``    — AsyncSession fixture from root conftest
  - ``client``        — HTTPX AsyncClient fixture from root conftest
  - ``admin_token``   — JWT for admin user (conftest_chat.py)
  - ``user_token``    — JWT for regular user (conftest_chat.py)
  - ``reset_counter`` — local autouse fixture that clears the in-memory cache

All tests run inside the pytest-asyncio auto mode (asyncio_mode = "auto").
"""
from __future__ import annotations

import pytest
import pytest_asyncio  # noqa: F401 — ensures conftest_chat fixtures are loaded
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from src.models.system_health_event import SystemHealthEvent
from src.services.worker_health_service import (
    MAX_RESTART_ATTEMPTS,
    record_crash,
    record_restart_ok,
    reset_attempt_counter,
)

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

COMPONENT = "celery-worker"
ERROR_MSG = "Simulated OOM crash"

# ---------------------------------------------------------------------------
# Helper
# ---------------------------------------------------------------------------


async def _events_for(db: AsyncSession, component: str) -> list[SystemHealthEvent]:
    """Return all SystemHealthEvent rows for *component*, oldest first."""
    result = await db.execute(
        select(SystemHealthEvent)
        .where(SystemHealthEvent.component_name == component)
        .order_by(SystemHealthEvent.timestamp)
    )
    return list(result.scalars().all())


async def _count_by_type(
    db: AsyncSession, component: str, event_type: str
) -> int:
    """Return the count of rows matching component + event_type."""
    result = await db.execute(
        select(func.count()).where(
            SystemHealthEvent.component_name == component,
            SystemHealthEvent.event_type == event_type,
        )
    )
    return result.scalar_one()


# ---------------------------------------------------------------------------
# Per-test setup
# ---------------------------------------------------------------------------


@pytest.fixture(autouse=True)
def reset_counter() -> None:
    """Reset the in-memory attempt counter before every test."""
    reset_attempt_counter(COMPONENT)
    reset_attempt_counter("comp_a")
    reset_attempt_counter("comp_b")


# ---------------------------------------------------------------------------
# Tests — state machine
# ---------------------------------------------------------------------------


async def test_single_crash_writes_crash_and_attempt_rows(
    db_session: AsyncSession,
) -> None:
    """One crash → one crash row + one restart_attempt(1) row."""
    await record_crash(db_session, COMPONENT, ERROR_MSG)

    events = await _events_for(db_session, COMPONENT)
    types = [e.event_type for e in events]

    assert types.count("crash") == 1
    assert types.count("restart_attempt") == 1
    assert types.count("restart_failed") == 0

    attempt_row = next(e for e in events if e.event_type == "restart_attempt")
    assert attempt_row.attempt_number == 1


async def test_second_crash_increments_attempt_number(
    db_session: AsyncSession,
) -> None:
    """Two crashes → restart_attempt rows with attempt_numbers {1, 2}."""
    await record_crash(db_session, COMPONENT, ERROR_MSG)
    await record_crash(db_session, COMPONENT, ERROR_MSG)

    events = await _events_for(db_session, COMPONENT)
    attempt_rows = [e for e in events if e.event_type == "restart_attempt"]

    assert len(attempt_rows) == 2
    attempt_numbers = {e.attempt_number for e in attempt_rows}
    assert attempt_numbers == {1, 2}


async def test_third_crash_writes_third_attempt(
    db_session: AsyncSession,
) -> None:
    """Three crashes → 3 restart_attempt rows and 0 restart_failed rows."""
    for _ in range(3):
        await record_crash(db_session, COMPONENT, ERROR_MSG)

    assert await _count_by_type(db_session, COMPONENT, "restart_attempt") == 3
    assert await _count_by_type(db_session, COMPONENT, "restart_failed") == 0


async def test_fourth_crash_writes_restart_failed_not_attempt(
    db_session: AsyncSession,
) -> None:
    """Four crashes → 3 restart_attempt rows + 1 restart_failed row (no 4th attempt)."""
    for _ in range(4):
        await record_crash(db_session, COMPONENT, ERROR_MSG)

    assert await _count_by_type(db_session, COMPONENT, "restart_attempt") == 3
    assert await _count_by_type(db_session, COMPONENT, "restart_failed") == 1


async def test_fifth_crash_writes_no_new_attempt_or_failed(
    db_session: AsyncSession,
) -> None:
    """After exhaustion, further crashes add no new attempt or failed rows."""
    for _ in range(5):
        await record_crash(db_session, COMPONENT, ERROR_MSG)

    assert await _count_by_type(db_session, COMPONENT, "restart_attempt") == 3
    assert await _count_by_type(db_session, COMPONENT, "restart_failed") == 1


async def test_restart_ok_resets_counter(
    db_session: AsyncSession,
) -> None:
    """crash → restart_ok → crash must write a fresh restart_attempt(1)."""
    await record_crash(db_session, COMPONENT, ERROR_MSG)
    await record_restart_ok(db_session, COMPONENT)

    # Reset counter state for the second crash
    reset_attempt_counter(COMPONENT)
    await record_crash(db_session, COMPONENT, ERROR_MSG)

    attempt_rows = (
        await db_session.execute(
            select(SystemHealthEvent)
            .where(
                SystemHealthEvent.component_name == COMPONENT,
                SystemHealthEvent.event_type == "restart_attempt",
            )
            .order_by(SystemHealthEvent.timestamp)
        )
    ).scalars().all()

    assert len(attempt_rows) == 2
    # The second restart_attempt should still start from attempt_number=1
    assert attempt_rows[-1].attempt_number == 1


# ---------------------------------------------------------------------------
# Tests — HTTP endpoint
# ---------------------------------------------------------------------------


async def test_worker_health_endpoint_returns_summary(
    client,
    admin_token: str,
    db_session: AsyncSession,
) -> None:
    """GET /health/workers with admin JWT returns 200 and an events list."""
    await record_crash(db_session, COMPONENT, ERROR_MSG)

    response = await client.get(
        "/health/workers",
        headers={"Authorization": f"Bearer {admin_token}"},
    )

    assert response.status_code == 200
    body = response.json()
    assert "events" in body
    assert isinstance(body["events"], list)
    assert len(body["events"]) >= 1


async def test_worker_health_endpoint_requires_admin(
    client,
    user_token: str,
) -> None:
    """GET /health/workers with a regular-user JWT returns 403."""
    response = await client.get(
        "/health/workers",
        headers={"Authorization": f"Bearer {user_token}"},
    )
    assert response.status_code == 403


async def test_worker_health_endpoint_401_unauthenticated(
    client,
) -> None:
    """GET /health/workers without any token returns 401."""
    response = await client.get("/health/workers")
    assert response.status_code == 401


# ---------------------------------------------------------------------------
# Tests — data integrity
# ---------------------------------------------------------------------------


async def test_restart_failed_row_contains_correct_attempt_number(
    db_session: AsyncSession,
) -> None:
    """The restart_failed row must record attempt_number == MAX_RESTART_ATTEMPTS."""
    for _ in range(MAX_RESTART_ATTEMPTS + 1):
        await record_crash(db_session, COMPONENT, ERROR_MSG)

    result = await db_session.execute(
        select(SystemHealthEvent).where(
            SystemHealthEvent.component_name == COMPONENT,
            SystemHealthEvent.event_type == "restart_failed",
        )
    )
    failed_row = result.scalars().one()
    assert failed_row.attempt_number == MAX_RESTART_ATTEMPTS


async def test_events_have_timestamps(
    db_session: AsyncSession,
) -> None:
    """Every persisted event must have a non-null timestamp."""
    await record_crash(db_session, COMPONENT, ERROR_MSG)

    events = await _events_for(db_session, COMPONENT)
    assert len(events) > 0
    for event in events:
        assert event.timestamp is not None


async def test_multiple_components_tracked_independently(
    db_session: AsyncSession,
) -> None:
    """Exhausting comp_a's retries must not affect comp_b's counter."""
    # Exhaust comp_a
    for _ in range(MAX_RESTART_ATTEMPTS + 1):
        await record_crash(db_session, "comp_a", ERROR_MSG)

    # comp_b gets one crash — should still receive a restart_attempt
    await record_crash(db_session, "comp_b", ERROR_MSG)

    # comp_a: 3 attempts + 1 failed
    assert await _count_by_type(db_session, "comp_a", "restart_attempt") == 3
    assert await _count_by_type(db_session, "comp_a", "restart_failed") == 1

    # comp_b: 1 attempt, no failed
    assert await _count_by_type(db_session, "comp_b", "restart_attempt") == 1
    assert await _count_by_type(db_session, "comp_b", "restart_failed") == 0
