"""Unit tests for tasks.trigger_all_syncs (T-065)."""
from __future__ import annotations

from contextlib import asynccontextmanager
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock, patch

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _make_source(uid: str) -> SimpleNamespace:
    """Create a minimal source stub with an .id attribute."""
    return SimpleNamespace(id=uid)


@asynccontextmanager
async def _fake_task_session():
    """Stand-in for ``task_session`` that yields a dummy session.

    The real ``task_session`` builds a throwaway asyncpg engine per event loop
    (see ``src.core.database``); in unit tests we never touch the DB, so we
    yield a MagicMock and skip engine creation entirely.
    """
    yield MagicMock()


def _patch_module(mock_source_service: MagicMock):
    """Patch the task module's real DI seams.

    ``trigger_all_syncs`` constructs a ``SourceService`` inside a
    ``task_session()`` context — there is no module-level ``container``. We
    patch ``task_session`` to avoid real DB I/O and ``SourceService`` so the
    constructed service is our mock regardless of constructor args.
    """
    return (
        patch("src.tasks.trigger_all_syncs.task_session", _fake_task_session),
        patch(
            "src.tasks.trigger_all_syncs.SourceService",
            return_value=mock_source_service,
        ),
        patch("src.tasks.sync_source.sync_source.delay"),
    )


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------


class TestTriggerAllSyncs:
    """Tests for trigger_all_syncs task."""

    def test_dispatches_one_task_per_active_source(self) -> None:
        """Each active source triggers exactly one sync_source.delay() call."""
        sources = [_make_source("aaa"), _make_source("bbb"), _make_source("ccc")]

        mock_source_service = MagicMock()
        mock_source_service.list_all_active_sources = AsyncMock(
            return_value=(sources, len(sources))
        )

        patch_session, patch_service, patch_delay = _patch_module(mock_source_service)
        with patch_session, patch_service, patch_delay as mock_delay:
            from src.tasks.trigger_all_syncs import trigger_all_syncs  # noqa: PLC0415

            result = trigger_all_syncs()

        assert result == {"dispatched": 3}
        assert mock_delay.call_count == 3

    def test_returns_zero_when_no_active_sources(self) -> None:
        """Returns dispatched=0 when there are no active sources."""
        mock_source_service = MagicMock()
        mock_source_service.list_all_active_sources = AsyncMock(return_value=([], 0))

        patch_session, patch_service, patch_delay = _patch_module(mock_source_service)
        with patch_session, patch_service, patch_delay as mock_delay:
            from src.tasks.trigger_all_syncs import trigger_all_syncs  # noqa: PLC0415

            result = trigger_all_syncs()

        assert result == {"dispatched": 0}
        mock_delay.assert_not_called()

    def test_passes_source_id_as_string(self) -> None:
        """Source id is converted to str before passing to sync_source.delay()."""
        import uuid  # noqa: PLC0415

        raw_id = uuid.UUID("12345678-1234-5678-1234-567812345678")
        sources = [_make_source(raw_id)]

        mock_source_service = MagicMock()
        mock_source_service.list_all_active_sources = AsyncMock(
            return_value=(sources, len(sources))
        )

        patch_session, patch_service, patch_delay = _patch_module(mock_source_service)
        with patch_session, patch_service, patch_delay as mock_delay:
            from src.tasks.trigger_all_syncs import trigger_all_syncs  # noqa: PLC0415

            trigger_all_syncs()

        mock_delay.assert_called_once_with(str(raw_id))

    def test_dispatched_count_matches_source_count(self) -> None:
        """Return dict 'dispatched' key always equals the number of sources."""
        n = 7
        sources = [_make_source(str(i)) for i in range(n)]

        mock_source_service = MagicMock()
        mock_source_service.list_all_active_sources = AsyncMock(
            return_value=(sources, n)
        )

        patch_session, patch_service, patch_delay = _patch_module(mock_source_service)
        with patch_session, patch_service, patch_delay:
            from src.tasks.trigger_all_syncs import trigger_all_syncs  # noqa: PLC0415

            result = trigger_all_syncs()

        assert result["dispatched"] == n
