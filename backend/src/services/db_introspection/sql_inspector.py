"""SQL-dialect schema inspector for the studying-agent (Phase 2 — real impl).

Drives the six-phase studying-agent pipeline against a PostgreSQL / MySQL /
SQL Server source and returns a strict :class:`SchemaDocument`:

1. **CONNECTING** — open a fresh read-only-hardened async engine, ``SELECT 1``.
2. **INVENTORY** — reflect schemas + tables + views (skip system schemas,
   cap at :data:`_MAX_TABLES`), cheap row-count estimates.
3. **COLUMNS** — per table: columns / PK / indexes / FKs, normalised types.
4. **SAMPLING** — per table: ``SELECT <cols> ... LIMIT 3`` (validated by
   :func:`db_safety.validate_sql`), up to 3 distinct PII-redacted values
   per column, under a wall-clock budget.
5. **DESCRIBING** — per table: one LLM call (resolver slot ``schema_inspector``)
   → 2-3 sentence description + ≤3 tags; then one call for the corpus summary.
6. **INDEXING** — Phase 2 vector index. Not done this slice → ``vector_index_ref=None``.

Per-table failures in COLUMNS / SAMPLING / DESCRIBING are recorded as
:class:`PhaseError` rows, flip ``partial=True``, and do **not** abort the
study. Fatal failures (can't connect, can't reflect anything) raise
:class:`SchemaStudyPhaseError` so the orchestrator can stamp the right
``<phase>_FAILED`` state.

Read-only everywhere: no DDL/DML ever touches the source. Sampling is
``SELECT ... LIMIT 3`` only, AST-validated.
"""

from __future__ import annotations

import json
import logging
import re
import time
from datetime import datetime, timezone
from typing import TYPE_CHECKING, Any, Final

import sqlalchemy as sa
from sqlalchemy.engine import Inspector
from sqlalchemy.ext.asyncio import AsyncEngine, create_async_engine
from sqlalchemy.types import (
    Boolean,
    Date,
    DateTime,
    Enum as SAEnum,
    Integer,
    LargeBinary,
    Numeric,
    SmallInteger,
    String,
    Time,
)

from src.services.db_introspection._errors import SchemaStudyPhaseError
from src.services.db_introspection.fingerprint import compute_fingerprint
from src.services.db_introspection.pii_redaction import (
    column_name_looks_pii,
    looks_pii,
    redact_value,
)
from src.services.db_introspection.schema_doc import (
    ColumnDoc,
    DialectLiteral,
    IndexDoc,
    PhaseError,
    Relationship,
    SchemaDocument,
    TableDoc,
)
from src.services.db_safety import harden_postgres_connection, validate_sql

if TYPE_CHECKING:  # pragma: no cover - typing only
    from src.services.ai_model_resolver import AIModelResolver

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Constants / caps
# ---------------------------------------------------------------------------

#: The studying-agent version this inspector emits. Bumped from @0.1 (the
#: Phase-1 contract-only release) now that the real pipeline ships.
AGENT_VERSION = "studying-agent@0.2"

#: Hard cap on tables reflected per source. Beyond this we log + truncate.
_MAX_TABLES = 200

#: Max distinct sample values stored per column (contract also caps at 3).
_MAX_SAMPLES_PER_COLUMN = 3

#: Hard cap on how many columns of a single table the SAMPLING phase pulls.
#: The COLUMNS phase already captured every column in the document; this only
#: bounds the generated ``SELECT`` so a 10k-column table can't produce a
#: 10k-column query. Columns past the cap get ``sample_values=[]``.
_MAX_SAMPLE_COLUMNS_PER_TABLE = 60

#: Wall-clock budget for the SAMPLING phase across the whole source (seconds).
_SAMPLING_BUDGET_SECONDS = 60.0

#: Wall-clock budget for the DESCRIBING phase across the whole source (seconds).
_DESCRIBING_BUDGET_SECONDS = 120.0

#: Per-statement timeout applied to the introspection / sampling engine (ms).
_STATEMENT_TIMEOUT_MS = 15_000

#: Resolver stage slot for the table/summary LLM calls.
_LLM_STAGE = "schema_inspector"

#: System schemas we never reflect.
_SYSTEM_SCHEMAS = frozenset(
    {
        "pg_catalog",
        "information_schema",
        "sys",
        "mysql",
        "performance_schema",
        "pg_toast",
        "pg_temp_1",
        "pg_toast_temp_1",
    }
)

#: Map ``config["db_type"]`` → contract dialect literal.
_DIALECT_BY_DB_TYPE: dict[str, DialectLiteral] = {
    "postgresql": "postgresql",
    "mysql": "mysql",
    "mssql": "mssql",
}

