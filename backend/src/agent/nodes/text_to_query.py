"""text_to_query — LangGraph node that converts the user's natural-language
question into a read-only SQL SELECT for each routed database source.

Resolver slot: ``text_to_query``.

Only fires when ``state["text_to_query_source_ids"]`` is non-empty.
For each such source the node:

1. Resolves the source's connection config from the DB.
2. Generates a SQL SELECT via the LLM.
3. Validates the SQL is read-only via the shared sqlglot-based
   :func:`src.services.db_safety.validate_sql` (no more regex
   blocklist false-positives on column names like ``update_at``).
4. Appends ``LIMIT 100`` via the dialect-aware
   :func:`src.services.db_safety.inject_limit` (works on MSSQL's
   ``OFFSET / FETCH NEXT`` too).
5. Executes it; appends each row as a chunk so ``persist`` renders citations.

State writes (merged into existing fields):
* ``retrieved_chunks`` — extended with one chunk per row.
* ``generated_sql`` — ``{source_id: sql}`` for trace/debug.

Defensive fallbacks:
* SQL safety check fails → skip that source, log warning.
* Source connect / execute fails → skip that source, continue.
* No source list → no-op.

Constitution: SQL injection prevention is non-negotiable.  We refuse
anything that is not a single ``SELECT`` statement.
"""
from __future__ import annotations

import logging
import uuid
from typing import TYPE_CHECKING, Any

import sqlalchemy as sa
from sqlalchemy.ext.asyncio import create_async_engine

from src.agent.nodes._intent_render import render_intent_block
from src.agent.state import AgentState
from src.core.crypto import decrypt
from src.models.enums import SourceType
from src.prompts import load_prompt
from src.services.db_safety import (
    harden_postgres_engine_kwargs,
    inject_limit,
    redact_dsn,
    validate_sql,
)

if TYPE_CHECKING:
    from langfuse import Langfuse
    from sqlalchemy.ext.asyncio import AsyncSession

    from src.repositories.source_repository import SourceRepository
    from src.services.ai_model_resolver import AIModelResolver

logger = logging.getLogger(__name__)

_STAGE = "text_to_query"
_LIMIT = 100

# ---------------------------------------------------------------------------
# Credential / DSN redaction (FR-020)
# ---------------------------------------------------------------------------
# ``_execute`` opens an engine from the source's decrypted ``connection_string``.
# A driver (asyncpg / SQLAlchemy) failure can embed that DSN
# (``scheme://user:pass@host`` URL, ``password=...`` key-value, bare
# ``host:port``) in ``str(exc)``. We log the *sanitised* message instead of a
# raw traceback, delegating to the single canonical hardened redactor
# (:func:`src.services.db_safety.redact_dsn`). The module-local alias preserves
# the existing call sites / test imports.
_sanitise = redact_dsn

# Map ``config["db_type"]`` to a sqlglot dialect name.  ``mssql`` is sqlglot's
# ``tsql``; everything else falls back to ``postgres`` (the strictest parser
# of the supported set, which is the right safety default).
_DIALECT_BY_DB_TYPE: dict[str, str] = {
    "postgresql": "postgres",
    "mysql": "mysql",
    "mssql": "tsql",
}


def _dialect_for(config: dict[str, Any]) -> str:
    return _DIALECT_BY_DB_TYPE.get(str(config.get("db_type", "")), "postgres")


# NOTE: The previous regex-based ``is_safe_sql`` and subquery-wrapping
# ``wrap_with_limit`` helpers have been removed from this module.  All
# callers now go through the shared sqlglot-based primitives:
#
#     from src.services.db_safety import validate_sql, inject_limit
#
# This eliminates the documented false-positive on column names like
# ``update_at`` / ``call`` / ``delete_at`` that the old keyword blocklist
# triggered on, and produces dialect-correct output on MSSQL.


def _row_to_text(row: Any) -> str:
    """Render a SQL row as ``col: value`` lines for the synthesizer."""
    try:
        return "\n".join(f"{col}: {val}" for col, val in row.items())
    except Exception:  # noqa: BLE001
        return str(row)


