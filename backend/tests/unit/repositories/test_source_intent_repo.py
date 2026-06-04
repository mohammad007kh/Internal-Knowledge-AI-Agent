"""Unit tests for ``SourceRepository`` intent methods (T-020).

004-agentic-pipeline US1 / FR-001.

These tests do NOT hit a real Postgres (the unit suite runs without Docker /
pgvector — see ``tests/unit/conftest.py``). Following the established repo-test
convention (``test_admin_audit_log_repository.py``), they drive the repository
with an AsyncSession-shaped mock that captures the compiled SQL of every
statement, then assert on:

  * the predicate set the statement builds (e.g. the conditional UPDATE's
    ``intent_status != 'user_set'`` guard — the TOCTOU-safe race protection),
  * the SET columns the statement writes (propose must NEVER write ``purpose``
    or ``cross_source_hints``),
  * the affected-row semantics the method returns to its caller.

The "``user_set`` row is untouched by the conditional update" gate criterion is
proven two ways here:
  1. structurally — the compiled UPDATE carries ``intent_status != 'user_set'``
     in its WHERE clause AND never names ``purpose`` / ``cross_source_hints``
     in its SET clause, so Postgres physically cannot touch a ``user_set`` row
     or the admin-only fields; and
  2. behaviourally — when the DB reports 0 affected rows (the race-loser case),
     ``propose_intent_conditional`` returns ``False`` and the caller
     short-circuits.
"""

from __future__ import annotations

import os
import uuid
from unittest.mock import AsyncMock, MagicMock

import pytest

# Required env vars must be set before importing src modules.
os.environ.setdefault("DATABASE_URL", "postgresql+asyncpg://test:test@localhost/test")
os.environ.setdefault("JWT_SECRET_KEY", "test-jwt-secret-key-at-least-32-chars-long!!")
os.environ.setdefault("JWT_REFRESH_SECRET_KEY", "test-jwt-refresh-secret-key-32-chars!!")
os.environ.setdefault("MINIO_ENDPOINT", "localhost:9000")
os.environ.setdefault("MINIO_ACCESS_KEY", "testaccess")
os.environ.setdefault("MINIO_SECRET_KEY", "testsecret")
os.environ.setdefault("ENCRYPTION_KEY", "dGVzdGVuY3J5cHRpb25rZXkxMjM0NTY3ODk=")

from sqlalchemy.dialects import postgresql as pg_dialect

from src.core.exceptions import BadRequestError, NotFoundError
from src.repositories.source_repository import (
    INTENT_EXAMPLE_QUESTIONS_MAX,
    INTENT_OUT_OF_SCOPE_MAX,
    INTENT_PURPOSE_MAX_CHARS,
    SourceRepository,
)

_PG_DIALECT = pg_dialect.dialect()


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _make_session(*, returned_id: uuid.UUID | None, intent_row: object | None = None):
    """Build an AsyncSession-shaped mock that captures compiled SQL.

    ``returned_id`` controls ``result.scalars().first()`` — the value
    ``update_intent`` / ``propose_intent_conditional`` use to decide whether a
    row was affected. Pass ``None`` to simulate "0 rows affected" (the
    race-loser / not-found case).

    ``intent_row`` controls ``result.one_or_none()`` for ``get_intent``.

    The compiled SQL of every executed statement is appended to
    ``session.captured_sql`` (compiled against the Postgres dialect so JSONB
    columns render cleanly).
    """
    session = MagicMock()
    session.captured_sql = []  # type: ignore[attr-defined]
    session.captured_params = []  # type: ignore[attr-defined]

    async def _execute(stmt):
        # ``.values(...)`` on an UPDATE renders as bind parameters, so the
        # status literals ('user_set'/'ai_set') live in the compiled params,
        # not the SQL text. Capture BOTH so tests can assert on either.
        compiled = stmt.compile(dialect=_PG_DIALECT)
        session.captured_sql.append(str(compiled))
        session.captured_params.append(dict(compiled.params))
        result = MagicMock()
        result.scalars.return_value.first.return_value = returned_id
        result.one_or_none.return_value = intent_row
        return result

    session.execute = AsyncMock(side_effect=_execute)
    return session


def _last_sql(session) -> str:
    return session.captured_sql[-1]


def _last_param_values(session) -> set[str]:
    """All scalar bind-param values of the last statement, as strings."""
    return {str(v) for v in session.captured_params[-1].values()}