#: Map ``config["db_type"]`` → sqlglot dialect (for the SAMPLING SQL gate).
_SQLGLOT_DIALECT_BY_DB_TYPE: dict[str, str] = {
    "postgresql": "postgres",
    "mysql": "mysql",
    "mssql": "tsql",
}


# --- Error-message sanitisation -------------------------------------------
#
# Anything headed for a persisted PhaseError (and thus the audit log / admin
# UI) must not leak DB topology or credentials. Driver exceptions are noisy:
# asyncpg / psycopg embed ``host=...`` / ``dbname=...`` / ``password=...``
# DSN fragments, SQLAlchemy embeds ``scheme://user:pass@host`` URLs, and a
# bare ``host:port`` can show up anywhere. We over-redact on purpose — a
# scrubbed error message is fine; a leaked one is not.

#: ``scheme://user:pass@host`` → ``scheme://***@host``
_CRED_URL_RE: Final[re.Pattern[str]] = re.compile(r"://[^@\s/]+@")

#: DSN-style ``key=value`` fragments that name the host/db/user/credentials.
_DSN_KV_RE: Final[re.Pattern[str]] = re.compile(
    r"\b(host|hostaddr|port|dbname|database|user|username|password|passwd)\s*=\s*"
    r"('[^']*'|\"[^\"]*\"|\S+)",
    re.IGNORECASE,
)

#: A bare ``hostname:port`` (2-5 digit port). Conservative — only fires when a
#: colon-separated port is present, so we don't eat ``"line 12:34"``.
_HOST_PORT_RE: Final[re.Pattern[str]] = re.compile(r"\b[\w.-]+:\d{2,5}\b")


def _sanitise(message: str) -> str:
    """Redact credentials / host / db-name fragments from an error message.

    Mirrors (and tightens) ``study_source._sanitise``. Order matters: strip
    DSN ``key=value`` fragments first (they may contain a ``host:port``),
    then collapse any remaining bare ``host:port``, then the URL form.
    """
    text = str(message)
    text = _DSN_KV_RE.sub(lambda m: f"{m.group(1).lower()}=<redacted>", text)
    text = _HOST_PORT_RE.sub("<host>:<port>", text)
    text = _CRED_URL_RE.sub("://***@", text)
    return text


# ---------------------------------------------------------------------------
# Type normalisation
# ---------------------------------------------------------------------------


def _normalise_column_type(sa_type: Any) -> str:
    """Map a SQLAlchemy reflected type to a contract :data:`ColumnTypeLiteral`.

    Arrays are returned as ``array<T>`` where ``T`` is the recursively
    normalised element type. Anything we can't classify → ``unknown``.
    """
    # ARRAY — SQLAlchemy exposes ``item_type``. We avoid importing the
    # dialect-specific ARRAY classes directly so reflection of any backend's
    # array works; ``getattr`` is enough.
    item_type = getattr(sa_type, "item_type", None)
    if item_type is not None and type(sa_type).__name__.upper().startswith("ARRAY"):
        return f"array<{_normalise_column_type(item_type)}>"

    if isinstance(sa_type, Boolean):
        return "bool"
    if isinstance(sa_type, (SmallInteger, Integer)):
        return "int"
    if isinstance(sa_type, Numeric):
        # Numeric with scale==0 is integer-ish; otherwise float.
        scale = getattr(sa_type, "scale", None)
        return "int" if scale == 0 else "float"
    if isinstance(sa_type, DateTime):
        return "datetime"
    if isinstance(sa_type, Date):
        return "date"
    if isinstance(sa_type, Time):
        return "datetime"
    if isinstance(sa_type, LargeBinary):
        return "binary"
    if isinstance(sa_type, SAEnum):
        return "enum"

    type_name = type(sa_type).__name__.upper()
    if "UUID" in type_name or "GUID" in type_name:
        return "uuid"
    if "JSON" in type_name or "JSONB" in type_name:
        return "json"
    if "BINARY" in type_name or "BLOB" in type_name or "BYTEA" in type_name:
        return "binary"
    if "ENUM" in type_name:
        return "enum"
    if isinstance(sa_type, String) or "TEXT" in type_name or "CHAR" in type_name:
        return "text"
    if "FLOAT" in type_name or "DOUBLE" in type_name or "REAL" in type_name or "DECIMAL" in type_name:
        return "float"
    if "INT" in type_name:
        return "int"
    if "DATE" in type_name:
        return "date"
    if "TIME" in type_name:
        return "datetime"
    return "unknown"


def _render_default(default: Any) -> str | None:
    """Stringify a reflected column server-default; ``None`` stays ``None``."""
    if default is None:
        return None
    text = str(default).strip()
    return text or None


# ---------------------------------------------------------------------------
# Engine helpers
# ---------------------------------------------------------------------------


