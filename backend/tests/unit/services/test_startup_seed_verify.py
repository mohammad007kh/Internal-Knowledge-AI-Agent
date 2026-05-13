"""Unit tests for :func:`startup_seed.verify_all_stages_configured`.

ARCH-A startup assertion: every slot listed in
``src.api.v1.admin.llm_settings.STAGES`` MUST end up with a row in
``llm_configurations`` whose ``ai_model_id`` is non-NULL.  The verifier
collects the slots that fail either gate, logs them at ``ERROR`` level,
and returns the list.  It does NOT raise — boot must remain best-effort
per the lifespan contract.

These tests don't touch a real database; they patch the SQLAlchemy
session's ``execute`` to return a hand-built row list, so they're
hermetic and run under the lightweight unit-test conftest.
"""
from __future__ import annotations

import os

# Env preamble — same pattern as the other backend unit-test modules.
# Must run before any ``src.*`` import triggers Settings validation.
os.environ.setdefault("DATABASE_URL", "postgresql+asyncpg://test:test@localhost/test")
os.environ.setdefault("JWT_SECRET_KEY", "test-jwt-secret-key-at-least-32-chars-long!!")
os.environ.setdefault("JWT_REFRESH_SECRET_KEY", "test-jwt-refresh-secret-key-32-chars!!")
os.environ.setdefault("MINIO_ENDPOINT", "localhost:9000")
os.environ.setdefault("MINIO_ACCESS_KEY", "testaccess")
os.environ.setdefault("MINIO_SECRET_KEY", "testsecret")
os.environ.setdefault("ENCRYPTION_KEY", "dGVzdGVuY3J5cHRpb25rZXkxMjM0NTY3ODk=")

import logging  # noqa: E402
import uuid  # noqa: E402
from typing import Any  # noqa: E402
from unittest.mock import AsyncMock, MagicMock  # noqa: E402

import pytest  # noqa: E402

from src.api.v1.admin.llm_settings import STAGES  # noqa: E402
from src.services import startup_seed  # noqa: E402


def _row(slot_name: str, ai_model_id: Any) -> MagicMock:
    """Build a fake ``LLMConfiguration`` row with the two fields we read."""
    r = MagicMock()
    r.slot_name = slot_name
    r.ai_model_id = ai_model_id
    return r


def _session_returning(rows: list[MagicMock]) -> AsyncMock:
    """Build an ``AsyncSession`` whose ``execute(...).scalars().all()``
    returns *rows*.

    The verifier calls ``await session.execute(select(...))`` and then
    ``.scalars().all()``.  ``execute`` is an ``AsyncMock`` so the await
    works; the return value's ``.scalars().all()`` is a plain MagicMock
    chain that yields the row list.
    """
    session = AsyncMock()
    result = MagicMock()
    result.scalars.return_value.all.return_value = rows
    session.execute.return_value = result
    return session


@pytest.mark.asyncio
async def test_all_stages_linked_returns_empty_list(caplog) -> None:
    """Happy path — every slot has a linked AIModel.

    The verifier must return an empty list AND log ``"startup check OK"``
    at INFO level.  No ERROR record is emitted.
    """
    ai_model_id = uuid.uuid4()
    rows = [_row(stage, ai_model_id) for stage in STAGES]
    session = _session_returning(rows)

    with caplog.at_level(logging.INFO, logger="src.services.startup_seed"):
        bad = await startup_seed.verify_all_stages_configured(session)

    assert bad == []
    ok_lines = [
        r for r in caplog.records
        if "startup check OK" in r.getMessage()
        and r.name == "src.services.startup_seed"
    ]
    assert len(ok_lines) == 1
    # No ERROR-level "FAILED" record on the happy path.
    assert not any(
        r.levelno >= logging.ERROR and "FAILED" in r.getMessage()
        for r in caplog.records
    )


@pytest.mark.asyncio
async def test_missing_slot_logged_as_error(caplog) -> None:
    """A slot that has no row at all is reported under ``missing``."""
    ai_model_id = uuid.uuid4()
    # Drop the seeded "synthesizer" row to simulate the ARCH-A bug class:
    # the slot the resolver looks up doesn't exist in the DB at all.
    rows = [_row(stage, ai_model_id) for stage in STAGES if stage != "synthesizer"]
    session = _session_returning(rows)

    with caplog.at_level(logging.ERROR, logger="src.services.startup_seed"):
        bad = await startup_seed.verify_all_stages_configured(session)

    assert bad == ["synthesizer"]
    err_lines = [
        r for r in caplog.records
        if r.levelno >= logging.ERROR
        and "FAILED" in r.getMessage()
    ]
    assert len(err_lines) == 1
    assert "synthesizer" in err_lines[0].getMessage()


@pytest.mark.asyncio
async def test_unlinked_slot_logged_as_error(caplog) -> None:
    """A row with ``ai_model_id=None`` is reported under ``unlinked``.

    This is the silent-failure case the verifier was added to catch:
    the row exists, ``llm_settings`` returns it, but the resolver can't
    actually load a model from it.
    """
    ai_model_id = uuid.uuid4()
    rows = []
    for stage in STAGES:
        rows.append(_row(stage, None if stage == "input_guard" else ai_model_id))
    session = _session_returning(rows)

    with caplog.at_level(logging.ERROR, logger="src.services.startup_seed"):
        bad = await startup_seed.verify_all_stages_configured(session)

    assert bad == ["input_guard"]
    err_lines = [
        r for r in caplog.records
        if r.levelno >= logging.ERROR
    ]
    assert len(err_lines) == 1
    assert "input_guard" in err_lines[0].getMessage()


@pytest.mark.asyncio
async def test_multiple_bad_slots_all_reported(caplog) -> None:
    """All failing slots are surfaced in a single ERROR line.

    The verifier must NOT short-circuit at the first failure — operators
    need to see the full list so they can fix them in one trip to
    ``/admin/llm-settings``.
    """
    ai_model_id = uuid.uuid4()
    # Two failure modes at once — one row dropped, one row unlinked.
    rows = []
    for stage in STAGES:
        if stage == "reflector":
            continue  # missing entirely
        rows.append(_row(stage, None if stage == "titler" else ai_model_id))
    session = _session_returning(rows)

    with caplog.at_level(logging.ERROR, logger="src.services.startup_seed"):
        bad = await startup_seed.verify_all_stages_configured(session)

    assert bad == sorted(["reflector", "titler"])
    err_lines = [
        r for r in caplog.records
        if r.levelno >= logging.ERROR
    ]
    assert len(err_lines) == 1
    msg = err_lines[0].getMessage()
    assert "reflector" in msg
    assert "titler" in msg


@pytest.mark.asyncio
async def test_verifier_does_not_raise_on_empty_table(caplog) -> None:
    """Lifespan contract — verifier must never raise.

    Empty ``llm_configurations`` table (fresh DB before any seeding) is
    the worst case: every slot is missing.  The verifier must log and
    return cleanly so :func:`run_startup_seeding`'s outer guard isn't
    needed to swallow the exception.
    """
    session = _session_returning([])

    with caplog.at_level(logging.ERROR, logger="src.services.startup_seed"):
        bad = await startup_seed.verify_all_stages_configured(session)

    assert bad == sorted(STAGES)
    # Single bright "STARTUP CHECK FAILED" line — no traceback.
    err_lines = [
        r for r in caplog.records
        if r.levelno >= logging.ERROR
    ]
    assert len(err_lines) == 1
    assert err_lines[0].exc_info is None
