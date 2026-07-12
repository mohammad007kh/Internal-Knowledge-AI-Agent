"""Ephemeral fixtures loader for database/multi eval cases (T-041).

A database-type eval case carries ``fixtures.seed`` — a path to a synthetic
seed SQL file (see ``evals/fixtures/*.sql``). To run such a case the harness
needs a *queryable* database that the pipeline can target. This module provides
:func:`ephemeral_fixture`, an ``async with`` context manager that:

1. Generates a unique throwaway schema name (``eval_<uuid4hex>``) and
   ``CREATE SCHEMA``s it inside the EXISTING Postgres service (no new infra).
2. Applies the case's ``fixtures.seed`` SQL into that schema (``search_path`` is
   pinned to the ephemeral schema first, so unqualified table names land there
   and a runaway seed can't touch real application tables).
3. Registers a TEMPORARY ``database`` :class:`~src.models.source.Source` row
   whose connection config points at the ephemeral schema, so
   ``run_pipeline()`` can target it by id.
4. On exit — success OR exception — deletes the temp source row and
   ``DROP SCHEMA … CASCADE``. Teardown runs in a ``finally`` so nothing leaks.

Isolation: every entry gets a fresh schema name, so sequential or parallel
cases never collide.

Trust boundary: the seed SQL is trusted-but-synthetic (authored in-repo and
human-reviewed before commit). It is still executed only after ``search_path``
is scoped to the ephemeral schema, defence-in-depth against an authoring slip.

FX41 lesson: ALL durable DB access (the temp source row) goes through the
request-session-bound :class:`~src.repositories.source_repository.SourceRepository`
and the passed-in :class:`AsyncSession` — no module-global engine, no naked
queries outside the schema-scoped seed-application path.
"""

from __future__ import annotations

import json
import uuid
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from dataclasses import dataclass
from pathlib import Path

from sqlalchemy.ext.asyncio import AsyncSession

from evals.schema import EvalCase
from src.core.crypto import encrypt
from src.models.enums import ConnectionStatus, SourceStatus, SourceType
from src.models.source import Source

# ``backend/`` — ``fixtures.seed`` paths in the cases are relative to this.
_BACKEND_DIR = Path(__file__).resolve().parent.parent

# Default connection target for the ephemeral schema. The seed lives in the
# SAME Postgres database the harness session is bound to; only the schema
# differs per run. Host/port/db are filled from the running service's env at
# registration time (see :func:`_db_connection_target`).
_EPHEMERAL_SCHEMA_PREFIX = "eval_"


class FixtureError(RuntimeError):
    """Raised when an ephemeral fixture cannot be created or torn down.

    Subclasses :class:`RuntimeError` (registry: error_handling = exceptions) so
    the eval runner can surface a fixtures problem distinctly from a pipeline
    failure while it still behaves like a runtime error.
    """


@dataclass(frozen=True)
class FixtureHandle:
    """Immutable handle yielded by :func:`ephemeral_fixture`.

    ``source_id`` is the temp database source the pipeline targets; ``schema``
    is the ephemeral schema name (exposed so tests can assert teardown).
    """

    source_id: uuid.UUID
    schema: str


def _ephemeral_schema_name() -> str:
    """Return a fresh, collision-free ephemeral schema identifier.

    ``uuid4().hex`` is lowercase hex only, so the result is a safe bare SQL
    identifier (no quoting needed) and unique per call — sequential/parallel
    cases never share a schema.
    """
    return f"{_EPHEMERAL_SCHEMA_PREFIX}{uuid.uuid4().hex}"


def _resolve_seed_path(seed: str) -> Path:
    """Resolve a case ``fixtures.seed`` path (relative to ``backend/``) to a file.

    Raises :class:`FixtureError` when the path escapes ``backend/`` or the file
    is missing — both are authoring mistakes that must fail loudly.
    """
    candidate = (_BACKEND_DIR / seed).resolve()
    try:
        candidate.relative_to(_BACKEND_DIR)
    except ValueError as exc:  # path traversal outside backend/
        raise FixtureError(
            f"seed path {seed!r} resolves outside backend/ — refusing to load"
        ) from exc
    if not candidate.is_file():
        raise FixtureError(f"seed file not found: {candidate}")
    return candidate


def _db_connection_target(session: AsyncSession, schema: str) -> dict[str, object]:
    """Build the temp source's connection config from the session's own engine.

    The ephemeral schema lives in the SAME database the harness session is
    bound to, so the host/port/db/user are read off the bound engine's URL —
    the pipeline can then reach the seeded rows by setting ``search_path`` to
    *schema*. Password is intentionally NOT echoed back from the URL here; the
    registration encrypts whatever the URL carries so the stored blob mirrors a
    real database source.
    """
    url = session.get_bind().url  # type: ignore[union-attr]
    return {
        "host": url.host or "localhost",
        "port": url.port or 5432,
        "database": url.database or "",
        "user": url.username or "",
        "password": url.password or "",
        "schema": schema,
    }