async def _build_engine(connection_string: str, db_type: str) -> AsyncEngine:
    """Create a fresh async engine with read-only hardening applied."""
    conn_str = connection_string
    if db_type == "postgresql" or conn_str.startswith(("postgresql", "postgres")):
        try:
            conn_str = await harden_postgres_connection(
                conn_str, statement_timeout_ms=_STATEMENT_TIMEOUT_MS
            )
        except ValueError:
            # Fall back to the raw URL — the connect probe below still
            # protects us, and we don't widen the blast radius.
            logger.warning(
                "sql_inspector: postgres hardening rejected the URL — "
                "falling back to raw connection string"
            )
    return create_async_engine(conn_str, pool_pre_ping=True, pool_size=2, max_overflow=0)


async def _reflect(engine: AsyncEngine, fn: Any) -> Any:
    """Run a sync reflection callable against an :class:`Inspector`.

    ``fn`` receives a :class:`sqlalchemy.engine.Inspector` and returns
    whatever it likes; we marshal it back through ``run_sync``.
    """
    async with engine.connect() as conn:
        return await conn.run_sync(lambda sync_conn: fn(sa.inspect(sync_conn)))


# ---------------------------------------------------------------------------
# Phase 1 — CONNECTING
# ---------------------------------------------------------------------------


async def _phase_connecting(engine: AsyncEngine) -> None:
    try:
        async with engine.connect() as conn:
            await conn.execute(sa.text("SELECT 1"))
    except Exception as exc:  # noqa: BLE001 - classify + re-raise sanitised
        message = _sanitise(str(exc)).lower()
        if "timeout" in message or "timed out" in message:
            error_key = "CONNECT_TIMEOUT"
        elif (
            "password" in message
            or "authentication" in message
            or "auth failed" in message
            or "role" in message
        ):
            error_key = "AUTH_FAILED"
        else:
            error_key = "CONNECT_REFUSED"
        raise SchemaStudyPhaseError(
            phase="CONNECTING",
            error_key=error_key,
            message="Could not connect to the source database (see server logs).",
        ) from None


# ---------------------------------------------------------------------------
# Phase 2 — INVENTORY
# ---------------------------------------------------------------------------


async def _phase_inventory(engine: AsyncEngine) -> list[tuple[str, str, str]]:
    """Return ``[(schema, table_name, kind)]`` for all non-system relations.

    Raises :class:`SchemaStudyPhaseError` if reflection of the schema list
    itself fails (a fatal INVENTORY error).
    """

    def _collect(inspector: Inspector) -> list[tuple[str, str, str]]:
        out: list[tuple[str, str, str]] = []
        try:
            schemas = inspector.get_schema_names()
        except Exception:  # noqa: BLE001 - some dialects need a default schema
            schemas = [inspector.default_schema_name or ""]
        for schema in schemas:
            if (schema or "").lower() in _SYSTEM_SCHEMAS:
                continue
            schema_arg = schema or None
            try:
                tables = inspector.get_table_names(schema=schema_arg)
            except Exception:  # noqa: BLE001 - skip un-reflectable schemas
                tables = []
            try:
                views = inspector.get_view_names(schema=schema_arg)
            except Exception:  # noqa: BLE001
                views = []
            try:
                mat_views = inspector.get_materialized_view_names(schema=schema_arg)
            except Exception:  # noqa: BLE001 - older SA / unsupported dialect
                mat_views = []
            mat_set = set(mat_views)
            for name in tables:
                out.append((schema or "", name, "table"))
            for name in views:
                # Some dialects list materialized views under get_view_names
                # too — defer to the explicit materialized-view list.
                if name in mat_set:
                    continue
                out.append((schema or "", name, "view"))
            for name in mat_views:
                out.append((schema or "", name, "materialized_view"))
        return out

    try:
        relations: list[tuple[str, str, str]] = await _reflect(engine, _collect)
    except SchemaStudyPhaseError:
        raise
    except Exception as exc:  # noqa: BLE001
        raise SchemaStudyPhaseError(
            phase="INVENTORY",
            error_key="REFLECT_FAILED",
            message=f"Could not reflect the source schema: {_sanitise(str(exc))}",
        ) from None

    if not relations:
        raise SchemaStudyPhaseError(
            phase="INVENTORY",
            error_key="NO_TABLES",
            message="The source database exposes no tables or views to study.",
        )

    if len(relations) > _MAX_TABLES:
        logger.warning(
            "sql_inspector: source has %d relations; truncating to %d",
            len(relations),
            _MAX_TABLES,
        )
        relations = relations[:_MAX_TABLES]
    return relations


