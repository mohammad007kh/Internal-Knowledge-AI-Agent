"""Integration tests for the ephemeral eval fixtures loader (T-041).

Exercises :func:`evals.fixtures_loader.ephemeral_fixture` against the live test
database: create -> query the seeded rows + temp source -> exit -> assert the
ephemeral schema is gone and the temp source row is deleted. A second test
forces an exception inside the context and asserts teardown still ran.

Requires ``RUN_INTEGRATION_TESTS=1`` and a reachable Postgres (the root
conftest provisions ``test_knowledge_agent`` + applies migrations).
"""

from __future__ import annotations

import os
import uuid
from pathlib import Path

import pytest
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from evals.fixtures_loader import FixtureHandle, ephemeral_fixture
from evals.schema import load_case
from src.models.source import Source
from src.models.user import User

pytestmark = pytest.mark.skipif(
    os.getenv("RUN_INTEGRATION_TESTS") != "1",
    reason="Integration tests require RUN_INTEGRATION_TESTS=1 and a live database",
)

# The database case that references evals/fixtures/cctp-mini.sql.
_CASE_PATH = (
    Path(__file__).resolve().parents[3]
    / "evals"
    / "cases"
    / "database"
    / "db-workspaces-alice-01.json"
)


async def _schema_exists(session: AsyncSession, schema: str) -> bool:
    """Return True iff *schema* is listed in information_schema.schemata."""
    result = await session.execute(
        text(
            "SELECT 1 FROM information_schema.schemata"
            " WHERE schema_name = :schema"
        ),
        {"schema": schema},
    )
    return result.scalar_one_or_none() is not None


async def _count_in_schema(session: AsyncSession, schema: str, table: str) -> int:
    """Count rows in *schema.table* via a fully-qualified read."""
    # Schema/table here are loader-generated / test-literal, never user input.
    result = await session.execute(
        text(f'SELECT count(*) FROM "{schema}"."{table}"')
    )
    return int(result.scalar_one())


async def test_ephemeral_fixture_creates_seeds_and_tears_down(
    db_session: AsyncSession, admin_user: User
) -> None:
    """Happy path: schema + seed + temp source exist inside, gone after exit."""
    case = load_case(_CASE_PATH)
    captured: FixtureHandle | None = None

    async with ephemeral_fixture(
        case, db_session, owner_id=admin_user.id
    ) as handle:
        captured = handle

        # 1. The ephemeral schema exists and the seed rows are queryable.
        #    Assert the seed populated each table (> 0) rather than pinning an
        #    EXACT count — a future edit to cctp-mini.sql's seed data must not
        #    false-fail this loader test, whose contract is "seed + teardown
        #    work", not "the seed has exactly N rows".
        assert await _schema_exists(db_session, handle.schema) is True
        assert await _count_in_schema(db_session, handle.schema, "users") > 0
        assert (
            await _count_in_schema(db_session, handle.schema, "workspaces") > 0
        )

        # 2. The temp database source is registered and findable by id.
        source = await db_session.get(Source, handle.source_id)
        assert source is not None
        assert source.source_type.value == "database"
        assert source.owner_id == admin_user.id

    # 3. After exit: schema dropped, temp source row deleted.
    assert captured is not None
    assert await _schema_exists(db_session, captured.schema) is False
    assert await db_session.get(Source, captured.source_id) is None


async def test_ephemeral_fixture_tears_down_on_exception(
    db_session: AsyncSession, admin_user: User
) -> None:
    """Teardown must run even when the body raises — no leaked schema/source."""
    case = load_case(_CASE_PATH)
    leaked_schema: str | None = None
    leaked_source_id: uuid.UUID | None = None

    class _Boom(RuntimeError):
        pass

    with pytest.raises(_Boom):
        async with ephemeral_fixture(
            case, db_session, owner_id=admin_user.id
        ) as handle:
            leaked_schema = handle.schema
            leaked_source_id = handle.source_id
            # Sanity: it really was created before we blow up.
            assert await _schema_exists(db_session, handle.schema) is True
            raise _Boom("forced failure inside the fixture body")

    assert leaked_schema is not None
    assert leaked_source_id is not None
    assert await _schema_exists(db_session, leaked_schema) is False
    assert await db_session.get(Source, leaked_source_id) is None
