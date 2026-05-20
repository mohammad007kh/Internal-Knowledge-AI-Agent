"""Unit tests for SyncJobService auto-demote logic — Slice A.

Asserts the connection-health side effects on ``mark_success`` /
``mark_failed``:

* ``mark_success`` → ``connection_status='healthy'``, error cleared.
* ``mark_failed`` after one prior ``failed`` run → ``connection_status='failed'``
  (auto-demoted, the chat picker hides the row).
* ``mark_failed`` after a prior ``success`` run → ``connection_status='degraded'``
  (one-off blip, picker still surfaces it).
"""

from __future__ import annotations

import os
import uuid
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from datetime import UTC, datetime
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock

import pytest

os.environ.setdefault("DATABASE_URL", "postgresql+asyncpg://test:test@localhost/test")
os.environ.setdefault("JWT_SECRET_KEY", "test-jwt-secret-key-at-least-32-chars-long!!")
os.environ.setdefault("JWT_REFRESH_SECRET_KEY", "test-jwt-refresh-secret-key-32-chars!!")
os.environ.setdefault("MINIO_ENDPOINT", "localhost:9000")
os.environ.setdefault("MINIO_ACCESS_KEY", "testaccess")
os.environ.setdefault("MINIO_SECRET_KEY", "testsecret")
os.environ.setdefault("ENCRYPTION_KEY", "dGVzdGVuY3J5cHRpb25rZXkxMjM0NTY3ODk=")

from src.models.enums import SyncStatus  # noqa: E402
from src.services.sync_job_service import SyncJobService  # noqa: E402

SOURCE_ID = uuid.UUID("00000000-0000-0000-0000-000000000044")
JOB_ID = uuid.UUID("00000000-0000-0000-0000-000000000055")


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _make_service(
    *,
    repo: AsyncMock,
    session: AsyncMock,
) -> SyncJobService:
    """Build a SyncJobService bound to an in-memory mock session.

    The real service opens a session via ``session_factory()`` and then
    enters ``session.begin()`` for the transaction. We mock both as no-op
    async context managers yielding the same `session` mock so every
    UPDATE / SELECT lands on a single instance the test can inspect.
    """

    @asynccontextmanager
    async def _begin_ctx() -> AsyncIterator[None]:
        yield None

    @asynccontextmanager
    async def _factory_ctx() -> AsyncIterator[AsyncMock]:
        yield session

    # Wire the begin() CM on the session up front so it survives
    # multiple factory entries (each mark_* call opens a new session).
    session.begin = lambda: _begin_ctx()

    factory = MagicMock()
    factory.side_effect = lambda: _factory_ctx()
    return SyncJobService(session_factory=factory, sync_job_repo=repo)


def _make_job(status: SyncStatus = SyncStatus.RUNNING) -> SimpleNamespace:
    """Return a stand-in for a SyncJob ORM row."""
    return SimpleNamespace(
        id=JOB_ID,
        source_id=SOURCE_ID,
        status=status,
        started_at=datetime.now(UTC),
        finished_at=None,
        error_message=None,
        documents_synced=0,
        chunks_created=0,
        created_at=datetime.now(UTC),
        updated_at=datetime.now(UTC),
    )


def _select_status_result(statuses: list[SyncStatus]) -> MagicMock:
    """Build a mock ``execute`` Result whose ``.all()`` matches the ORM contract.

    The repo issues ``SELECT status FROM sync_jobs WHERE source_id=… ORDER BY
    created_at DESC LIMIT 2`` and reads ``row[0]`` to get the status. Returning
    a list of single-tuples mirrors that.
    """
    result = MagicMock()
    result.all.return_value = [(s,) for s in statuses]
    return result


def _empty_update_result() -> MagicMock:
    return MagicMock()


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------


class TestMarkSuccess:
    @pytest.mark.asyncio
    async def test_marks_connection_healthy(self, monkeypatch) -> None:
        """A successful sync flips connection_status back to 'healthy' and clears the error.

        The post-success lifecycle hook (``_maybe_enqueue_auto_name_for``)
        is patched out because it opens a brand-new session via
        :data:`AsyncSessionLocal` — out of scope for this unit test.
        """
        from src.services import sync_job_service as svc_module

        monkeypatch.setattr(
            svc_module, "_maybe_enqueue_auto_name_for", AsyncMock()
        )

        repo = AsyncMock()
        repo.update_status = AsyncMock(return_value=_make_job(status=SyncStatus.SUCCESS))

        session = AsyncMock()
        session.execute = AsyncMock(return_value=_empty_update_result())

        service = _make_service(repo=repo, session=session)

        await service.mark_success(JOB_ID, documents_synced=3, chunks_created=15)

        # The first execute call writes the connection-health update on Source.
        # We check that the compiled SQL carries the 'healthy' literal.
        assert session.execute.await_count >= 1
        compiled_pieces: list[str] = []
        for call in session.execute.await_args_list:
            stmt = call.args[0]
            try:
                compiled_pieces.append(
                    str(stmt.compile(compile_kwargs={"literal_binds": True}))
                )
            except Exception:  # noqa: BLE001 — bare strings/non-Compilable sneak through tests
                continue
        joined = "\n".join(compiled_pieces)
        assert "connection_status" in joined
        assert "'healthy'" in joined