async def _row_count_estimate(
    engine: AsyncEngine, schema: str, table: str, db_type: str
) -> int | None:
    """Cheap row-count estimate per dialect — never runs ``COUNT(*)``."""
    try:
        if db_type == "postgresql":
            sql = sa.text(
                "SELECT reltuples::bigint FROM pg_class c "
                "JOIN pg_namespace n ON n.oid = c.relnamespace "
                "WHERE c.relname = :t AND n.nspname = :s"
            )
            params = {"t": table, "s": schema or "public"}
        elif db_type == "mysql":
            sql = sa.text(
                "SELECT table_rows FROM information_schema.tables "
                "WHERE table_name = :t AND table_schema = :s"
            )
            params = {"t": table, "s": schema}
        elif db_type == "mssql":
            sql = sa.text(
                "SELECT SUM(p.rows) FROM sys.partitions p "
                "JOIN sys.tables t ON p.object_id = t.object_id "
                "JOIN sys.schemas s ON t.schema_id = s.schema_id "
                "WHERE t.name = :t AND s.name = :s AND p.index_id IN (0, 1)"
            )
            params = {"t": table, "s": schema or "dbo"}
        else:  # pragma: no cover - guarded by caller
            return None
        async with engine.connect() as conn:
            result = await conn.execute(sql, params)
            value = result.scalar()
        if value is None:
            return None
        ivalue = int(value)
        return ivalue if ivalue >= 0 else None
    except Exception:  # noqa: BLE001 - row-count is best-effort, never fatal
        return None


# ---------------------------------------------------------------------------
# Phase 3 — COLUMNS
# ---------------------------------------------------------------------------


def _qualified_name(schema: str, table: str) -> str:
    return f"{schema}.{table}" if schema else table


async def _phase_columns_for_table(
    engine: AsyncEngine,
    schema: str,
    table: str,
) -> tuple[list[ColumnDoc], list[str], list[IndexDoc], list[Relationship]]:
    """Reflect one table's columns / PK / indexes / FKs. Raises on failure."""
    schema_arg = schema or None

    def _collect(inspector: Inspector) -> dict[str, Any]:
        return {
            "columns": inspector.get_columns(table, schema=schema_arg),
            "pk": inspector.get_pk_constraint(table, schema=schema_arg),
            "indexes": inspector.get_indexes(table, schema=schema_arg),
            "fks": inspector.get_foreign_keys(table, schema=schema_arg),
        }

    reflected: dict[str, Any] = await _reflect(engine, _collect)

    columns: list[ColumnDoc] = []
    for col in reflected["columns"]:
        sa_type = col.get("type")
        native_type = ""
        try:
            native_type = str(sa_type)
        except Exception:  # noqa: BLE001 - some custom types blow up on str()
            native_type = type(sa_type).__name__ if sa_type is not None else "unknown"
        name = str(col["name"])
        columns.append(
            ColumnDoc(
                name=name,
                type=_normalise_column_type(sa_type),
                native_type=native_type or "unknown",
                nullable=bool(col.get("nullable", True)),
                default=_render_default(col.get("default")),
                sample_values=[],
                is_pii_candidate=column_name_looks_pii(name),
                inferred=False,
            )
        )

    pk_cols: list[str] = [str(c) for c in (reflected["pk"].get("constrained_columns") or [])]

    indexes: list[IndexDoc] = []
    for idx in reflected["indexes"]:
        idx_name = idx.get("name")
        if not idx_name:
            continue
        indexes.append(
            IndexDoc(
                name=str(idx_name),
                columns=[str(c) for c in (idx.get("column_names") or []) if c is not None],
                unique=bool(idx.get("unique", False)),
            )
        )

    relationships: list[Relationship] = []
    for fk in reflected["fks"]:
        referred_table = fk.get("referred_table")
        if not referred_table:
            continue
        referred_schema = fk.get("referred_schema") or schema
        relationships.append(
            Relationship(
                from_columns=[str(c) for c in (fk.get("constrained_columns") or [])],
                to_table=_qualified_name(referred_schema or "", str(referred_table)),
                to_columns=[str(c) for c in (fk.get("referred_columns") or [])],
                kind="foreign_key",
            )
        )

    return columns, pk_cols, indexes, relationships


# ---------------------------------------------------------------------------
# Phase 4 — SAMPLING
# ---------------------------------------------------------------------------


def _quote_ident(name: str, db_type: str) -> str:
    """Minimal identifier quoting for a generated SELECT.

    sqlglot validates the result anyway; this just produces a parseable
    identifier for ordinary names. Names containing the quote char are
    rejected upstream (we skip sampling for them).
    """
    if db_type == "mysql":
        return f"`{name}`"
    if db_type == "mssql":
        return f"[{name}]"
    return f'"{name}"'


#: How many rows the SAMPLING SELECT pulls. The studying-agent spec pins
#: this at 3 (a tiny, cheap peek — ``LIMIT 3``); ``_MAX_SAMPLES_PER_COLUMN``
#: then bounds how many of those land in the document.
_SAMPLE_FETCH_ROWS = 3


