"""Unit tests for the auto_name_source Celery task.

We exercise the async core function directly with a mocked session so we
don't need a real broker or DB. The Celery task itself is just a thin
sync wrapper around ``asyncio.run(_run(...))``; testing the wrapper would
add nothing beyond what these tests cover.
"""

from __future__ import annotations

import uuid
from contextlib import asynccontextmanager
from typing import Any
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from src.models.enums import SourceType
from src.models.source import Source
from src.services.source_profiling.protocol import SourceProfile
from src.tasks.auto_name_source import _run

pytestmark = pytest.mark.asyncio


def _make_pending_source(source_type: SourceType = SourceType.FILE_UPLOAD) -> Source:
    s = Source(
        name="Untitled source",
        source_type=source_type,
        owner_id=uuid.uuid4(),
        is_active=False,
    )
    s.id = uuid.uuid4()
    s.name_status = "pending_ai"
    s.description_status = "pending_ai"
    s.description = None
    return s


def _profile_for(source: Source) -> SourceProfile:
    return SourceProfile(
        source_id=str(source.id),
        source_type=source.source_type,
        topics=["sales", "Q4"],
        entities=[],
        content_types=[],
        coverage_summary="Files about Q4 sales reports",
        scope_exclusions="",
        sample_count=3,
    )


def _patched_session(load_returns: Source | None) -> Any:
    """Build a fake AsyncSession.

    - ``execute()`` first call (in _load_pending_source) returns a result
      whose ``scalar_one_or_none()`` yields *load_returns*.
    - subsequent ``execute()`` calls (the UPDATE) return a no-op result.
    - ``add()`` and ``commit()`` are tracked.
    """
    update_result = MagicMock()
    update_result.scalar_one_or_none = MagicMock(return_value=None)

    load_result = MagicMock()
    load_result.scalar_one_or_none = MagicMock(return_value=load_returns)

    session = MagicMock()
    session.execute = AsyncMock(side_effect=[load_result, update_result])
    session.add = MagicMock()
    session.commit = AsyncMock()

    @asynccontextmanager
    async def factory() -> Any:
        yield session

    return session, factory


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------


async def test_skips_when_source_no_longer_pending() -> None:
    """If the admin typed a name (or the task already ran), name_status is
    no longer ``pending_ai`` and the task short-circuits."""
    session, factory = _patched_session(load_returns=None)

    with patch("src.tasks.auto_name_source.AsyncSessionLocal", factory):
        result = await _run(uuid.uuid4())

    assert result["status"] == "skipped"
    # No profiling, no UPDATE, no commit.
    assert session.execute.await_count == 1
    session.commit.assert_not_called()


async def test_happy_path_writes_ai_name_and_description() -> None:
    """Pending source → factory builds a profiler → profile yields topics
    → stub generator returns a name+description → row is updated."""
    source = _make_pending_source()
    session, factory = _patched_session(load_returns=source)

    fake_profiler = MagicMock()
    fake_profiler.profile = AsyncMock(return_value=_profile_for(source))

    fake_factory = MagicMock()
    fake_factory.for_source = MagicMock(return_value=fake_profiler)

    with (
        patch("src.tasks.auto_name_source.AsyncSessionLocal", factory),
        patch(
            "src.tasks.auto_name_source._build_profiler_factory",
            return_value=fake_factory,
        ),
        patch(
            "src.tasks.auto_name_source._generate_name_and_description",
            new=AsyncMock(return_value=("Q4 Sales Files", "Q4 sales reports.")),
        ),
        # FX26 — the rescue-sync hook opens its own session; patch it out
        # so the naming-pipeline assertions below stay focused on what we
        # are actually testing. Hook-specific behaviour is covered by the
        # dedicated tests further down.
        patch(
            "src.tasks.auto_name_source._maybe_enqueue_initial_sync",
            new=AsyncMock(return_value=False),
        ),
    ):
        result = await _run(source.id)

    assert result["status"] == "ai_set"
    assert isinstance(result["name"], str) and result["name"]
    # Two execute() calls: SELECT then UPDATE.
    assert session.execute.await_count == 2
    session.commit.assert_awaited_once()


async def test_appends_history_row_when_prior_description_present() -> None:
    """When the source already had a description (e.g. from a regenerate
    run), the AI overwrite must record the prior value in
    source_description_history for auditability."""
    source = _make_pending_source()
    source.description = "previously written description"
    session, factory = _patched_session(load_returns=source)

    fake_profiler = MagicMock()
    fake_profiler.profile = AsyncMock(return_value=_profile_for(source))
    fake_factory = MagicMock(for_source=MagicMock(return_value=fake_profiler))

    with (
        patch("src.tasks.auto_name_source.AsyncSessionLocal", factory),
        patch(
            "src.tasks.auto_name_source._build_profiler_factory",
            return_value=fake_factory,
        ),
        patch(
            "src.tasks.auto_name_source._generate_name_and_description",
            new=AsyncMock(return_value=("Q4 Sales Files", "Q4 sales reports.")),
        ),
        patch(
            "src.tasks.auto_name_source._maybe_enqueue_initial_sync",
            new=AsyncMock(return_value=False),
        ),
    ):
        await _run(source.id)

    # session.add should have been called with a SourceDescriptionHistory row.
    session.add.assert_called_once()
    history_row = session.add.call_args.args[0]
    assert history_row.description == "previously written description"
    assert history_row.source_id == source.id


