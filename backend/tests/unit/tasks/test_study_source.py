"""Unit tests for the ``tasks.study_source`` Celery task (Slice E1).

We exercise the async core (:func:`_run`) directly with mocked sessions
and a mocked connector so the tests need neither a broker nor a live DB.
The Celery task itself is just ``asyncio.run(_run(...))``.

Test matrix
-----------
* Happy path — connector produces a SchemaDocument → study marked
  completed, Source.schema_status flipped to ``"completed"``.
* Idempotency — a non-terminal study row exists → task short-circuits
  without creating a second study, without flipping schema_status, and
  without invoking the connector.
* Failure path — connector raises → schema_status flipped to ``"failed"``,
  study row marked ``<phase>_FAILED`` with a sanitised message, and the
  helper returns ``status="failed"`` (the wrapper re-raises in production
  so Celery records the failure, but the async core surfaces a result).
* Non-DB source — the task is a no-op skip.
* Missing source — the task is a no-op skip.
"""

from __future__ import annotations

import os
import uuid
from contextlib import asynccontextmanager
from typing import Any
from unittest.mock import AsyncMock, MagicMock, patch

import pytest


os.environ.setdefault("DATABASE_URL", "postgresql+asyncpg://test:test@localhost/test")
os.environ.setdefault("JWT_SECRET_KEY", "test-jwt-secret-key-at-least-32-chars-long!!")
os.environ.setdefault("JWT_REFRESH_SECRET_KEY", "test-jwt-refresh-secret-key-32-chars!!")
os.environ.setdefault("MINIO_ENDPOINT", "localhost:9000")
os.environ.setdefault("MINIO_ACCESS_KEY", "testaccess")
os.environ.setdefault("MINIO_SECRET_KEY", "testsecret")
os.environ.setdefault("ENCRYPTION_KEY", "dGVzdGVuY3J5cHRpb25rZXkxMjM0NTY3ODk=")


pytestmark = pytest.mark.asyncio


# ---------------------------------------------------------------------------
# Fixtures + helpers
# ---------------------------------------------------------------------------


def _make_db_source(*, source_type: str = "database") -> MagicMock:
    """Build a Source ORM-shaped MagicMock for the task's pipeline."""
    from src.models.enums import SourceType

    src = MagicMock()
    src.id = uuid.uuid4()
    if source_type == "database":
        src.source_type = SourceType.DATABASE
    else:
        src.source_type = SourceType(source_type)
    # Empty config_encrypted means the task's _decrypt_config returns {} —
    # the connector spy doesn't read it anyway.
    src.config_encrypted = None
    src.name = "Reporting DB"
    return src


def _make_schema_document() -> Any:
    """Return a minimal valid :class:`SchemaDocument`.

    Empty ``tables`` is allowed; the fingerprint is recomputed by the task
    so we don't need to pre-populate it correctly.
    """
    from datetime import datetime, timezone

    from src.services.db_introspection.schema_doc import SchemaDocument

    return SchemaDocument(
        dialect="postgresql",
        fingerprint="0" * 64,
        generated_at=datetime.now(tz=timezone.utc),
        agent_version="test@1",
        study_duration_ms=0,
        partial=False,
        phase_errors=[],
        tables=[],
        summary="",
        vector_index_ref=None,
    )


def _patch_session_factory(session: Any):
    """Return an ``AsyncSessionLocal`` stand-in yielding *session*.

    Each ``async with AsyncSessionLocal() as s`` produces the same session
    so tests can introspect a single set of spies.
    """

    @asynccontextmanager
    async def _factory() -> Any:
        yield session

    return _factory


# ---------------------------------------------------------------------------
# Happy path
# ---------------------------------------------------------------------------