def _build_sample_sql(
    schema: str, table: str, columns: list[str], db_type: str
) -> str | None:
    """Build a ``SELECT <cols> FROM <schema.table> LIMIT N`` string.

    Returns ``None`` if any identifier looks unsafe to interpolate (e.g.
    contains a quote character) — caller then skips sampling for the table.
    """
    bad = {'"', "`", "[", "]", ";", "\n", "\r"}
    idents = [schema, table, *columns]
    if any(any(ch in ident for ch in bad) for ident in idents if ident):
        return None
    col_list = ", ".join(_quote_ident(c, db_type) for c in columns)
    table_ref = (
        f"{_quote_ident(schema, db_type)}.{_quote_ident(table, db_type)}"
        if schema
        else _quote_ident(table, db_type)
    )
    if db_type == "mssql":
        return f"SELECT TOP {_SAMPLE_FETCH_ROWS} {col_list} FROM {table_ref}"
    return f"SELECT {col_list} FROM {table_ref} LIMIT {_SAMPLE_FETCH_ROWS}"


async def _phase_sampling_for_table(
    engine: AsyncEngine,
    schema: str,
    table: str,
    columns: list[ColumnDoc],
    db_type: str,
) -> None:
    """Sample up to 3 distinct, PII-redacted values per column, in place.

    Binary/BLOB columns (normalised type ``"binary"``) are skipped — a
    ``BYTEA`` holding a 50 MB image must never be fetched + stringified +
    stored — and the per-table column count is capped at
    :data:`_MAX_SAMPLE_COLUMNS_PER_TABLE`. Skipped/capped columns keep
    ``sample_values=[]`` (the COLUMNS phase already recorded them). If nothing
    is left to sample (an all-binary table), no ``SELECT`` is run.

    Raises an exception (caught by the caller as a per-table PhaseError) on
    timeout / permission errors.
    """
    if not columns:
        return
    non_binary = [c for c in columns if c.type != "binary"]
    sample_cols = (
        non_binary[:_MAX_SAMPLE_COLUMNS_PER_TABLE]
        if len(non_binary) > _MAX_SAMPLE_COLUMNS_PER_TABLE
        else non_binary
    )
    if not sample_cols:
        # Nothing safe/worth sampling (e.g. an all-binary table) — don't emit
        # a "SELECT FROM" with zero columns.
        return
    if len(sample_cols) < len(non_binary):
        logger.info(
            "sql_inspector: %s has %d sampleable columns — capping at %d",
            _qualified_name(schema, table),
            len(non_binary),
            _MAX_SAMPLE_COLUMNS_PER_TABLE,
        )
    col_names = [c.name for c in sample_cols]
    sql_text = _build_sample_sql(schema, table, col_names, db_type)
    if sql_text is None:
        logger.info(
            "sql_inspector: skipping sampling for %s — unsafe identifier",
            _qualified_name(schema, table),
        )
        return

    # Defense-in-depth: the generated SELECT must pass the shared SQL gate.
    sqlglot_dialect = _SQLGLOT_DIALECT_BY_DB_TYPE.get(db_type, "postgres")
    verdict = validate_sql(sql_text, dialect=sqlglot_dialect)
    if not verdict.is_safe:
        logger.warning(
            "sql_inspector: generated sample SQL failed validation "
            "(%s) — skipping sampling for %s",
            verdict.error_key,
            _qualified_name(schema, table),
        )
        return

    try:
        async with engine.connect() as conn:
            result = await conn.execute(sa.text(sql_text))
            rows = result.mappings().all()
    except Exception as exc:  # noqa: BLE001 - classify for the PhaseError
        message = _sanitise(str(exc)).lower()
        if "timeout" in message or "timed out" in message or "cancel" in message:
            raise SchemaStudyPhaseError(
                phase="SAMPLING",
                error_key="SAMPLE_TIMEOUT",
                message=(
                    f"Sampling {_qualified_name(schema, table)} timed out."
                ),
            ) from None
        if "permission" in message or "denied" in message or "privilege" in message:
            raise SchemaStudyPhaseError(
                phase="SAMPLING",
                error_key="SAMPLE_DENIED",
                message=(
                    f"Not permitted to read {_qualified_name(schema, table)} "
                    "for sampling."
                ),
            ) from None
        raise SchemaStudyPhaseError(
            phase="SAMPLING",
            error_key="SAMPLE_FAILED",
            message=(
                f"Could not sample {_qualified_name(schema, table)}: "
                f"{_sanitise(str(exc))}"
            ),
        ) from None

    # Collect up to N distinct non-null values per column (insertion order).
    per_column: dict[str, list[str]] = {name: [] for name in col_names}
    for row in rows:
        for name in col_names:
            if len(per_column[name]) >= _MAX_SAMPLES_PER_COLUMN:
                continue
            value = row.get(name)
            if value is None:
                continue
            redacted = redact_value(value)
            if redacted in per_column[name]:
                continue
            per_column[name].append(redacted)

    for col in columns:
        samples = per_column.get(col.name, [])[: _MAX_SAMPLES_PER_COLUMN]
        col.sample_values = samples
        if not col.is_pii_candidate and looks_pii(col.name, samples):
            col.is_pii_candidate = True


