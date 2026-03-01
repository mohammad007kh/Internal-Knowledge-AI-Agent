"""Unit tests for tasks.trigger_all_syncs (T-065)."""
from __future__ import annotations

from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock, patch

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _make_source(uid: str) -> SimpleNamespace:
    """Create a minimal source stub with an .id attribute."""
    return SimpleNamespace(id=uid)


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------


class TestTriggerAllSyncs:
    """Tests for trigger_all_syncs task."""

    def test_dispatches_one_task_per_active_source(self) -> None:
        """Each active source triggers exactly one sync_source.delay() call."""
        sources = [_make_source("aaa"), _make_source("bbb"), _make_source("ccc")]

        mock_source_service = MagicMock()
        mock_source_service.list_all_active_sources = AsyncMock(return_value=(sources, len(sources)))

        mock_container = MagicMock()
        mock_container.source_service.return_value = mock_source_service

        mock_delay = MagicMock()

        with (
            patch(
                "src.tasks.trigger_all_syncs.container",
                mock_container,
            ),
            patch(
                "src.tasks.sync_source.sync_source.delay",
                mock_delay,
            ),
        ):
            from src.tasks.trigger_all_syncs import trigger_all_syncs  # noqa: PLC0415

            result = trigger_all_syncs()

        assert result == {"dispatched": 3}
        assert mock_delay.call_count == 3

    def test_returns_zero_when_no_active_sources(self) -> None:
        """Returns dispatched=0 when there are no active sources."""
        mock_source_service = MagicMock()
        mock_source_service.list_all_active_sources = AsyncMock(return_value=([], 0))

        mock_container = MagicMock()
        mock_container.source_service.return_value = mock_source_service

        mock_delay = MagicMock()

        with (
            patch(
                "src.tasks.trigger_all_syncs.container",
                mock_container,
            ),
            patch(
                "src.tasks.sync_source.sync_source.delay",
                mock_delay,
            ),
        ):
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
        mock_source_service.list_all_active_sources = AsyncMock(return_value=(sources, len(sources)))

        mock_container = MagicMock()
        mock_container.source_service.return_value = mock_source_service

        mock_delay = MagicMock()

        with (
            patch(
                "src.tasks.trigger_all_syncs.container",
                mock_container,
            ),
            patch(
                "src.tasks.sync_source.sync_source.delay",
                mock_delay,
            ),
        ):
            from src.tasks.trigger_all_syncs import trigger_all_syncs  # noqa: PLC0415

            trigger_all_syncs()

        mock_delay.assert_called_once_with(str(raw_id))

    def test_dispatched_count_matches_source_count(self) -> None:
        """Return dict 'dispatched' key always equals the number of sources."""
        n = 7
        sources = [_make_source(str(i)) for i in range(n)]

        mock_source_service = MagicMock()
        mock_source_service.list_all_active_sources = AsyncMock(return_value=(sources, n))

        mock_container = MagicMock()
        mock_container.source_service.return_value = mock_source_service

        with (
            patch(
                "src.tasks.trigger_all_syncs.container",
                mock_container,
            ),
            patch(
                "src.tasks.sync_source.sync_source.delay",
                MagicMock(),
            ),
        ):
            from src.tasks.trigger_all_syncs import trigger_all_syncs  # noqa: PLC0415

            result = trigger_all_syncs()

        assert result["dispatched"] == n