# ---------------------------------------------------------------------------
# get_intent
# ---------------------------------------------------------------------------


class TestGetIntent:
    async def test_returns_six_intent_fields(self) -> None:
        sid = uuid.uuid4()
        row = MagicMock()
        row.purpose = "Answers billing questions."
        row.example_questions = ["How do I get a refund?"]
        row.out_of_scope = ["Legal advice"]
        row.cross_source_hints = [{"topic": "HR", "source_id": str(uuid.uuid4())}]
        row.intent_status = "ai_set"
        row.intent_updated_at = None
        session = _make_session(returned_id=None, intent_row=row)
        repo = SourceRepository(session)

        out = await repo.get_intent(sid)

        assert set(out) == {
            "purpose",
            "example_questions",
            "out_of_scope",
            "cross_source_hints",
            "intent_status",
            "intent_updated_at",
        }
        assert out["purpose"] == "Answers billing questions."
        assert out["intent_status"] == "ai_set"
        # Reads the live row, filtering soft-deleted rows out.
        assert "DELETED_AT IS NULL" in _last_sql(session).upper()

    async def test_missing_source_raises_not_found(self) -> None:
        session = _make_session(returned_id=None, intent_row=None)
        repo = SourceRepository(session)

        with pytest.raises(NotFoundError):
            await repo.get_intent(uuid.uuid4())


# ---------------------------------------------------------------------------
# update_intent (admin save -> user_set)
# ---------------------------------------------------------------------------


class TestUpdateIntent:
    async def test_flips_status_to_user_set_and_stamps_timestamp(self) -> None:
        sid = uuid.uuid4()
        session = _make_session(returned_id=sid)
        repo = SourceRepository(session)

        affected = await repo.update_intent(
            sid,
            purpose="Source of truth for billing.",
            example_questions=["How do refunds work?"],
        )

        assert affected is True
        sql = _last_sql(session).upper()
        # Status flip to user_set + timestamp stamp are unconditional.
        assert "INTENT_STATUS" in sql
        assert "user_set" in _last_param_values(session)
        assert "INTENT_UPDATED_AT" in sql
        assert "NOW()" in sql
        # Provided fields are written.
        assert "PURPOSE" in sql
        assert "EXAMPLE_QUESTIONS" in sql

    async def test_omitted_fields_are_not_written(self) -> None:
        """Only provided fields land in the SET clause (None == not provided)."""
        sid = uuid.uuid4()
        session = _make_session(returned_id=sid)
        repo = SourceRepository(session)

        await repo.update_intent(sid, purpose="Just the purpose.")

        sql = _last_sql(session).upper()
        assert "PURPOSE" in sql
        # No example_questions / out_of_scope / cross_source_hints provided.
        assert "EXAMPLE_QUESTIONS" not in sql
        assert "OUT_OF_SCOPE" not in sql
        assert "CROSS_SOURCE_HINTS" not in sql

    async def test_missing_row_returns_false(self) -> None:
        session = _make_session(returned_id=None)
        repo = SourceRepository(session)

        affected = await repo.update_intent(uuid.uuid4(), purpose="x")

        assert affected is False

    async def test_purpose_over_cap_raises(self) -> None:
        session = _make_session(returned_id=uuid.uuid4())
        repo = SourceRepository(session)

        with pytest.raises(BadRequestError):
            await repo.update_intent(
                uuid.uuid4(),
                purpose="x" * (INTENT_PURPOSE_MAX_CHARS + 1),
            )
        # Cap is rejected BEFORE any SQL is emitted.
        assert session.captured_sql == []

    async def test_purpose_at_cap_is_accepted(self) -> None:
        sid = uuid.uuid4()
        session = _make_session(returned_id=sid)
        repo = SourceRepository(session)

        affected = await repo.update_intent(
            sid, purpose="x" * INTENT_PURPOSE_MAX_CHARS
        )

        assert affected is True

    async def test_too_many_example_questions_raises(self) -> None:
        session = _make_session(returned_id=uuid.uuid4())
        repo = SourceRepository(session)

        with pytest.raises(BadRequestError):
            await repo.update_intent(
                uuid.uuid4(),
                example_questions=["q"] * (INTENT_EXAMPLE_QUESTIONS_MAX + 1),
            )

    async def test_too_many_out_of_scope_raises(self) -> None:
        session = _make_session(returned_id=uuid.uuid4())
        repo = SourceRepository(session)

        with pytest.raises(BadRequestError):
            await repo.update_intent(
                uuid.uuid4(),
                out_of_scope=["t"] * (INTENT_OUT_OF_SCOPE_MAX + 1),
            )