async def test_happy_path_writes_schema_study_and_sets_status_completed():
    """Connector returns a SchemaDocument → study marked READY,
    Source.schema_status flipped to ``"completed"``."""
    source = _make_db_source()

    session = MagicMock()
    session.commit = AsyncMock()
    session.execute = AsyncMock()
    session.flush = AsyncMock()
    session.add = MagicMock()

    # SourceRepository.get_by_id returns our DB source.
    get_by_id = AsyncMock(return_value=source)

    # is_running → False so the pipeline runs.
    is_running = AsyncMock(return_value=False)

    # create_study returns a study with a real id.
    study_row = MagicMock()
    study_row.id = uuid.uuid4()
    create_study = AsyncMock(return_value=study_row)

    set_schema_status = AsyncMock(return_value=None)
    mark_completed = AsyncMock(return_value=None)
    mark_failed = AsyncMock(return_value=None)

    # Connector stub with study_schema → SchemaDocument.
    schema_doc = _make_schema_document()
    connector_stub = MagicMock()
    connector_stub.study_schema = AsyncMock(return_value=schema_doc)
    factory_build = MagicMock(return_value=connector_stub)

    factory = _patch_session_factory(session)

    from src.repositories.schema_study_repository import SchemaStudyRepository
    from src.repositories.source_repository import SourceRepository

    with (
        patch("src.tasks.study_source.AsyncSessionLocal", factory),
        patch.object(SourceRepository, "get_by_id", get_by_id, create=False),
        patch.object(
            SourceRepository, "set_schema_status", set_schema_status, create=False
        ),
        patch.object(
            SchemaStudyRepository, "is_running", is_running, create=False
        ),
        patch.object(
            SchemaStudyRepository, "create_study", create_study, create=False
        ),
        patch.object(
            SchemaStudyRepository, "mark_completed", mark_completed, create=False
        ),
        patch.object(
            SchemaStudyRepository, "mark_failed", mark_failed, create=False
        ),
        patch(
            "src.tasks.study_source.ConnectorFactory",
            return_value=MagicMock(build=factory_build),
        ),
    ):
        from src.tasks.study_source import _run

        result = await _run(source.id)

    assert result["status"] == "completed", result
    # Connector study_schema invoked exactly once.
    connector_stub.study_schema.assert_awaited_once()
    # set_schema_status called twice: once with "studying", once with "completed".
    statuses = [c.args[1] for c in set_schema_status.await_args_list]
    assert "studying" in statuses
    assert "completed" in statuses
    # Study lifecycle: create_study + mark_completed; never mark_failed.
    create_study.assert_awaited_once()
    mark_completed.assert_awaited_once()
    mark_failed.assert_not_awaited()


# ---------------------------------------------------------------------------
# Idempotency
# ---------------------------------------------------------------------------


async def test_idempotency_second_concurrent_call_is_a_noop():
    """When ``is_running`` returns True the task short-circuits."""
    source = _make_db_source()

    session = MagicMock()
    session.commit = AsyncMock()
    session.execute = AsyncMock()
    session.flush = AsyncMock()
    session.add = MagicMock()

    get_by_id = AsyncMock(return_value=source)
    is_running = AsyncMock(return_value=True)
    create_study = AsyncMock()
    set_schema_status = AsyncMock()

    connector_stub = MagicMock()
    connector_stub.study_schema = AsyncMock()

    factory = _patch_session_factory(session)

    from src.repositories.schema_study_repository import SchemaStudyRepository
    from src.repositories.source_repository import SourceRepository

    with (
        patch("src.tasks.study_source.AsyncSessionLocal", factory),
        patch.object(SourceRepository, "get_by_id", get_by_id, create=False),
        patch.object(
            SourceRepository, "set_schema_status", set_schema_status, create=False
        ),
        patch.object(
            SchemaStudyRepository, "is_running", is_running, create=False
        ),
        patch.object(
            SchemaStudyRepository, "create_study", create_study, create=False
        ),
    ):
        from src.tasks.study_source import _run

        result = await _run(source.id)

    assert result["status"] == "skipped"
    create_study.assert_not_awaited()
    set_schema_status.assert_not_awaited()
    connector_stub.study_schema.assert_not_awaited()


# ---------------------------------------------------------------------------
# Failure path
# ---------------------------------------------------------------------------


