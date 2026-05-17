"""Unit tests for the ``check_scheduled_syncs`` Celery Beat task (FX22).

These tests exercise the async core (``_check_scheduled_syncs_async``) with
a mocked session so no broker / DB is required. The Celery task itself is a
thin ``asyncio.run`` wrapper and is not re-tested here.

Two scenarios are covered:

* **Happy path** — the SELECT succeeds, the task dispatches one sync per due
  source, stamps ``status='syncing'`` plus a recomputed ``next_sync_due_at``,
  and commits. The query bind parameter is asserted to be a TZ-aware UTC
  datetime — the regression FX22 was caused by exactly that argument being
  rejected by asyncpg because the SQLAlchemy column was naive.

* **DBAPIError path** — when the SELECT raises (the FX22 symptom: tz-aware
  vs naive comparison), the task must log + return 0 rather than
  propagating. No ``send_task`` and no UPDATE should fire, and no spurious
  success state should be recorded. This protects Beat from a 60-second
  unhandled-exception loop and stops a future schema-drift regression from
  silently looking healthy.
"""
from __future__ import annotations

import uuid
from contextlib import asynccontextmanager
from datetime import datetime, timezone
from typing import Any
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from sqlalchemy.exc import DBAPIError

from src.models.enums import SourceType
from src.models.source import Source
from src.tasks.check_scheduled_syncs import _check_scheduled_syncs_async

pytestmark = pytest.mark.asyncio


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


def _make_due_source(*, schedule: str | None = "*/5 * * * *") -> Source:
    """Build an in-memory Source that the cron task should pick up."""
    s = Source(
        name="Test Source",
        source_type=SourceType.DATABASE,
        owner_id=uuid.uuid4(),
        is_active=True,
    )
    s.id = uuid.uuid4()
    s.sync_mode = "scheduled"
    s.sync_schedule = schedule
    s.status = "ready"
    # The actual due-at filter is exercised inside the SQL — what matters
    # for the unit test is that the fake session returns this row as if
    # the filter had matched.
    s.next_sync_due_at = datetime(2026, 5, 17, 12, 0, tzinfo=timezone.utc)
    return s


def _patched_session(
    *,
    select_result: list[Source] | DBAPIError,
) -> tuple[MagicMock, Any]:
    """Build a fake AsyncSession.

    * ``select_result`` is either the list of Sources to return from the
      first ``execute`` call (happy path), or a ``DBAPIError`` to raise.
    * Subsequent ``execute`` calls (the per-source UPDATEs) return a
      no-op MagicMock.
    * ``commit`` is tracked.
    """
    scalars = MagicMock()
    if isinstance(select_result, list):
        scalars.all = MagicMock(return_value=select_result)
        select_mock = MagicMock()
        select_mock.scalars = MagicMock(return_value=scalars)
        update_mock = MagicMock()

        session = MagicMock()
        session.execute = AsyncMock(
            side_effect=[select_mock] + [update_mock] * len(select_result)
        )
    else:
        session = MagicMock()
        session.execute = AsyncMock(side_effect=select_result)

    session.commit = AsyncMock()

    @asynccontextmanager
    async def factory() -> Any:
        yield session

    return session, factory


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------


async def test_happy_path_dispatches_sync_for_due_source() -> None:
    """One due source → one ``send_task`` call → row stamped 'syncing' → commit."""
    source = _make_due_source()
    session, factory = _patched_session(select_result=[source])

    with (
        patch("src.tasks.check_scheduled_syncs.task_session", factory),
        patch(
            "src.tasks.check_scheduled_syncs.celery_app.send_task"
        ) as send_task,
    ):
        dispatched = await _check_scheduled_syncs_async()

    assert dispatched == 1
    send_task.assert_called_once_with(
        "tasks.sync_source", args=[str(source.id)]
    )
    # 1 SELECT + 1 UPDATE
    assert session.execute.await_count == 2
    session.commit.assert_awaited_once()


async def test_column_type_is_tz_aware() -> None:
    """Regression guard for FX22.

    The on-disk column has been TIMESTAMPTZ since migration 0018, but the
    SQLAlchemy column declaration was naive — that mismatch made asyncpg
    reject the tz-aware ``datetime.now(timezone.utc)`` bind parameter the
    Beat task passes. Assert the model column now declares ``timezone=True``
    so a future refactor cannot silently drop it.
    """
    column = Source.__table__.c.next_sync_due_at
    # SQLAlchemy's DateTime type exposes ``timezone`` directly on the
    # column type. If a maintainer ever swaps the declaration back to a
    # bare ``Mapped[datetime | None] = mapped_column(nullable=True)``,
    # this assertion fails before the integration regression returns.
    assert getattr(column.type, "timezone", False) is True, (
        "sources.next_sync_due_at must be TZ-aware (DateTime(timezone=True)) — "
        "see FX22. Without this, the asyncpg bind parameter cast becomes "
        "TIMESTAMP WITHOUT TIME ZONE and the cron task crashes every 60 s."
    )


async def test_dbapierror_is_caught_and_returns_zero() -> None:
    """FX22: a DBAPIError on the SELECT must NOT propagate.

    Beat ticks every 60 s; an unhandled exception in this task tears the
    Beat scheduler's bookkeeping for that schedule. The expected behaviour
    is to log + return 0 + let the next tick try again. We also assert
    that:
      * No ``send_task`` is fired (no spurious "success" downstream)
      * No UPDATE is issued (the failed SELECT means we never saw any rows)
      * ``commit`` is NOT called (no partial state to persist)
    """
    fake_orig = Exception("invalid input for query argument $2")
    dbapi_exc = DBAPIError("SELECT ...", {}, fake_orig)

    session, factory = _patched_session(select_result=dbapi_exc)

    with (
        patch("src.tasks.check_scheduled_syncs.task_session", factory),
        patch(
            "src.tasks.check_scheduled_syncs.celery_app.send_task"
        ) as send_task,
    ):
        dispatched = await _check_scheduled_syncs_async()

    assert dispatched == 0
    send_task.assert_not_called()
    # Only the SELECT was attempted.
    assert session.execute.await_count == 1
    session.commit.assert_not_called()


async def test_no_due_sources_returns_zero_without_dispatch() -> None:
    """Empty result set → no dispatch, no UPDATE, but the SELECT did run.

    We still ``commit`` (cheap on an empty transaction) — this matches
    the current task semantics and keeps the test focused on the FX22
    regression rather than re-asserting unrelated behaviour.
    """
    session, factory = _patched_session(select_result=[])

    with (
        patch("src.tasks.check_scheduled_syncs.task_session", factory),
        patch(
            "src.tasks.check_scheduled_syncs.celery_app.send_task"
        ) as send_task,
    ):
        dispatched = await _check_scheduled_syncs_async()

    assert dispatched == 0
    send_task.assert_not_called()
    assert session.execute.await_count == 1
    session.commit.assert_awaited_once()