# ---------------------------------------------------------------------------
# Heuristic tags
# ---------------------------------------------------------------------------

_AUDIT_NAME_RE = re.compile(r"(_log|_logs|_audit|_history|_events?)$|^audit_|^event_log")
_LOOKUP_COLUMN_SETS: tuple[frozenset[str], ...] = (
    frozenset({"id", "name"}),
    frozenset({"id", "code"}),
    frozenset({"id", "label"}),
    frozenset({"code", "name"}),
)


def _heuristic_tags(table: TableDoc) -> list[str]:
    """Derive a few structural tags from a table's shape."""
    tags: list[str] = []
    bare_name = table.name.split(".")[-1].lower()
    col_names = {c.name.lower() for c in table.columns}
    n_cols = len(table.columns)
    fk_from_cols = {c.lower() for r in table.relationships for c in r.from_columns}

    if table.kind in ("view", "materialized_view"):
        tags.append("view")
    if _AUDIT_NAME_RE.search(bare_name):
        tags.append("audit_log")
    # Junction: ~2 columns, both FKs (ignoring an optional surrogate id / ts).
    non_meta = {c for c in col_names if c not in {"id", "created_at", "updated_at"}}
    if 2 <= n_cols <= 4 and non_meta and non_meta.issubset(fk_from_cols) and len(non_meta) == 2:
        tags.append("junction")
    # Lookup: small-ish table whose columns are basically id+name/code.
    estimate = table.row_count_estimate
    small = estimate is None or estimate <= 5_000
    if small and n_cols <= 4:
        for candidate in _LOOKUP_COLUMN_SETS:
            if candidate.issubset(col_names):
                tags.append("lookup")
                break
    if not tags and table.kind == "table":
        tags.append("transactional")
    # Dedupe, keep order, cap at 3.
    seen: set[str] = set()
    out: list[str] = []
    for t in tags:
        if t not in seen:
            seen.add(t)
            out.append(t)
    return out[:3]


# ---------------------------------------------------------------------------
# Phase 5 — DESCRIBING
# ---------------------------------------------------------------------------

_TABLE_RESPONSE_FORMAT: dict[str, Any] = {
    "type": "json_schema",
    "json_schema": {
        "name": "table_description",
        "strict": True,
        "schema": {
            "type": "object",
            "additionalProperties": False,
            "required": ["description", "tags"],
            "properties": {
                "description": {"type": "string"},
                "tags": {
                    "type": "array",
                    "maxItems": 3,
                    "items": {"type": "string"},
                },
            },
        },
    },
}

_SUMMARY_RESPONSE_FORMAT: dict[str, Any] = {
    "type": "json_schema",
    "json_schema": {
        "name": "corpus_summary",
        "strict": True,
        "schema": {
            "type": "object",
            "additionalProperties": False,
            "required": ["summary"],
            "properties": {"summary": {"type": "string"}},
        },
    },
}

_TABLE_SYSTEM_PROMPT = (
    "You are a database schema documentarian. Given a table's name, its "
    "columns (name, normalised type, up to 3 redacted sample values), and a "
    "few structural hints, write a concise 2-3 sentence description of what "
    "the table most likely stores and how it's used. Then propose up to 3 "
    "short lowercase tags (e.g. audit_log, lookup, transactional, junction, "
    "config). Never invent column names. Never echo raw values. Respond with "
    "JSON matching the provided schema."
)

_SUMMARY_SYSTEM_PROMPT = (
    "You are a database schema documentarian. Given a list of tables with "
    "short descriptions, write a 4-6 sentence overview of what this database "
    "appears to be for and how the major tables relate. Respond with JSON "
    "matching the provided schema."
)


def _table_llm_payload(table: TableDoc, hints: list[str]) -> str:
    """Build the user message for the per-table DESCRIBING call.

    Deliberately excludes ``native_type`` (audit-only, never shown to the
    LLM) and never includes anything credential-shaped.
    """
    cols = [
        {
            "name": c.name,
            "type": str(c.type),
            "samples": c.sample_values,
        }
        for c in table.columns
    ]
    return json.dumps(
        {
            "table": table.name,
            "kind": table.kind,
            "row_count_estimate": table.row_count_estimate,
            "primary_key": table.primary_key,
            "columns": cols,
            "structural_hints": hints,
        },
        separators=(",", ":"),
    )


