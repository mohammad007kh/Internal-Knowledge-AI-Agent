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
    ):
        await _run(source.id)

    session.add.assert_not_called()