class TestMarkFailed:
    @pytest.mark.asyncio
    async def test_failed_after_prior_failed_demotes_to_failed(self) -> None:
        """Two consecutive failures → connection_status='failed' (auto-demoted)."""
        repo = AsyncMock()
        repo.update_status = AsyncMock(
            return_value=_make_job(status=SyncStatus.FAILED)
        )

        session = AsyncMock()
        # Order: SELECT status → returns [failed, failed] (this run + prior),
        # then UPDATE Source.connection_status.
        session.execute = AsyncMock(
            side_effect=[
                _select_status_result([SyncStatus.FAILED, SyncStatus.FAILED]),
                _empty_update_result(),
            ]
        )

        service = _make_service(repo=repo, session=session)

        await service.mark_failed(JOB_ID, error_message="connection refused")

        # The second execute is the Source update — verify its compiled SQL
        # carries the 'failed' literal.
        assert session.execute.await_count == 2
        update_stmt = session.execute.await_args_list[1].args[0]
        compiled = str(
            update_stmt.compile(compile_kwargs={"literal_binds": True})
        )
        assert "'failed'" in compiled
        assert "connection refused" in compiled

    @pytest.mark.asyncio
    async def test_failed_after_prior_success_only_degraded(self) -> None:
        """One failure after a successful run → connection_status='degraded' (lenient)."""
        repo = AsyncMock()
        repo.update_status = AsyncMock(
            return_value=_make_job(status=SyncStatus.FAILED)
        )

        session = AsyncMock()
        session.execute = AsyncMock(
            side_effect=[
                _select_status_result([SyncStatus.FAILED, SyncStatus.SUCCESS]),
                _empty_update_result(),
            ]
        )

        service = _make_service(repo=repo, session=session)

        await service.mark_failed(JOB_ID, error_message="transient blip")

        update_stmt = session.execute.await_args_list[1].args[0]
        compiled = str(
            update_stmt.compile(compile_kwargs={"literal_binds": True})
        )
        # 'degraded' wins — we still surface the source in the picker.
        assert "'degraded'" in compiled
        # Sanity: the connection_status column is NOT being set to 'failed'.
        assert "connection_status='failed'" not in compiled.replace(" ", "")

    @pytest.mark.asyncio
    async def test_error_message_truncated_to_500(self) -> None:
        """Long error messages are clipped to 500 chars before persistence."""
        repo = AsyncMock()
        repo.update_status = AsyncMock(
            return_value=_make_job(status=SyncStatus.FAILED)
        )

        session = AsyncMock()
        session.execute = AsyncMock(
            side_effect=[
                _select_status_result([SyncStatus.FAILED, SyncStatus.SUCCESS]),
                _empty_update_result(),
            ]
        )

        service = _make_service(repo=repo, session=session)

        long_err = "x" * 2000
        await service.mark_failed(JOB_ID, error_message=long_err)

        update_stmt = session.execute.await_args_list[1].args[0]
        compiled = str(
            update_stmt.compile(compile_kwargs={"literal_binds": True})
        )
        # 500 'x' characters survive; nothing past that.
        assert "x" * 500 in compiled
        assert "x" * 501 not in compiled


class TestPriorJobScoping:
    """The consecutive-failure SELECT is scoped to the source under test."""

    @pytest.mark.asyncio
    async def test_select_filters_by_source_id(self) -> None:
        """The SQL counts only this source's runs — a different source's
        recent failure must NOT be able to demote an unrelated row.
        """
        repo = AsyncMock()
        repo.update_status = AsyncMock(
            return_value=_make_job(status=SyncStatus.FAILED)
        )

        session = AsyncMock()
        session.execute = AsyncMock(
            side_effect=[
                _select_status_result([SyncStatus.FAILED]),
                _empty_update_result(),
            ]
        )

        service = _make_service(repo=repo, session=session)

        await service.mark_failed(JOB_ID, error_message="oops")

        select_stmt = session.execute.await_args_list[0].args[0]
        compiled = str(
            select_stmt.compile(compile_kwargs={"literal_binds": True})
        )
        # WHERE source_id = '<source_id>' must appear. SQLAlchemy renders
        # uuid bind values without dashes when literal_binds=True
        # (postgresql UUID type), so compare on the dash-stripped form.
        assert str(SOURCE_ID).replace("-", "") in compiled.replace("-", "")