async def _generate_sql(
    *,
    query: str,
    schema_sketch: str,
    ai_model_resolver: AIModelResolver,
) -> tuple[str, int, int]:
    client = await ai_model_resolver.resolve(_STAGE)
    prompt = load_prompt(_STAGE, custom=client.custom_prompt)
    user_payload = (
        f"Schema sketch:\n{schema_sketch or '(no schema available)'}\n\n"
        f"Question: {query}"
    )
    response = await client.http_client.chat.completions.create(
        model=client.model_id,
        messages=[
            {"role": "system", "content": prompt},
            {"role": "user", "content": user_payload},
        ],
        temperature=client.temperature,
        max_tokens=client.max_tokens,
    )
    in_tok = int(response.usage.prompt_tokens) if response.usage else 0
    out_tok = int(response.usage.completion_tokens) if response.usage else 0
    return (response.choices[0].message.content or "").strip(), in_tok, out_tok


def _decrypt_source_config(source: Any) -> dict[str, Any] | None:
    """Decrypt and parse the source's encrypted JSON config.

    Returns None on any decryption / parse failure.
    """
    if not getattr(source, "config_encrypted", None):
        return None
    try:
        import json  # noqa: PLC0415

        plaintext = decrypt(source.config_encrypted)
        return dict(json.loads(plaintext))
    except Exception:  # noqa: BLE001
        logger.warning(
            "text_to_query: failed to decrypt config for source=%s", source.id,
            exc_info=True,
        )
        return None


async def _execute(
    connection_string: str,
    sql: str,
    *,
    db_type: str,
) -> list[Any]:
    """Run *sql* against *connection_string*; returns list of mapping rows.

    For Postgres sources the connection string is run through
    ``harden_postgres_connection`` so ``default_transaction_read_only=on`` and
    ``statement_timeout`` apply at the libpq level — defense in depth alongside
    ``validate_sql``. Other dialects fall back to the raw string until Phase 2
    ships their hardening helpers.
    """
    if db_type == "postgresql":
        hardened = await harden_postgres_engine_kwargs(connection_string)
        engine = create_async_engine(
            **hardened.as_create_async_engine_kwargs(),
            pool_size=1,
            max_overflow=0,
        )
    else:
        engine = create_async_engine(
            connection_string,
            pool_size=1,
            max_overflow=0,
        )
    try:
        async with engine.connect() as conn:
            result = await conn.execute(sa.text(sql))
            return list(result.mappings().all())
    finally:
        await engine.dispose()


