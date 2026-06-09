"""Unit tests for the SQL-dialect schema inspector (studying-agent Phase 2).

The inspector talks to a SQLAlchemy *async* engine, but the project's test
environment doesn't ship an async SQLite driver (no ``aiosqlite``). So we
build a real **synchronous** in-memory SQLite engine — with a shared
``StaticPool`` connection so the schema/data survives across ``connect()``
calls — and wrap it in a tiny shim that exposes just the async surface the
inspector uses (``connect`` → async ctx mgr with ``execute`` / ``run_sync``,
plus ``dispose``). This keeps the test honest about reflection / sampling
behaviour without needing an extra dependency.

What's covered:

* INVENTORY finds the tables (system schemas excluded).
* COLUMNS reflects names / types / nullability / PK / FK / indexes.
* SAMPLING returns ≤3 PII-redacted values and flags the email column.
* DESCRIBING is invoked per-table + once for the summary (mocked LLM);
  the returned description + tags land on the document.
* A per-table COLUMNS failure → PhaseError + partial, study continues.
* A per-table SAMPLING failure → PhaseError + partial, columns kept.
* The assembled SchemaDocument validates (strict) and the fingerprint is
  non-empty.
"""

from __future__ import annotations

import os
from typing import Any
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
import sqlalchemy as sa
from sqlalchemy import create_engine
from sqlalchemy.pool import StaticPool

os.environ.setdefault("DATABASE_URL", "postgresql+asyncpg://test:test@localhost/test")
os.environ.setdefault("JWT_SECRET_KEY", "test-jwt-secret-key-at-least-32-chars-long!!")
os.environ.setdefault("JWT_REFRESH_SECRET_KEY", "test-jwt-refresh-secret-key-32-chars!!")
os.environ.setdefault("MINIO_ENDPOINT", "localhost:9000")
os.environ.setdefault("MINIO_ACCESS_KEY", "testaccess")
os.environ.setdefault("MINIO_SECRET_KEY", "testsecret")
os.environ.setdefault("ENCRYPTION_KEY", "dGVzdGVuY3J5cHRpb25rZXkxMjM0NTY3ODk=")

pytestmark = pytest.mark.asyncio


# ---------------------------------------------------------------------------
# Sync-SQLite-backed async engine shim
# ---------------------------------------------------------------------------


class _AsyncConnShim:
    """Wraps a live sync ``Connection`` with the async API the inspector uses."""

    def __init__(self, sync_conn: sa.Connection) -> None:
        self._conn = sync_conn

    async def __aenter__(self) -> _AsyncConnShim:
        return self

    async def __aexit__(self, *exc: object) -> None:
        # Leave the (StaticPool-shared) connection open across calls.
        return None

    async def execute(self, *args: Any, **kwargs: Any) -> Any:
        return self._conn.execute(*args, **kwargs)

    async def run_sync(self, fn: Any) -> Any:
        return fn(self._conn)


class _AsyncEngineShim:
    """Minimal async-engine stand-in over a sync SQLAlchemy engine."""

    def __init__(self, sync_engine: sa.Engine) -> None:
        self._engine = sync_engine
        self._conn: sa.Connection | None = None

    def connect(self) -> _AsyncConnShim:
        if self._conn is None or self._conn.closed:
            self._conn = self._engine.connect()
        return _AsyncConnShim(self._conn)

    async def dispose(self) -> None:
        if self._conn is not None and not self._conn.closed:
            self._conn.close()
        self._engine.dispose()