async def test_failure_path_marks_failed_and_flips_schema_status():
    """Connector raises → study marked ``<phase>_FAILED`` and Source
    .schema_status flipped to ``"failed"``."""
    source = _make_db_source()

    session = MagicMock()
    session.commit = AsyncMock()
    session.execute = AsyncMock()
    session.flush = AsyncMock()
    session.add = MagicMock()

    study_row = MagicMock()
    study_row.id = uuid.uuid4()

    get_by_id = AsyncMock(return_value=source)
    is_running = AsyncMock(return_value=False)
    create_study = AsyncMock(return_value=study_row)
    set_schema_status = AsyncMock()
    mark_completed = AsyncMock()
    mark_failed = AsyncMock()

    # Connector raises a ConnectionError → phase becomes CONNECT.
    connector_stub = MagicMock()
    connector_stub.study_schema = AsyncMock(
        side_effect=ConnectionError("DB unreachable at postgresql://u:p@h:5432/db")
    )
    factory_build = MagicMock(return_value=connector_stub)

    factory = _patch_session_factory(session)

    from src.repositories.schema_study_repository import SchemaStudyRepository
    from src.repositories.source_repository import SourceRepository

    with (
        patch("src.tasks.study_source.AsyncSessionLocal", factory),
        patch.object(SourceRepository, "get_by_id", get_by_id, create=False),
        patch.object(
            SourceRepository, "set_schema_status", set_schema_status, create=False
        ),
        patch.object(
            SchemaStudyRepository, "is_running", is_running, create=False
        ),
        patch.object(
            SchemaStudyRepository, "create_study", create_study, create=False
        ),
        patch.object(
            SchemaStudyRepository, "mark_completed", mark_completed, create=False
        ),
        patch.object(
            SchemaStudyRepository, "mark_failed", mark_failed, create=False
        ),
        patch(
            "src.tasks.study_source.ConnectorFactory",
            return_value=MagicMock(build=factory_build),
        ),
    ):
        from src.tasks.study_source import _run

        result = await _run(source.id)

    assert result["status"] == "failed"
    assert result["phase"] == "CONNECT"
    # The error message MUST be sanitised — credentials stripped.
    assert "u:p@" not in result["error"]
    # ``error`` should still mention the host (after sanitisation).
    assert "DB unreachable" in result["error"]

    mark_failed.assert_awaited_once()
    mark_completed.assert_not_awaited()
    statuses = [c.args[1] for c in set_schema_status.await_args_list]
    assert "studying" in statuses
    assert "failed" in statuses


async def test_failure_path_uses_phase_from_schema_study_phase_error():
    """When the connector raises a ``SchemaStudyPhaseError`` carrying an
    explicit ``.phase``, the orchestrator stamps that phase's ``_FAILED``
    state — not the legacy ConnectionError heuristic."""
    from src.services.db_introspection import SchemaStudyPhaseError

    source = _make_db_source()

    session = MagicMock()
    session.commit = AsyncMock()
    session.execute = AsyncMock()
    session.flush = AsyncMock()
    session.add = MagicMock()

    study_row = MagicMock()
    study_row.id = uuid.uuid4()

    get_by_id = AsyncMock(return_value=source)
    is_running = AsyncMock(return_value=False)
    create_study = AsyncMock(return_value=study_row)
    set_schema_status = AsyncMock()
    mark_completed = AsyncMock()
    mark_failed = AsyncMock()

    connector_stub = MagicMock()
    connector_stub.study_schema = AsyncMock(
        side_effect=SchemaStudyPhaseError(
            phase="SAMPLING",
            error_key="SAMPLE_TIMEOUT",
            message="Sampling main.orders timed out.",
        )
    )
    factory_build = MagicMock(return_value=connector_stub)

    factory = _patch_session_factory(session)

    from src.repositories.schema_study_repository import SchemaStudyRepository
    from src.repositories.source_repository import SourceRepository

    with (
        patch("src.tasks.study_source.AsyncSessionLocal", factory),
        patch.object(SourceRepository, "get_by_id", get_by_id, create=False),
        patch.object(
            SourceRepository, "set_schema_status", set_schema_status, create=False
        ),
        patch.object(
            SchemaStudyRepository, "is_running", is_running, create=False
        ),
        patch.object(
            SchemaStudyRepository, "create_study", create_study, create=False
        ),
        patch.object(
            SchemaStudyRepository, "mark_completed", mark_completed, create=False
        ),
        patch.object(
            SchemaStudyRepository, "mark_failed", mark_failed, create=False
        ),
        patch(
            "src.tasks.study_source.ConnectorFactory",
            return_value=MagicMock(build=factory_build),
        ),
    ):
        from src.tasks.study_source import _run

        result = await _run(source.id)

    assert result["status"] == "failed"
    assert result["phase"] == "SAMPLING"
    assert "main.orders timed out" in result["error"]
    # mark_failed stamps the SAMPLING_FAILED state via phase="SAMPLING".
    mark_failed.assert_awaited_once()
    assert mark_failed.await_args.kwargs["phase"] == "SAMPLING"
    statuses = [c.args[1] for c in set_schema_status.await_args_list]
    assert "studying" in statuses
    assert "failed" in statuses