async def text_to_query(
    state: AgentState,
    *,
    ai_model_resolver: AIModelResolver,
    db_session: AsyncSession,
    source_repository: SourceRepository,
    langfuse: Langfuse,
) -> dict[str, Any]:
    """Run NL→SQL retrieval for each routed database source.

    Result chunks are appended to ``retrieved_chunks`` with metadata
    so ``persist.format_response`` renders human-readable citations.
    """
    target_ids: list[str] = list(state.get("text_to_query_source_ids") or [])
    query: str = (state.get("query") or "").strip()
    if not target_ids or not query:
        return {}

    span = langfuse.span(  # type: ignore[attr-defined]
        trace_id=state["trace_id"],
        name=_STAGE,
        input={"target_count": len(target_ids), "query": query[:200]},
    )

    new_chunks: list[dict[str, Any]] = []
    generated_sql: dict[str, str] = {}
    skipped: list[str] = []
    total_in = 0
    total_out = 0

    try:
        # Resolve sources by id (defensive — bad inputs just get skipped).
        try:
            uuids: list[uuid.UUID] = []
            for sid in target_ids:
                try:
                    uuids.append(uuid.UUID(sid))
                except (ValueError, TypeError):
                    skipped.append(sid)
            sources = await source_repository.list_by_ids(uuids) if uuids else []
        except Exception:  # noqa: BLE001
            logger.warning("text_to_query: failed to load sources", exc_info=True)
            return {}

        for source in sources:
            sid = str(source.id)
            if source.source_type != SourceType.DATABASE:
                skipped.append(sid)
                continue

            config = _decrypt_source_config(source)
            if config is None or not config.get("connection_string"):
                logger.info(
                    "text_to_query: source=%s has no connection_string — skipping",
                    sid,
                )
                skipped.append(sid)
                continue

            # Schema sketch — prefer the studying agent's persisted
            # SchemaDocument over the AI-authored description. The Phase 1
            # Wave 1 studying agent persists a structured doc into
            # ``schema_studies.schema_document_json``; that's a much
            # higher-signal input for SQL generation than the freeform
            # description (which targets retrieval routing, not query
            # synthesis). Fall back to ``source.description`` only when
            # no study has completed yet.
            schema_sketch = await _load_schema_sketch(db_session, source)

            try:
                raw_sql, in_tok, out_tok = await _generate_sql(
                    query=query,
                    schema_sketch=schema_sketch,
                    ai_model_resolver=ai_model_resolver,
                )
                total_in += in_tok
                total_out += out_tok
            except Exception:  # noqa: BLE001
                logger.warning(
                    "text_to_query: LLM call failed for source=%s", sid,
                    exc_info=True,
                )
                skipped.append(sid)
                continue

            dialect = _dialect_for(config)
            validation = validate_sql(raw_sql, dialect=dialect)
            if not validation.is_safe:
                logger.warning(
                    "text_to_query: unsafe SQL for source=%s reason=%s — skipping",
                    sid,
                    validation.error_key,
                )
                skipped.append(sid)
                continue

            try:
                wrapped = inject_limit(raw_sql, n=_LIMIT, dialect=dialect)
            except ValueError:
                # Defensive: validate_sql passed but inject_limit choked.
                # Skip this source rather than emit a half-formed query.
                logger.warning(
                    "text_to_query: limit injection failed for source=%s — skipping",
                    sid,
                    exc_info=True,
                )
                skipped.append(sid)
                continue
            generated_sql[sid] = wrapped

            try:
                rows = await _execute(
                    config["connection_string"],
                    wrapped,
                    db_type=str(config.get("db_type", "")),
                )
            except Exception as exc:  # noqa: BLE001
                # ``exc_info`` is intentionally OMITTED: the traceback's final
                # line renders ``str(exc)``, and a driver (asyncpg/SQLAlchemy)
                # connection failure can embed the DSN there. Log the exception
                # type + a *sanitised* message instead (FR-020).
                logger.warning(
                    "text_to_query: execution failed for source=%s — skipping "
                    "[%s: %s]",
                    sid,
                    type(exc).__name__,
                    _sanitise(exc),
                )
                skipped.append(sid)
                continue

            for row in rows:
                new_chunks.append(
                    {
                        "chunk_id": f"sql:{sid}:{len(new_chunks)}",
                        "source_id": sid,
                        "text": _row_to_text(row),
                        "score": 0.0,
                        "document_title": source.name,
                        "page_number": None,
                        "source_name": source.name,
                    }
                )

        existing = list(state.get("retrieved_chunks") or [])
        merged = existing + new_chunks
        span.update(
            output={
                "rows_added": len(new_chunks),
                "sources_used": len(generated_sql),
                "sources_skipped": len(skipped),
            }
        )
        logger.info(
            "text_to_query: produced %d rows from %d sources (skipped=%d)",
            len(new_chunks),
            len(generated_sql),
            len(skipped),
        )
        return {
            "retrieved_chunks": merged,
            "generated_sql": generated_sql,
            "total_input_tokens": total_in,
            "total_output_tokens": total_out,
        }
    finally:
        span.end()


# ---------------------------------------------------------------------------
# Schema-sketch loader
# ---------------------------------------------------------------------------


_MAX_TABLES_FOR_SKETCH = 30
"""Cap how many tables we render into the SQL-generation prompt. Past this
the LLM stops paying attention; truncation is documented in the prompt."""


def _description_fallback(source: Any) -> str:
    """Render the schema-sketch fallback when no usable SchemaDocument exists.

    The source's *purpose* takes precedence over the bare ``description``
    (T-024 / FR-004): a delimiter-wrapped, treat-as-data intent block leads,
    followed by the freeform description as supplementary context. Falls back
    to the bare description when no intent is authored, and to an empty string
    when neither is present.
    """
    intent_block = render_intent_block(
        purpose=getattr(source, "purpose", None),
        example_questions=getattr(source, "example_questions", None),
        out_of_scope=getattr(source, "out_of_scope", None),
        intent_status=getattr(source, "intent_status", None),
    )
    description = (getattr(source, "description", None) or "").strip()

    if not intent_block:
        return description
    if not description:
        return intent_block
    return f"{intent_block}\n\n{description}"