# ---------------------------------------------------------------------------
# propose_intent_conditional (AI proposal -> ai_set, guarded)
# ---------------------------------------------------------------------------


class TestProposeIntentConditional:
    async def test_writes_only_ai_fields_plus_status_and_timestamp(self) -> None:
        sid = uuid.uuid4()
        session = _make_session(returned_id=sid)
        repo = SourceRepository(session)

        affected = await repo.propose_intent_conditional(
            sid,
            example_questions=["What is the SLA?"],
            out_of_scope=["Tax filing"],
        )

        assert affected is True
        sql = _last_sql(session).upper()
        # AI-writable fields + status/timestamp.
        assert "EXAMPLE_QUESTIONS" in sql
        assert "OUT_OF_SCOPE" in sql
        assert "ai_set" in _last_param_values(session)
        assert "INTENT_UPDATED_AT" in sql
        assert "NOW()" in sql

    async def test_set_clause_never_writes_purpose_or_cross_source_hints(self) -> None:
        """Propose is bundle-level but excludes the two admin-only fields.

        ``purpose`` (FR-002) and ``cross_source_hints`` (admin-only in v1) must
        never appear in the SET clause — we inspect the SET clause specifically
        (the WHERE clause is allowed to reference other columns).
        """
        sid = uuid.uuid4()
        session = _make_session(returned_id=sid)
        repo = SourceRepository(session)

        await repo.propose_intent_conditional(
            sid,
            example_questions=["q"],
            out_of_scope=["t"],
        )

        sql = _last_sql(session).upper()
        set_clause = sql.split("WHERE", 1)[0]
        assert "PURPOSE" not in set_clause
        assert "CROSS_SOURCE_HINTS" not in set_clause

    async def test_where_clause_guards_against_user_set(self) -> None:
        """The TOCTOU-safe guard: WHERE intent_status != 'user_set'.

        This is the structural proof that a ``user_set`` row is physically
        unreachable by the conditional update — Postgres filters it out before
        applying the SET.
        """
        sid = uuid.uuid4()
        session = _make_session(returned_id=sid)
        repo = SourceRepository(session)

        await repo.propose_intent_conditional(
            sid,
            example_questions=["q"],
            out_of_scope=["t"],
        )

        sql = _last_sql(session).upper()
        where_clause = sql.split("WHERE", 1)[1]
        assert "INTENT_STATUS" in where_clause
        assert "!=" in where_clause or "<>" in where_clause
        # The guard compares against the 'user_set' literal (a bound param).
        # propose writes status='ai_set', so 'user_set' can only originate
        # from the WHERE guard.
        assert "user_set" in _last_param_values(session)

    async def test_user_set_row_is_untouched_zero_rows_affected(self) -> None:
        """Behavioural proof: a concurrent admin save (user_set) wins the race.

        When the guarded UPDATE matches no row (the DB returns no id because the
        row is already ``user_set``), the method reports ``False`` so the
        caller short-circuits and never assumes its proposal landed. Combined
        with ``test_where_clause_guards_against_user_set``, this proves a
        ``user_set`` row is left entirely unchanged.
        """
        # returned_id=None => RETURNING yields no row => 0 rows affected.
        session = _make_session(returned_id=None)
        repo = SourceRepository(session)

        affected = await repo.propose_intent_conditional(
            uuid.uuid4(),
            example_questions=["q"],
            out_of_scope=["t"],
        )

        assert affected is False

    async def test_propose_respects_caps(self) -> None:
        session = _make_session(returned_id=uuid.uuid4())
        repo = SourceRepository(session)

        with pytest.raises(BadRequestError):
            await repo.propose_intent_conditional(
                uuid.uuid4(),
                example_questions=["q"] * (INTENT_EXAMPLE_QUESTIONS_MAX + 1),
                out_of_scope=["t"],
            )
        with pytest.raises(BadRequestError):
            await repo.propose_intent_conditional(
                uuid.uuid4(),
                example_questions=["q"],
                out_of_scope=["t"] * (INTENT_OUT_OF_SCOPE_MAX + 1),
            )