# ---------------------------------------------------------------------------
# Non-database source — skipped without touching state
# ---------------------------------------------------------------------------


async def test_non_database_source_is_skipped():
    """Web sources should never run the studying agent."""
    source = _make_db_source(source_type="web_url")

    session = MagicMock()
    session.commit = AsyncMock()
    session.execute = AsyncMock()
    session.flush = AsyncMock()

    get_by_id = AsyncMock(return_value=source)
    is_running = AsyncMock()
    create_study = AsyncMock()
    set_schema_status = AsyncMock()

    factory = _patch_session_factory(session)

    from src.repositories.schema_study_repository import SchemaStudyRepository
    from src.repositories.source_repository import SourceRepository

    with (
        patch("src.tasks.study_source.AsyncSessionLocal", factory),
        patch.object(SourceRepository, "get_by_id", get_by_id, create=False),
        patch.object(
            SourceRepository, "set_schema_status", set_schema_status, create=False
        ),
        patch.object(
            SchemaStudyRepository, "is_running", is_running, create=False
        ),
        patch.object(
            SchemaStudyRepository, "create_study", create_study, create=False
        ),
    ):
        from src.tasks.study_source import _run

        result = await _run(source.id)

    assert result["status"] == "skipped"
    is_running.assert_not_awaited()
    create_study.assert_not_awaited()
    set_schema_status.assert_not_awaited()


# ---------------------------------------------------------------------------
# Missing source — skipped
# ---------------------------------------------------------------------------