async def _load_schema_sketch(
    db: AsyncSession,  # noqa: F821 — forward ref under TYPE_CHECKING
    source: Any,
) -> str:
    """Render the latest persisted SchemaDocument as a compact text block
    suitable for the text-to-SQL prompt.

    Falls back to the source's intent (purpose-first, delimiter-wrapped) and
    then its bare ``description`` when no SchemaStudy exists yet (e.g., source
    created before Wave 1 shipped, or the studying agent hasn't finished its
    first run). See :func:`_description_fallback`.

    The shape we emit is deliberately deterministic so prompt tokens stay
    stable — one line per table with type/PK/columns and a trailing
    relationships block.
    """
    from sqlalchemy import select  # noqa: PLC0415

    from src.models.schema_study import SchemaStudy  # noqa: PLC0415
    from src.services.db_introspection.schema_doc import SchemaDocument  # noqa: PLC0415

    stmt = (
        select(SchemaStudy)
        .where(SchemaStudy.source_id == source.id)
        .where(SchemaStudy.schema_document_json.is_not(None))
        .order_by(SchemaStudy.finished_at.desc().nulls_last())
        .limit(1)
    )
    study = (await db.execute(stmt)).scalar_one_or_none()
    if study is None or study.schema_document_json is None:
        return _description_fallback(source)

    try:
        doc = SchemaDocument.model_validate(study.schema_document_json)
    except Exception:  # noqa: BLE001 — bad JSON shape is recoverable
        logger.warning(
            "text_to_query: schema_document_json failed strict validation — "
            "falling back to source intent / description",
            extra={"source_id": str(source.id)},
            exc_info=True,
        )
        return _description_fallback(source)

    return _render_schema_sketch(doc)


def _render_schema_sketch(doc: SchemaDocument) -> str:  # noqa: F821
    """Format a :class:`SchemaDocument` into a compact text block the LLM
    can read efficiently.

    Format::

        Dialect: postgresql
        Tables:
        - public.orders (table) PK=[id]
            columns: id:int, customer_id:int, total:float, ...
            description: Per-customer purchase orders.
        - public.customers (table) PK=[id]
            columns: id:int, email:text, ...
        Relationships:
        - public.orders.customer_id -> public.customers.id

    Truncates beyond _MAX_TABLES_FOR_SKETCH and notes the truncation
    inline so the LLM knows it doesn't have the full schema.
    """
    lines: list[str] = [f"Dialect: {doc.dialect}", "Tables:"]
    considered = doc.tables[:_MAX_TABLES_FOR_SKETCH]
    for table in considered:
        pk_str = f" PK=[{', '.join(table.primary_key)}]" if table.primary_key else ""
        lines.append(f"- {table.name} ({table.kind}){pk_str}")
        if table.columns:
            cols = ", ".join(
                f"{c.name}:{c.type}" for c in table.columns[:20]
            )
            if len(table.columns) > 20:
                cols += f", ... (+{len(table.columns) - 20} more)"
            lines.append(f"    columns: {cols}")
        if table.description.strip():
            # Cap per-table description so a single chatty table can't
            # blow the prompt budget.
            lines.append(f"    description: {table.description.strip()[:200]}")
    if len(doc.tables) > _MAX_TABLES_FOR_SKETCH:
        extra = len(doc.tables) - _MAX_TABLES_FOR_SKETCH
        lines.append(f"  (truncated — {extra} additional tables not shown)")

    relationships: list[str] = []
    for table in considered:
        for rel in table.relationships:
            from_cols = ".".join([table.name, ",".join(rel.from_columns)])
            to_cols = ".".join([rel.to_table, ",".join(rel.to_columns)])
            relationships.append(f"- {from_cols} -> {to_cols}")
    if relationships:
        lines.append("Relationships:")
        lines.extend(relationships)

    return "\n".join(lines)