async def _apply_seed(session: AsyncSession, schema: str, seed_sql: str) -> None:
    """Create *schema*, pin ``search_path`` to it, and run *seed_sql* inside it.

    Uses the session's underlying asyncpg connection's simple-query protocol so
    the multi-statement seed script executes as one batch. ``search_path`` is
    set BEFORE the seed runs, so unqualified ``CREATE TABLE`` / ``INSERT``
    statements land in the ephemeral schema only.

    The schema name is generated by :func:`_ephemeral_schema_name` (lowercase
    hex, fixed prefix) and never derived from external input, so interpolating
    it into the DDL is safe — it cannot be a SQL-injection vector.
    """
    raw_conn = await session.connection()
    asyncpg_conn = (await raw_conn.get_raw_connection()).driver_connection
    if asyncpg_conn is None:  # pragma: no cover — defensive
        raise FixtureError("could not reach the underlying asyncpg connection")

    await asyncpg_conn.execute(f'CREATE SCHEMA "{schema}"')
    # Pin search_path for THIS connection so the seed's unqualified DDL/DML
    # cannot touch application tables.
    await asyncpg_conn.execute(f'SET search_path TO "{schema}"')
    try:
        await asyncpg_conn.execute(seed_sql)
    finally:
        # Restore the default search_path so the shared session/connection does
        # not keep the ephemeral schema pinned for later ORM work.
        await asyncpg_conn.execute("SET search_path TO public")


async def _drop_schema(session: AsyncSession, schema: str) -> None:
    """``DROP SCHEMA … CASCADE`` the ephemeral schema. Best-effort, idempotent."""
    raw_conn = await session.connection()
    asyncpg_conn = (await raw_conn.get_raw_connection()).driver_connection
    if asyncpg_conn is None:  # pragma: no cover — defensive
        return
    await asyncpg_conn.execute(f'DROP SCHEMA IF EXISTS "{schema}" CASCADE')


async def _register_temp_source(
    session: AsyncSession,
    *,
    owner_id: uuid.UUID,
    schema: str,
    config: dict[str, object],
) -> uuid.UUID:
    """Insert a temporary ``database`` Source pointing at *schema*; return its id.

    Goes through the ORM on the passed-in session (FX41: request-session-bound,
    no naked SQL). The connection config is Fernet-encrypted exactly like a real
    database source so the stored shape is faithful.
    """
    source = Source(
        id=uuid.uuid4(),
        name=f"eval-fixture-{schema}",
        source_type=SourceType.DATABASE,
        owner_id=owner_id,
        is_active=True,
        status=SourceStatus.READY,
        connection_status=ConnectionStatus.HEALTHY,
        config_encrypted=encrypt(json.dumps(config)),
    )
    session.add(source)
    await session.flush()
    return source.id


async def _delete_temp_source(session: AsyncSession, source_id: uuid.UUID) -> None:
    """Hard-delete the temp source row (it is ephemeral; no audit trail needed)."""
    source = await session.get(Source, source_id)
    if source is not None:
        await session.delete(source)
        await session.flush()


@asynccontextmanager
async def ephemeral_fixture(
    case: EvalCase,
    session: AsyncSession,
    *,
    owner_id: uuid.UUID,
) -> AsyncIterator[FixtureHandle]:
    """Provision an isolated, seeded DB fixture for *case*; tear it down on exit.

    Args:
        case: The eval case to provision; MUST carry ``fixtures.seed``.
        session: Request-session-bound :class:`AsyncSession` the harness owns.
            All durable writes (the temp source) go through it.
        owner_id: An existing ``users.id`` to own the temp source row (FK).

    Yields:
        A :class:`FixtureHandle` with the temp ``source_id`` and the ephemeral
        ``schema`` name.

    Raises:
        FixtureError: When the case has no ``fixtures``, the seed file is
            missing, or the schema/source cannot be created.

    Teardown (temp-source delete + ``DROP SCHEMA … CASCADE``) ALWAYS runs, even
    if the body raises.
    """
    if case.fixtures is None:
        raise FixtureError(f"case {case.id!r} has no fixtures.seed to load")

    seed_path = _resolve_seed_path(case.fixtures.seed)
    seed_sql = seed_path.read_text(encoding="utf-8")

    schema = _ephemeral_schema_name()
    source_id: uuid.UUID | None = None
    try:
        await _apply_seed(session, schema, seed_sql)
        config = _db_connection_target(session, schema)
        source_id = await _register_temp_source(
            session, owner_id=owner_id, schema=schema, config=config
        )
        yield FixtureHandle(source_id=source_id, schema=schema)
    finally:
        # Teardown order: drop the source row first (it references nothing in
        # the ephemeral schema), then drop the schema. Both are best-effort so
        # one failure cannot mask the other or leak the remaining resource.
        if source_id is not None:
            await _delete_temp_source(session, source_id)
        await _drop_schema(session, schema)