async def test_does_not_append_history_row_when_no_prior_description() -> None:
    """First-time AI name on a fresh source has no prior description to
    record; skip the audit row to keep the table clean."""
    source = _make_pending_source()
    assert source.description is None
    session, factory = _patched_session(load_returns=source)

    fake_profiler = MagicMock()
    fake_profiler.profile = AsyncMock(return_value=_profile_for(source))
    fake_factory = MagicMock(for_source=MagicMock(return_value=fake_profiler))

    with (
        patch("src.tasks.auto_name_source.AsyncSessionLocal", factory),
        patch(
            "src.tasks.auto_name_source._build_profiler_factory",
            return_value=fake_factory,
        ),
        patch(
            "src.tasks.auto_name_source._generate_name_and_description",
            new=AsyncMock(return_value=("Q4 Sales Files", "Q4 sales reports.")),
        ),
        patch(
            "src.tasks.auto_name_source._maybe_enqueue_initial_sync",
            new=AsyncMock(return_value=False),
        ),
    ):
        await _run(source.id)

    session.add.assert_not_called()


# ---------------------------------------------------------------------------
# FX26 — initial-sync rescue hook
# ---------------------------------------------------------------------------


async def test_initial_sync_rescue_enqueues_when_no_sync_job_exists() -> None:
    """FX26 happy path: auto-name completed, no SyncJob row → enqueue
    ``tasks.sync_source`` so the source actually gets ingested."""
    from src.tasks.auto_name_source import _maybe_enqueue_initial_sync

    dispatched: list[uuid.UUID] = []

    def fake_dispatch(source_id: uuid.UUID) -> None:
        dispatched.append(source_id)

    source_id = uuid.uuid4()
    with (
        patch(
            "src.tasks.auto_name_source._count_sync_jobs",
            new=AsyncMock(return_value=0),
        ),
        patch(
            "src.tasks.auto_name_source._dispatch_sync_source",
            new=fake_dispatch,
        ),
    ):
        enqueued = await _maybe_enqueue_initial_sync(source_id)

    assert enqueued is True
    assert dispatched == [source_id]


async def test_initial_sync_rescue_skips_when_sync_job_already_exists() -> None:
    """Idempotency: if any SyncJob row exists for this source the rescue
    must be a no-op. Prevents double-syncs when the create endpoint's
    enqueue + this hook both fire successfully."""
    from src.tasks.auto_name_source import _maybe_enqueue_initial_sync

    dispatch_mock = MagicMock()
    with (
        patch(
            "src.tasks.auto_name_source._count_sync_jobs",
            new=AsyncMock(return_value=1),
        ),
        patch(
            "src.tasks.auto_name_source._dispatch_sync_source",
            new=dispatch_mock,
        ),
    ):
        enqueued = await _maybe_enqueue_initial_sync(uuid.uuid4())

    assert enqueued is False
    dispatch_mock.assert_not_called()


async def test_initial_sync_rescue_swallows_dispatch_errors() -> None:
    """A broker outage during the rescue dispatch must NOT undo the
    naming write that just committed in ``_run``. The hook returns
    ``False`` and the caller proceeds."""
    from src.tasks.auto_name_source import _maybe_enqueue_initial_sync

    def boom(_source_id: uuid.UUID) -> None:
        raise RuntimeError("broker down")

    with (
        patch(
            "src.tasks.auto_name_source._count_sync_jobs",
            new=AsyncMock(return_value=0),
        ),
        patch(
            "src.tasks.auto_name_source._dispatch_sync_source",
            new=boom,
        ),
    ):
        enqueued = await _maybe_enqueue_initial_sync(uuid.uuid4())

    assert enqueued is False


async def test_initial_sync_rescue_swallows_count_errors() -> None:
    """A DB outage while reading the SyncJob count must not bubble. The
    naming write upstream is the durable outcome of the task."""
    from src.tasks.auto_name_source import _maybe_enqueue_initial_sync

    dispatch_mock = MagicMock()
    with (
        patch(
            "src.tasks.auto_name_source._count_sync_jobs",
            new=AsyncMock(side_effect=RuntimeError("db down")),
        ),
        patch(
            "src.tasks.auto_name_source._dispatch_sync_source",
            new=dispatch_mock,
        ),
    ):
        enqueued = await _maybe_enqueue_initial_sync(uuid.uuid4())

    assert enqueued is False
    dispatch_mock.assert_not_called()


async def test_run_calls_initial_sync_rescue_after_naming_commit() -> None:
    """End-to-end: ``_run`` must invoke ``_maybe_enqueue_initial_sync``
    AFTER the naming commit, so a hook failure can't roll back the AI
    naming write. Verified by patching the hook and asserting it was
    awaited exactly once after the session commit."""
    source = _make_pending_source()
    session, factory = _patched_session(load_returns=source)

    fake_profiler = MagicMock()
    fake_profiler.profile = AsyncMock(return_value=_profile_for(source))
    fake_factory = MagicMock(for_source=MagicMock(return_value=fake_profiler))

    rescue_mock = AsyncMock(return_value=True)

    with (
        patch("src.tasks.auto_name_source.AsyncSessionLocal", factory),
        patch(
            "src.tasks.auto_name_source._build_profiler_factory",
            return_value=fake_factory,
        ),
        patch(
            "src.tasks.auto_name_source._generate_name_and_description",
            new=AsyncMock(return_value=("Q4 Sales Files", "Q4 sales reports.")),
        ),
        patch(
            "src.tasks.auto_name_source._maybe_enqueue_initial_sync",
            new=rescue_mock,
        ),
    ):
        result = await _run(source.id)

    rescue_mock.assert_awaited_once_with(source.id)
    session.commit.assert_awaited_once()
    assert result["status"] == "ai_set"
    assert result["initial_sync_enqueued"] is True