async def test_advisory_lock_serialises_two_concurrent_runs():
    """Two concurrent ``_run()`` calls for the same source MUST end up with
    only ONE ``create_study`` invocation — the advisory lock + is_running
    gate together serialise the gate-check + insert.

    Honesty caveat: a true Postgres advisory-lock race needs a live
    database to reproduce. We simulate the *observable contract* in
    Python by:

    1. Giving each concurrent ``_run()`` its own session with an
       independent ``execute`` AsyncMock (so the mocked
       ``pg_advisory_xact_lock`` call doesn't fail).
    2. Replacing ``lock_for_source`` with a real ``asyncio.Lock``
       wrapped in an ``asynccontextmanager`` — this models the
       Postgres-side serialisation: only one task holds the lock at a
       time.
    3. Sharing a single in-memory ``is_running_state`` flag across
       both tasks. The second task to enter the critical section
       observes the flag set by the first and short-circuits.

    If the production code skipped the lock (today's race), both tasks
    would enter, both observe ``is_running=False`` simultaneously, and
    both call ``create_study`` — the assertion below would catch that
    regression.
    """
    import asyncio
    from contextlib import asynccontextmanager

    source = _make_db_source()

    # Each task gets its own session — but the lock + is_running flag are
    # shared in-process, modelling what Postgres provides at the DB level.
    # Each task opens at least 2 sessions (gate + run loop), and the
    # short-circuit path opens a third on its way to mark_failed if
    # something goes sideways. Provide a fresh mock per `async with` so
    # we never hit StopIteration.
    def _new_session() -> MagicMock:
        s = MagicMock()
        s.commit = AsyncMock()
        s.execute = AsyncMock()
        s.flush = AsyncMock()
        s.add = MagicMock()
        return s

    @asynccontextmanager
    async def _factory() -> Any:
        yield _new_session()

    # Shared in-memory advisory lock — modelled as an asyncio.Lock.
    shared_lock = asyncio.Lock()

    @asynccontextmanager
    async def _lock_for_source(self, sid):  # noqa: ANN001, ARG001
        async with shared_lock:
            yield

    # Shared "is there a running study for this source" flag. The first
    # task to clear the lock flips it; the second task sees it set and
    # short-circuits.
    in_flight: dict[str, bool] = {"flag": False}

    async def _is_running(self, sid):  # noqa: ANN001, ARG001
        return in_flight["flag"]

    create_study_calls: list[uuid.UUID] = []

    async def _create_study(self, *, source_id, agent_version, state):  # noqa: ANN001, ARG001
        # The first task takes the lock + gate, then sets the flag inside
        # the critical section before the second task can observe it.
        in_flight["flag"] = True
        await asyncio.sleep(0)  # yield to encourage interleaving
        study = MagicMock()
        study.id = uuid.uuid4()
        create_study_calls.append(source_id)
        return study

    get_by_id = AsyncMock(return_value=source)
    set_schema_status = AsyncMock()
    mark_completed = AsyncMock()
    mark_failed = AsyncMock()

    schema_doc = _make_schema_document()
    connector_stub = MagicMock()
    connector_stub.study_schema = AsyncMock(return_value=schema_doc)
    factory_build = MagicMock(return_value=connector_stub)

    from src.repositories.schema_study_repository import SchemaStudyRepository
    from src.repositories.source_repository import SourceRepository

    with (
        patch("src.tasks.study_source.AsyncSessionLocal", _factory),
        patch.object(SourceRepository, "get_by_id", get_by_id, create=False),
        patch.object(
            SourceRepository, "set_schema_status", set_schema_status, create=False
        ),
        patch.object(
            SchemaStudyRepository,
            "lock_for_source",
            _lock_for_source,
            create=False,
        ),
        patch.object(
            SchemaStudyRepository, "is_running", _is_running, create=False
        ),
        patch.object(
            SchemaStudyRepository, "create_study", _create_study, create=False
        ),
        patch.object(
            SchemaStudyRepository, "mark_completed", mark_completed, create=False
        ),
        patch.object(
            SchemaStudyRepository, "mark_failed", mark_failed, create=False
        ),
        patch(
            "src.tasks.study_source.ConnectorFactory",
            return_value=MagicMock(build=factory_build),
        ),
    ):
        from src.tasks.study_source import _run

        results = await asyncio.gather(_run(source.id), _run(source.id))

    # Exactly one task created a SchemaStudy; the other observed the flag
    # set inside the critical section and short-circuited.
    assert len(create_study_calls) == 1, create_study_calls
    statuses = sorted(r["status"] for r in results)
    assert statuses == ["completed", "skipped"], statuses


async def test_missing_source_is_skipped():
    """Unknown source id → no-op skip without touching state."""
    session = MagicMock()
    session.commit = AsyncMock()
    session.execute = AsyncMock()
    session.flush = AsyncMock()

    get_by_id = AsyncMock(return_value=None)
    set_schema_status = AsyncMock()

    factory = _patch_session_factory(session)

    from src.repositories.source_repository import SourceRepository

    with (
        patch("src.tasks.study_source.AsyncSessionLocal", factory),
        patch.object(SourceRepository, "get_by_id", get_by_id, create=False),
        patch.object(
            SourceRepository, "set_schema_status", set_schema_status, create=False
        ),
    ):
        from src.tasks.study_source import _run

        result = await _run(uuid.uuid4())

    assert result["status"] == "skipped"
    set_schema_status.assert_not_awaited()
