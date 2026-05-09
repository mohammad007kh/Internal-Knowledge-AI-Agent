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

from src.agent.state import AgentState
from src.core.crypto import decrypt
from src.models.enums import SourceType
from src.prompts import load_prompt
from src.services.db_safety import (
    harden_postgres_connection,
    inject_limit,
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
) -> str:
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
    return (response.choices[0].message.content or "").strip()


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
        connection_string = await harden_postgres_connection(connection_string)
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

            # Schema sketch — pull from cached description for now.
            schema_sketch = source.description or ""

            try:
                raw_sql = await _generate_sql(
                    query=query,
                    schema_sketch=schema_sketch,
                    ai_model_resolver=ai_model_resolver,
                )
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
            except Exception:  # noqa: BLE001
                logger.warning(
                    "text_to_query: execution failed for source=%s — skipping",
                    sid,
                    exc_info=True,
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
        }
    finally:
        span.end()