async def _describe_table(
    table: TableDoc, resolver: AIModelResolver
) -> None:
    """Fill ``table.description`` + merge LLM tags. Raises on LLM failure."""
    client = await resolver.resolve(_LLM_STAGE)
    hints = _heuristic_tags(table)
    response = await client.http_client.chat.completions.create(
        model=client.model_id,
        messages=[
            {"role": "system", "content": _TABLE_SYSTEM_PROMPT},
            {"role": "user", "content": _table_llm_payload(table, hints)},
        ],
        temperature=client.temperature,
        max_tokens=client.max_tokens,
        response_format=_TABLE_RESPONSE_FORMAT,  # type: ignore[arg-type]
    )
    raw = response.choices[0].message.content or "{}"
    payload = json.loads(raw)
    description = payload.get("description")
    if isinstance(description, str):
        table.description = description.strip()
    llm_tags = payload.get("tags") or []
    merged: list[str] = list(hints)
    for t in llm_tags:
        if isinstance(t, str) and t.strip():
            normalised = t.strip().lower().replace(" ", "_")
            if normalised not in merged:
                merged.append(normalised)
    table.tags = merged[:3]


async def _summarise_corpus(
    tables: list[TableDoc], dialect: str, resolver: AIModelResolver
) -> str:
    """Return a 4-6 sentence corpus summary. Raises on LLM failure."""
    client = await resolver.resolve(_LLM_STAGE)
    table_blurbs = [
        {"table": t.name, "description": t.description, "tags": t.tags}
        for t in tables
    ]
    user_content = json.dumps(
        {"dialect": dialect, "tables": table_blurbs}, separators=(",", ":")
    )
    response = await client.http_client.chat.completions.create(
        model=client.model_id,
        messages=[
            {"role": "system", "content": _SUMMARY_SYSTEM_PROMPT},
            {"role": "user", "content": user_content},
        ],
        temperature=client.temperature,
        max_tokens=client.max_tokens,
        response_format=_SUMMARY_RESPONSE_FORMAT,  # type: ignore[arg-type]
    )
    raw = response.choices[0].message.content or "{}"
    payload = json.loads(raw)
    summary = payload.get("summary")
    return summary.strip() if isinstance(summary, str) else ""


# ---------------------------------------------------------------------------
# Orchestration
# ---------------------------------------------------------------------------