def _make_sqlite_engine_with_fixtures() -> sa.Engine:
    """Create an in-memory SQLite DB with two related tables + sample rows."""
    engine = create_engine(
        "sqlite://",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    with engine.begin() as conn:
        conn.execute(
            sa.text(
                "CREATE TABLE customers ("
                "  id INTEGER PRIMARY KEY,"
                "  full_name TEXT NOT NULL,"
                "  email TEXT,"
                "  signup_date DATE"
                ")"
            )
        )
        conn.execute(
            sa.text(
                "CREATE TABLE orders ("
                "  id INTEGER PRIMARY KEY,"
                "  customer_id INTEGER NOT NULL REFERENCES customers(id),"
                "  amount_cents INTEGER NOT NULL,"
                "  note TEXT"
                ")"
            )
        )
        conn.execute(
            sa.text("CREATE INDEX ix_orders_customer ON orders (customer_id)")
        )
        conn.execute(
            sa.text(
                "INSERT INTO customers (id, full_name, email, signup_date) VALUES "
                "(1, 'Alice Smith', 'alice@example.com', '2024-01-10'),"
                "(2, 'Bob Jones', 'bob@example.com', '2024-02-15'),"
                "(3, 'Carol King', 'carol@example.com', '2024-03-20'),"
                "(4, 'Dan Lee', 'dan@example.com', '2024-04-25')"
            )
        )
        conn.execute(
            sa.text(
                "INSERT INTO orders (id, customer_id, amount_cents, note) VALUES "
                "(1, 1, 1999, 'gift'),"
                "(2, 1, 4500, NULL),"
                "(3, 2, 250, 'sample')"
            )
        )
    return engine


def _stub_resolver() -> tuple[Any, AsyncMock]:
    """Return a fake AIModelResolver whose LLM returns canned JSON.

    The single ``chat.completions.create`` AsyncMock is shared across the
    per-table calls and the summary call, so the test can assert the call
    count (n tables + 1).
    """
    create_mock = AsyncMock()
    call_count = {"n": 0}

    async def _create(**kwargs: Any) -> Any:
        call_count["n"] += 1
        # The last call (after every table) is the corpus summary; pick the
        # payload based on the response_format name.
        fmt_name = kwargs["response_format"]["json_schema"]["name"]
        if fmt_name == "corpus_summary":
            content = '{"summary": "This database tracks customers and their orders."}'
        else:
            content = (
                '{"description": "Stores rows for this relation.", '
                '"tags": ["transactional"]}'
            )
        msg = MagicMock()
        msg.content = content
        choice = MagicMock()
        choice.message = msg
        resp = MagicMock()
        resp.choices = [choice]
        return resp

    create_mock.side_effect = _create

    http_client = MagicMock()
    http_client.chat.completions.create = create_mock

    client = MagicMock()
    client.model_id = "gpt-test"
    client.temperature = 0.0
    client.max_tokens = 256
    client.http_client = http_client

    resolver = MagicMock()
    resolver.resolve = AsyncMock(return_value=client)
    return resolver, create_mock


def _patch_engine(engine: sa.Engine):
    """Patch ``sql_inspector._build_engine`` to yield the shim engine."""

    async def _build(connection_string: str, db_type: str) -> _AsyncEngineShim:  # noqa: ARG001
        return _AsyncEngineShim(engine)

    return patch(
        "src.services.db_introspection.sql_inspector._build_engine", _build
    )


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------


async def test_full_pipeline_inventory_columns_sampling_describing():
    from src.services.db_introspection.schema_doc import SchemaDocument
    from src.services.db_introspection.sql_inspector import study_sql_schema

    engine = _make_sqlite_engine_with_fixtures()
    resolver, create_mock = _stub_resolver()

    with _patch_engine(engine):
        doc = await study_sql_schema(
            connection_string="postgresql+asyncpg://ignored/ignored",
            db_type="postgresql",
            ai_model_resolver=resolver,
        )

    # Strict-Pydantic validation already happened on construction; re-validate
    # the dumped form for belt-and-braces.
    SchemaDocument.model_validate(doc.model_dump(mode="json"))

    # --- INVENTORY -------------------------------------------------------
    table_names = {t.name for t in doc.tables}
    # SQLite reports schema "main" for the default schema.
    assert any(n.endswith("customers") for n in table_names), table_names
    assert any(n.endswith("orders") for n in table_names), table_names
    assert all("sqlite_" not in n for n in table_names)

    by_short = {t.name.split(".")[-1]: t for t in doc.tables}
    customers = by_short["customers"]
    orders = by_short["orders"]

    # --- COLUMNS ---------------------------------------------------------
    cust_cols = {c.name: c for c in customers.columns}
    assert set(cust_cols) == {"id", "full_name", "email", "signup_date"}
    assert cust_cols["id"].type == "int"
    assert cust_cols["full_name"].type == "text"
    assert cust_cols["full_name"].nullable is False
    assert customers.primary_key == ["id"]

    order_cols = {c.name: c for c in orders.columns}
    assert order_cols["amount_cents"].type == "int"
    assert orders.primary_key == ["id"]
    # FK orders.customer_id -> customers.id
    assert orders.relationships, "expected a foreign-key relationship"
    fk = orders.relationships[0]
    assert fk.kind == "foreign_key"
    assert fk.from_columns == ["customer_id"]
    assert fk.to_table.endswith("customers")
    assert fk.to_columns == ["id"]
    # Index on customer_id reflected.
    assert any(ix.columns == ["customer_id"] for ix in orders.indexes)

    # --- SAMPLING --------------------------------------------------------
    email_col = cust_cols["email"]
    assert email_col.is_pii_candidate is True
    assert len(email_col.sample_values) <= 3
    # Every stored email value must be redacted (no '@example.com' verbatim).
    for v in email_col.sample_values:
        assert "@example.com" in v  # domain kept
        assert v.startswith(("a***@", "b***@", "c***@", "d***@"))
    # The note column on orders has a NULL row — sampled values exclude it.
    note_col = {c.name: c for c in orders.columns}["note"]
    assert all(v is not None for v in note_col.sample_values)
    assert len(note_col.sample_values) <= 3

    # --- DESCRIBING ------------------------------------------------------
    # One LLM call per table + one for the summary.
    assert create_mock.await_count == len(doc.tables) + 1
    assert customers.description == "Stores rows for this relation."
    assert "transactional" in customers.tags
    assert doc.summary == "This database tracks customers and their orders."

    # --- assembled document ---------------------------------------------
    assert doc.dialect == "postgresql"
    assert doc.agent_version == "studying-agent@0.3"
    assert len(doc.fingerprint) == 64
    assert doc.study_duration_ms >= 0
    assert doc.vector_index_ref is None
    # No errors → not partial.
    assert doc.partial is False
    assert doc.phase_errors == []
    # Tables are sorted by name.
    assert [t.name for t in doc.tables] == sorted(t.name for t in doc.tables)


async def test_per_table_columns_failure_records_phase_error_and_continues():
    from src.services.db_introspection.sql_inspector import study_sql_schema

    engine = _make_sqlite_engine_with_fixtures()
    resolver, _ = _stub_resolver()

    real_columns = None
    from src.services.db_introspection import sql_inspector as si

    real_columns = si._phase_columns_for_table

    async def _flaky_columns(eng: Any, schema: str, table: str):
        if table == "orders":
            raise RuntimeError("reflection blew up for orders")
        return await real_columns(eng, schema, table)

    with _patch_engine(engine), patch.object(
        si, "_phase_columns_for_table", _flaky_columns
    ):
        doc = await study_sql_schema(
            connection_string="postgresql+asyncpg://ignored/ignored",
            db_type="postgresql",
            ai_model_resolver=resolver,
        )

    assert doc.partial is True
    keys = {e.error_key for e in doc.phase_errors}
    phases = {e.phase for e in doc.phase_errors}
    assert "COLUMNS" in phases
    assert "REFLECT_FAILED" in keys
    # No credentials/PII leaked into the error message.
    for e in doc.phase_errors:
        assert "ignored:ignored" not in e.message
        assert "@example.com" not in e.message
    # The 'orders' table was dropped; 'customers' survived.
    remaining = {t.name.split(".")[-1] for t in doc.tables}
    assert "customers" in remaining
    assert "orders" not in remaining


async def test_per_table_sampling_failure_keeps_columns_and_marks_partial():
    from src.services.db_introspection import sql_inspector as si
    from src.services.db_introspection.sql_inspector import study_sql_schema

    engine = _make_sqlite_engine_with_fixtures()
    resolver, _ = _stub_resolver()

    async def _flaky_sampling(eng: Any, schema: str, table: str, columns: Any, db_type: str):
        raise si.SchemaStudyPhaseError(
            phase="SAMPLING",
            error_key="SAMPLE_DENIED",
            message=f"Not permitted to read {schema}.{table} for sampling.",
        )

    with _patch_engine(engine), patch.object(
        si, "_phase_sampling_for_table", _flaky_sampling
    ):
        doc = await study_sql_schema(
            connection_string="postgresql+asyncpg://ignored/ignored",
            db_type="postgresql",
            ai_model_resolver=resolver,
        )

    assert doc.partial is True
    sampling_errors = [e for e in doc.phase_errors if e.phase == "SAMPLING"]
    assert sampling_errors
    assert sampling_errors[0].error_key == "SAMPLE_DENIED"
    # Columns are still present (sampling failure doesn't drop the table).
    by_short = {t.name.split(".")[-1]: t for t in doc.tables}
    assert by_short["customers"].columns
    # But sample_values are empty since sampling never ran.
    assert all(not c.sample_values for c in by_short["customers"].columns)


async def test_no_resolver_skips_describing_and_marks_partial():
    from src.services.db_introspection.sql_inspector import study_sql_schema

    engine = _make_sqlite_engine_with_fixtures()

    with _patch_engine(engine):
        doc = await study_sql_schema(
            connection_string="postgresql+asyncpg://ignored/ignored",
            db_type="postgresql",
            ai_model_resolver=None,
        )

    assert doc.partial is True
    assert any(e.error_key == "LLM_UNAVAILABLE" for e in doc.phase_errors)
    assert doc.summary == ""
    # Heuristic tags still applied.
    assert all(isinstance(t.tags, list) for t in doc.tables)


async def test_unsupported_dialect_raises_phase_error():
    from src.services.db_introspection import SchemaStudyPhaseError
    from src.services.db_introspection.sql_inspector import study_sql_schema

    with pytest.raises(SchemaStudyPhaseError) as excinfo:
        await study_sql_schema(
            connection_string="mongodb://ignored",
            db_type="mongodb",
            ai_model_resolver=None,
        )
    assert excinfo.value.phase == "INVENTORY"
    assert excinfo.value.error_key == "UNSUPPORTED_DIALECT"


# ---------------------------------------------------------------------------
# Binary/BLOB column handling in SAMPLING
# ---------------------------------------------------------------------------


def _make_sqlite_engine_with_blob_table() -> sa.Engine:
    """In-memory SQLite DB with a BLOB column alongside a TEXT column."""
    engine = create_engine(
        "sqlite://",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    with engine.begin() as conn:
        conn.execute(
            sa.text(
                "CREATE TABLE assets ("
                "  id INTEGER PRIMARY KEY,"
                "  label TEXT NOT NULL,"
                "  payload BLOB"
                ")"
            )
        )
        conn.execute(
            sa.text(
                "INSERT INTO assets (id, label, payload) VALUES "
                "(1, 'logo', X'DEADBEEF'),"
                "(2, 'icon', X'CAFEBABE'),"
                "(3, 'banner', X'0011223344')"
            )
        )
    return engine


async def test_sampling_skips_binary_columns():
    from src.services.db_introspection import sql_inspector as si
    from src.services.db_introspection.sql_inspector import study_sql_schema

    engine = _make_sqlite_engine_with_blob_table()
    resolver, _ = _stub_resolver()

    real_build = si._build_sample_sql
    seen_sql: list[str] = []

    def _spy_build(schema: str, table: str, columns: list[str], db_type: str):
        sql = real_build(schema, table, columns, db_type)
        if sql is not None:
            seen_sql.append(sql)
        return sql

    with _patch_engine(engine), patch.object(si, "_build_sample_sql", _spy_build):
        doc = await study_sql_schema(
            connection_string="postgresql+asyncpg://ignored/ignored",
            db_type="postgresql",
            ai_model_resolver=resolver,
        )

    by_short = {t.name.split(".")[-1]: t for t in doc.tables}
    assets = by_short["assets"]
    cols = {c.name: c for c in assets.columns}
    # The BLOB column is reflected (still in the doc) but never sampled.
    assert cols["payload"].type == "binary"
    assert cols["payload"].sample_values == []
    # The text column *is* sampled.
    assert cols["label"].sample_values
    assert all(v is not None for v in cols["label"].sample_values)
    # The generated SELECT for `assets` must not mention the BLOB column.
    assets_selects = [s for s in seen_sql if "assets" in s]
    assert assets_selects, "expected a sample SELECT for assets"
    for sql in assets_selects:
        assert "payload" not in sql
        assert "label" in sql


# ---------------------------------------------------------------------------
# Error-message sanitisation
# ---------------------------------------------------------------------------


def test_sanitise_strips_dsn_host_dbname_password_fragments():
    from src.services.db_introspection.sql_inspector import _sanitise

    raw = (
        "connection failed: host=db.internal port=5432 dbname=secrets "
        "user=svc password=hunter2 (timeout expired)"
    )
    out = _sanitise(raw)
    assert "db.internal" not in out
    assert "secrets" not in out
    assert "hunter2" not in out
    assert "svc" not in out
    # The structural bits of the message survive.
    assert "connection failed" in out
    assert "timeout expired" in out


def test_sanitise_strips_url_credentials_and_host_port():
    from src.services.db_introspection.sql_inspector import _sanitise

    raw = "could not connect to postgresql+asyncpg://svc:hunter2@db.internal:5432/app"
    out = _sanitise(raw)
    assert "hunter2" not in out
    assert "svc:hunter2" not in out
    assert "db.internal:5432" not in out


# ---------------------------------------------------------------------------
# FX24 — edge-case hardening
#
# Every test below covers a specific "non-happy-path" the admin can throw at
# the studying agent. The cases mirror the audit list in FX24 verbatim.
# ---------------------------------------------------------------------------


def _make_empty_sqlite_engine() -> sa.Engine:
    """An in-memory SQLite DB with no user tables at all."""
    return create_engine(
        "sqlite://",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )


def _make_zero_row_sqlite_engine() -> sa.Engine:
    """A table that exists but holds no rows — sampling yields nothing."""
    engine = create_engine(
        "sqlite://",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    with engine.begin() as conn:
        conn.execute(
            sa.text(
                "CREATE TABLE empty_things ("
                "  id INTEGER PRIMARY KEY,"
                "  label TEXT NOT NULL"
                ")"
            )
        )
    return engine


async def test_empty_database_lands_ready_with_zero_tables():
    """EC1 — an empty source must land READY (not INVENTORY_FAILED).

    Previously the inspector raised ``NO_TABLES`` as a fatal phase error,
    which left the source stuck in ``INVENTORY_FAILED`` even though
    nothing was wrong — there were just no tables yet. After FX24 the
    inspector returns a valid SchemaDocument with ``tables=[]`` so the
    admin viewer can render the empty-DB hint.
    """
    from src.services.db_introspection.sql_inspector import study_sql_schema

    engine = _make_empty_sqlite_engine()

    with _patch_engine(engine):
        doc = await study_sql_schema(
            connection_string="postgresql+asyncpg://ignored/ignored",
            db_type="postgresql",
            ai_model_resolver=None,
        )

    assert doc.tables == []
    assert doc.summary == ""
    assert doc.partial_coverage is False
    assert doc.skipped_tables == []
    assert doc.truncated_at is None
    # No tables ⇒ no LLM was ever needed, so don't claim descriptions
    # are unavailable (the doc has nothing to describe).
    assert doc.llm_descriptions_available is True
    # The DESCRIBING phase produced no signal-of-no-resolver error because
    # the loop never iterated over any tables.
    assert all(e.error_key != "LLM_UNAVAILABLE" for e in doc.phase_errors)
    # Fingerprint is computed even for an empty doc.
    assert len(doc.fingerprint) == 64


async def test_empty_tables_skip_llm_for_no_signal_tables():
    """EC2 — a table with zero rows must not be fed to the LLM.

    The studying agent samples ``LIMIT 3`` and gets no rows back; the
    sample_values stay ``[]`` and the row-count estimate is 0. Calling the
    LLM with "describe what this empty table likely stores" is an
    invitation to hallucinate, so the inspector now skips the LLM call
    and records a ``NO_SIGNAL`` phase error.
    """
    from src.services.db_introspection.sql_inspector import study_sql_schema

    engine = _make_zero_row_sqlite_engine()
    resolver, create_mock = _stub_resolver()

    with _patch_engine(engine):
        doc = await study_sql_schema(
            connection_string="postgresql+asyncpg://ignored/ignored",
            db_type="postgresql",
            ai_model_resolver=resolver,
        )

    # The table is in the doc; only the LLM call was skipped.
    by_short = {t.name.split(".")[-1]: t for t in doc.tables}
    assert "empty_things" in by_short
    table = by_short["empty_things"]
    assert all(not c.sample_values for c in table.columns)
    # No description was attempted — the LLM mock must NOT have been
    # called for this table. The summary call may still fire (1 total).
    assert create_mock.await_count <= 1
    assert table.description == ""
    # The NO_SIGNAL phase error is recorded so the admin knows why.
    no_signal = [e for e in doc.phase_errors if e.error_key == "NO_SIGNAL"]
    assert no_signal


async def test_permission_denied_sampling_flags_partial_coverage_and_skipped_tables():
    """EC3 — a permission-denied table lands a partial-coverage signal.

    SAMPLE_DENIED (admin can list metadata but lacks SELECT on rows) is
    surfaced both via a phase_error AND via the explicit ``skipped_tables``
    list + ``partial_coverage=True`` so the admin UI can render a named
    list without parsing error messages.
    """
    from src.services.db_introspection import sql_inspector as si
    from src.services.db_introspection.sql_inspector import study_sql_schema

    engine = _make_sqlite_engine_with_fixtures()
    resolver, _ = _stub_resolver()

    async def _flaky_sampling(eng, schema, table, columns, db_type):  # noqa: ANN001
        if table == "orders":
            raise si.SchemaStudyPhaseError(
                phase="SAMPLING",
                error_key="SAMPLE_DENIED",
                message=f"Not permitted to read {schema}.{table} for sampling.",
            )
        # customers samples normally
        return None

    with _patch_engine(engine), patch.object(
        si, "_phase_sampling_for_table", _flaky_sampling
    ):
        doc = await study_sql_schema(
            connection_string="postgresql+asyncpg://ignored/ignored",
            db_type="postgresql",
            ai_model_resolver=resolver,
        )

    assert doc.partial_coverage is True
    assert any(name.endswith("orders") for name in doc.skipped_tables)
    # The orders table is still in the doc (we got its columns) — just
    # without sample values.
    by_short = {t.name.split(".")[-1]: t for t in doc.tables}
    assert "orders" in by_short
    # The phase-error message must not leak credentials.
    for e in doc.phase_errors:
        assert "ignored:ignored" not in e.message


async def test_permission_denied_columns_phase_marks_table_skipped():
    """EC3 — a COLUMNS-phase permission denial enrolls the table in skipped_tables."""
    from src.services.db_introspection import sql_inspector as si
    from src.services.db_introspection.sql_inspector import study_sql_schema

    engine = _make_sqlite_engine_with_fixtures()
    resolver, _ = _stub_resolver()

    real_columns = si._phase_columns_for_table

    async def _flaky_columns(eng, schema, table):  # noqa: ANN001
        if table == "orders":
            raise PermissionError("permission denied for table orders")
        return await real_columns(eng, schema, table)

    with _patch_engine(engine), patch.object(
        si, "_phase_columns_for_table", _flaky_columns
    ):
        doc = await study_sql_schema(
            connection_string="postgresql+asyncpg://ignored/ignored",
            db_type="postgresql",
            ai_model_resolver=resolver,
        )

    assert doc.partial_coverage is True
    assert any(name.endswith("orders") for name in doc.skipped_tables)
    # The orders table itself was dropped from the doc (no columns
    # available); customers remains.
    remaining = {t.name.split(".")[-1] for t in doc.tables}
    assert "customers" in remaining
    assert "orders" not in remaining


async def test_truncated_at_set_when_inventory_exceeds_max_tables():
    """EC4 — a huge schema records ``truncated_at`` + ``partial_coverage``.

    Drops the per-source cap to a small number so the existing fixture
    (two tables) trips the truncation path.
    """
    from src.services.db_introspection import sql_inspector as si
    from src.services.db_introspection.sql_inspector import study_sql_schema

    engine = _make_sqlite_engine_with_fixtures()
    resolver, _ = _stub_resolver()

    # Cap = 1: keep one of the two tables; surface the truncation signal.
    with _patch_engine(engine), patch.object(si, "_MAX_TABLES", 1):
        doc = await study_sql_schema(
            connection_string="postgresql+asyncpg://ignored/ignored",
            db_type="postgresql",
            ai_model_resolver=resolver,
        )

    assert doc.truncated_at == 2  # 2 user tables in the fixture
    assert len(doc.tables) == 1
    assert doc.partial_coverage is True


async def test_llm_total_failure_flags_descriptions_unavailable():
    """EC8 — when every per-table LLM call fails, flag descriptions unavailable.

    The schema metadata is the load-bearing part; descriptions are gravy.
    The study should land READY_PARTIAL (the orchestrator) with
    ``llm_descriptions_available=False`` so the admin sees a banner
    explaining the absence of blurbs rather than thinking the agent
    forgot.
    """
    from src.services.db_introspection.sql_inspector import study_sql_schema

    engine = _make_sqlite_engine_with_fixtures()
    resolver, create_mock = _stub_resolver()

    async def _always_fail(**_kwargs):  # noqa: ANN003
        raise RuntimeError("upstream 503 from LLM provider")

    create_mock.side_effect = _always_fail

    with _patch_engine(engine):
        doc = await study_sql_schema(
            connection_string="postgresql+asyncpg://ignored/ignored",
            db_type="postgresql",
            ai_model_resolver=resolver,
        )

    assert doc.llm_descriptions_available is False
    assert doc.partial is True  # phase errors recorded
    # Every table has no description but still has heuristic tags.
    for t in doc.tables:
        assert t.description == ""
        assert isinstance(t.tags, list)
    # The sanitised LLM error must not leak the model's exception type.
    llm_errors = [e for e in doc.phase_errors if e.error_key == "LLM_ERROR"]
    assert llm_errors


async def test_no_resolver_keeps_doc_loadable_and_flags_descriptions_unavailable():
    """EC8 — a missing resolver also flags ``llm_descriptions_available=False``."""
    from src.services.db_introspection.sql_inspector import study_sql_schema

    engine = _make_sqlite_engine_with_fixtures()
    with _patch_engine(engine):
        doc = await study_sql_schema(
            connection_string="postgresql+asyncpg://ignored/ignored",
            db_type="postgresql",
            ai_model_resolver=None,
        )
    assert doc.llm_descriptions_available is False
    assert any(e.error_key == "LLM_UNAVAILABLE" for e in doc.phase_errors)


async def test_signal_free_helper_skips_zero_row_zero_sample_tables():
    """Helper unit test — ``_is_signal_free_for_llm`` answers the right question."""
    from src.services.db_introspection.schema_doc import ColumnDoc, TableDoc
    from src.services.db_introspection.sql_inspector import _is_signal_free_for_llm

    def _col(name: str, samples: list[str]) -> ColumnDoc:
        return ColumnDoc(
            name=name,
            type="text",
            native_type="TEXT",
            nullable=True,
            default=None,
            sample_values=samples,
            is_pii_candidate=False,
            inferred=False,
        )

    empty = TableDoc(
        name="s.t",
        kind="table",
        row_count_estimate=0,
        primary_key=[],
        indexes=[],
        columns=[_col("id", []), _col("label", [])],
        relationships=[],
        description="",
        tags=[],
    )
    # Empty table, zero rows, zero samples ⇒ no signal for the LLM.
    assert _is_signal_free_for_llm(empty) is True

    # row_count_estimate=None: SAMPLING got nothing back from `LIMIT 3`,
    # which is itself strong evidence of "no rows", so also no-signal.
    unknown = empty.model_copy(update={"row_count_estimate": None})
    assert _is_signal_free_for_llm(unknown) is True

    # Any column with a sample value ⇒ we have signal; call the LLM.
    with_samples = empty.model_copy(
        update={"columns": [_col("id", []), _col("label", ["foo"])]}
    )
    assert _is_signal_free_for_llm(with_samples) is False

    # Positive row count but all columns happen to have empty samples
    # (e.g. all binary, all NULL) — we still have *some* signal (the
    # table is populated), so call the LLM.
    populated_but_no_samples = empty.model_copy(
        update={"row_count_estimate": 5}
    )
    assert _is_signal_free_for_llm(populated_but_no_samples) is False


# ---------------------------------------------------------------------------
# _build_engine — postgres hardening wiring (atomic url + connect_args pairing)
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_build_engine_asyncpg_passes_server_settings_connect_args():
    from src.services.db_introspection.sql_inspector import (
        _STATEMENT_TIMEOUT_MS,
        _build_engine,
    )

    captured: dict[str, Any] = {}

    def _fake_create(*args: Any, **kwargs: Any) -> MagicMock:
        captured["url"] = kwargs.get("url", args[0] if args else None)
        captured["connect_args"] = kwargs.get("connect_args", {})
        return MagicMock()

    with patch(
        "src.services.db_introspection.sql_inspector.create_async_engine",
        side_effect=_fake_create,
    ):
        await _build_engine(
            "postgresql+asyncpg://user:pw@host/db", "postgresql"
        )

    ss = captured["connect_args"]["server_settings"]
    assert ss["default_transaction_read_only"] == "on"
    # The 15_000 ms inspector constant threads through to connect_args.
    assert ss["statement_timeout"] == str(_STATEMENT_TIMEOUT_MS)
    # asyncpg URL unchanged.
    assert captured["url"] == "postgresql+asyncpg://user:pw@host/db"


@pytest.mark.asyncio
async def test_build_engine_libpq_passes_empty_connect_args():
    from src.services.db_introspection.sql_inspector import (
        _STATEMENT_TIMEOUT_MS,
        _build_engine,
    )

    captured: dict[str, Any] = {}

    def _fake_create(*args: Any, **kwargs: Any) -> MagicMock:
        captured["url"] = kwargs.get("url", args[0] if args else None)
        captured["connect_args"] = kwargs.get("connect_args", {})
        return MagicMock()

    with patch(
        "src.services.db_introspection.sql_inspector.create_async_engine",
        side_effect=_fake_create,
    ):
        await _build_engine("postgresql://user:pw@host/db", "postgresql")

    assert captured["connect_args"] == {}
    # libpq hardening rides in the URL options=, with the inspector timeout.
    # The options= value is URL-encoded (%3D for =), so decode first.
    from urllib.parse import unquote

    decoded_url = unquote(captured["url"])
    assert "default_transaction_read_only=on" in decoded_url
    assert f"statement_timeout={_STATEMENT_TIMEOUT_MS}" in decoded_url