async def study_sql_schema(
    *,
    connection_string: str,
    db_type: str,
    ai_model_resolver: AIModelResolver | None = None,
    sampling_budget_seconds: float = _SAMPLING_BUDGET_SECONDS,
    describing_budget_seconds: float = _DESCRIBING_BUDGET_SECONDS,
) -> SchemaDocument:
    """Run the six-phase studying-agent pipeline for a SQL source.

    Parameters
    ----------
    connection_string:
        Async-compatible SQLAlchemy URL (e.g. ``postgresql+asyncpg://...``).
        Consumed once here; never logged.
    db_type:
        One of ``"postgresql"`` / ``"mysql"`` / ``"mssql"``.
    ai_model_resolver:
        Resolver used for the DESCRIBING phase. When ``None`` the DESCRIBING
        phase is skipped (descriptions/summary stay empty, study is marked
        partial) — useful for callers that don't have a resolver wired.

    Returns
    -------
    SchemaDocument
        Strictly validated; ``fingerprint`` computed via
        :func:`compute_fingerprint`; ``partial`` set iff any phase error.

    Raises
    ------
    SchemaStudyPhaseError
        On a fatal failure (cannot connect, cannot reflect any table).
    """
    dialect = _DIALECT_BY_DB_TYPE.get(db_type)
    if dialect is None:
        raise SchemaStudyPhaseError(
            phase="INVENTORY",
            error_key="UNSUPPORTED_DIALECT",
            message=f"Unsupported SQL dialect for schema study: {db_type!r}",
        )

    start = time.monotonic()
    phase_errors: list[PhaseError] = []
    engine = await _build_engine(connection_string, db_type)
    try:
        # --- Phase 1: CONNECTING -------------------------------------------
        await _phase_connecting(engine)

        # --- Phase 2: INVENTORY --------------------------------------------
        relations = await _phase_inventory(engine)
        tables: list[TableDoc] = []
        for schema, name, kind in relations:
            estimate = await _row_count_estimate(engine, schema, name, db_type)
            tables.append(
                TableDoc(
                    name=_qualified_name(schema, name),
                    kind=kind,  # type: ignore[arg-type]
                    row_count_estimate=estimate,
                    primary_key=[],
                    indexes=[],
                    columns=[],
                    relationships=[],
                    description="",
                    tags=[],
                )
            )

        # --- Phase 3: COLUMNS ----------------------------------------------
        kept_tables: list[TableDoc] = []
        for table, (schema, name, _kind) in zip(tables, relations):
            try:
                cols, pk, idxs, rels = await _phase_columns_for_table(
                    engine, schema, name
                )
            except Exception as exc:  # noqa: BLE001 - per-table degradation
                phase_errors.append(
                    PhaseError(
                        phase="COLUMNS",
                        error_key="REFLECT_FAILED",
                        message=(
                            f"Could not reflect columns for {table.name}: "
                            f"{_sanitise(str(exc))}"
                        ),
                    )
                )
                logger.warning(
                    "sql_inspector: COLUMNS failed for %s — skipping table",
                    table.name,
                    exc_info=True,
                )
                continue
            table.columns = cols
            table.primary_key = pk
            table.indexes = idxs
            table.relationships = rels
            kept_tables.append(table)
        tables = kept_tables

        # --- Phase 4: SAMPLING ---------------------------------------------
        sampling_deadline = time.monotonic() + sampling_budget_seconds
        sampling_truncated = False
        for table in tables:
            if time.monotonic() >= sampling_deadline:
                if not sampling_truncated:
                    logger.warning(
                        "sql_inspector: sampling budget exhausted — "
                        "remaining tables sampled with no values"
                    )
                    sampling_truncated = True
                continue
            try:
                schema, name = (
                    table.name.split(".", 1) if "." in table.name else ("", table.name)
                )
                await _phase_sampling_for_table(
                    engine, schema, name, table.columns, db_type
                )
            except SchemaStudyPhaseError as exc:
                phase_errors.append(
                    PhaseError(
                        phase="SAMPLING",
                        error_key=exc.error_key,
                        message=exc.message,
                    )
                )
            except Exception as exc:  # noqa: BLE001 - never fatal
                phase_errors.append(
                    PhaseError(
                        phase="SAMPLING",
                        error_key="SAMPLE_FAILED",
                        message=(
                            f"Could not sample {table.name}: {_sanitise(str(exc))}"
                        ),
                    )
                )

        # --- Phase 5: DESCRIBING -------------------------------------------
        summary = ""
        if ai_model_resolver is not None and tables:
            describing_deadline = time.monotonic() + describing_budget_seconds
            budget_exhausted = False
            for table in tables:
                if time.monotonic() >= describing_deadline:
                    if not budget_exhausted:
                        budget_exhausted = True
                        logger.warning(
                            "sql_inspector: describing budget exhausted — "
                            "remaining tables left without descriptions"
                        )
                        phase_errors.append(
                            PhaseError(
                                phase="DESCRIBING",
                                error_key="LLM_BUDGET",
                                message=(
                                    "DESCRIBING time budget exhausted; some "
                                    "tables left undescribed."
                                ),
                            )
                        )
                    # Still set heuristic tags even without an LLM call.
                    if not table.tags:
                        table.tags = _heuristic_tags(table)
                    continue
                try:
                    await _describe_table(table, ai_model_resolver)
                except Exception as exc:  # noqa: BLE001 - never fatal
                    if not table.tags:
                        table.tags = _heuristic_tags(table)
                    phase_errors.append(
                        PhaseError(
                            phase="DESCRIBING",
                            error_key="LLM_ERROR",
                            message=(
                                f"LLM could not describe {table.name}: "
                                f"{_sanitise(str(exc))}"
                            ),
                        )
                    )
            try:
                summary = await _summarise_corpus(
                    tables, dialect, ai_model_resolver
                )
            except Exception as exc:  # noqa: BLE001 - never fatal
                phase_errors.append(
                    PhaseError(
                        phase="DESCRIBING",
                        error_key="LLM_ERROR",
                        message=(
                            f"LLM could not summarise the corpus: "
                            f"{_sanitise(str(exc))}"
                        ),
                    )
                )
        else:
            # No resolver — fall back to heuristic tags only, mark partial.
            for table in tables:
                if not table.tags:
                    table.tags = _heuristic_tags(table)
            if ai_model_resolver is None:
                phase_errors.append(
                    PhaseError(
                        phase="DESCRIBING",
                        error_key="LLM_UNAVAILABLE",
                        message="No LLM resolver available; descriptions skipped.",
                    )
                )

        # --- Phase 6: INDEXING — not done this slice; vector_index_ref=None.

        tables.sort(key=lambda t: t.name)
        duration_ms = max(0, int((time.monotonic() - start) * 1000))
        partial = bool(phase_errors)
        doc = SchemaDocument(
            dialect=dialect,
            fingerprint="0" * 64,  # placeholder, replaced below
            generated_at=datetime.now(tz=timezone.utc),
            agent_version=AGENT_VERSION,
            study_duration_ms=duration_ms,
            partial=partial,
            phase_errors=phase_errors,
            tables=tables,
            summary=summary,
            vector_index_ref=None,
        )
        return doc.model_copy(update={"fingerprint": compute_fingerprint(doc)})
    finally:
        await engine.dispose()


__all__ = ["AGENT_VERSION", "study_sql_schema"]
