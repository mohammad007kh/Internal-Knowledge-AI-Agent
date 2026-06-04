"""Schema-context chunk builder for DB sources (FX37).

The studying agent persists a structured :class:`SchemaDocument` into
``schema_studies.schema_document_json`` for every database source. The
chat pipeline's :func:`src.agent.nodes.retrieve.retrieve_context`
historically read **only** from the ``chunks`` table (vector embeddings),
which is empty for DB sources — so a question like "Please tell me about
this database" reached the synthesizer with zero grounding context and
the LLM elected to respond with a generic greeting.

This helper renders a compact text block from the latest completed
SchemaStudy and packages it as a chunk dict in the same shape
``retrieve_context`` produces, so the synthesizer's
:func:`src.agent.prompts.render_system_prompt` picks it up automatically
— no change needed in the prompt template or the generate node.

The helper is intentionally read-only and defensive: any DB / parse /
validation failure returns an empty list (the pipeline degrades to its
historical behaviour — generic "no info" reply — rather than crashing).
"""

from __future__ import annotations

import logging
import uuid
from typing import TYPE_CHECKING, Any

from sqlalchemy import select

from src.agent.nodes._intent_render import render_intent_block
from src.models.enums import SourceType
from src.models.schema_study import SchemaStudy
from src.models.source import Source
from src.services.db_introspection.schema_doc import SchemaDocument

if TYPE_CHECKING:
    from sqlalchemy.ext.asyncio import AsyncSession

logger = logging.getLogger(__name__)

# Cap how many tables we render into the synthesizer chunk. Past this the
# prompt grows faster than the LLM can attend to; truncation is documented
# inline so the model knows it isn't seeing the full catalogue.
_MAX_TABLES = 25
# Cap per-table description so a single chatty table can't blow the
# context budget.
_DESCRIPTION_CHAR_CAP = 240
# Cap how many columns we list per table. Wide tables (50+ columns) would
# otherwise blow the budget on a single relation.
_MAX_COLUMNS_PER_TABLE = 12


def _safe_uuids(values: list[str]) -> list[uuid.UUID]:
    """Coerce a list of strings into validated UUIDs, dropping invalid entries."""
    out: list[uuid.UUID] = []
    for v in values:
        if not isinstance(v, str):
            continue
        try:
            out.append(uuid.UUID(v))
        except (ValueError, TypeError):
            continue
    return out


def _render_chunk_text(source: Source, doc: SchemaDocument) -> str:
    """Render a SchemaDocument as a compact human-readable text block.

    Format::

        Database source: orders-db (dialect: postgresql)
        Summary: A PostgreSQL database containing customer-order data.
        Tables (5 total): public.customers, public.orders, public.order_items, ...
        - public.customers (table) PK=[id]
            columns: id:int, email:text, name:text
            note: Per-customer master record.
        - public.orders (table) PK=[id]
            columns: id:int, customer_id:int, total:float
            note: One row per purchase order.

    The format is deliberately deterministic so prompt tokens stay stable
    across runs; the LLM should treat this as the authoritative schema
    description for the source.

    Source *intent* (purpose / example questions / out-of-scope) renders
    ABOVE the schema block — inside the same pinned chunk — so the answer
    synthesizer always sees the source's purpose even when the table list is
    truncated past ``_MAX_TABLES`` (FR-004). Intent is delimiter-wrapped and
    flagged as data, never instructions (security rule 1).
    """
    lines: list[str] = []

    # -- Intent block FIRST (survives _MAX_TABLES truncation, FR-004) --------
    intent_block = render_intent_block(
        purpose=getattr(source, "purpose", None),
        example_questions=getattr(source, "example_questions", None),
        out_of_scope=getattr(source, "out_of_scope", None),
        intent_status=getattr(source, "intent_status", None),
    )
    if intent_block:
        lines.append(intent_block)
        lines.append("")  # blank line separates intent from the schema render

    lines.append(
        f"Database source: {source.name} (dialect: {doc.dialect})"
    )
    if doc.summary.strip():
        lines.append(f"Summary: {doc.summary.strip()[:_DESCRIPTION_CHAR_CAP * 2]}")

    total_tables = len(doc.tables)
    if total_tables == 0:
        lines.append("Tables: (none — the studying agent found no relations)")
        return "\n".join(lines)

    # One-line catalogue first — gives the LLM a fast "what's in here?" hit
    # before the per-table detail block.
    head_names = [t.name for t in doc.tables[:_MAX_TABLES]]
    catalogue = ", ".join(head_names)
    if total_tables > _MAX_TABLES:
        catalogue += f", ... (+{total_tables - _MAX_TABLES} more)"
    lines.append(f"Tables ({total_tables} total): {catalogue}")

    for table in doc.tables[:_MAX_TABLES]:
        pk = f" PK=[{', '.join(table.primary_key)}]" if table.primary_key else ""
        lines.append(f"- {table.name} ({table.kind}){pk}")
        if table.columns:
            cols = ", ".join(
                f"{c.name}:{c.type}" for c in table.columns[:_MAX_COLUMNS_PER_TABLE]
            )
            if len(table.columns) > _MAX_COLUMNS_PER_TABLE:
                cols += f", ... (+{len(table.columns) - _MAX_COLUMNS_PER_TABLE} more)"
            lines.append(f"    columns: {cols}")
        desc = table.description.strip()
        if desc:
            lines.append(f"    note: {desc[:_DESCRIPTION_CHAR_CAP]}")

    if total_tables > _MAX_TABLES:
        lines.append(
            f"(truncated — {total_tables - _MAX_TABLES} additional tables not shown)"
        )

    return "\n".join(lines)


async def _load_latest_study(
    db: AsyncSession, source_id: uuid.UUID
) -> SchemaStudy | None:
    """Fetch the most recently finished SchemaStudy with a non-null document.

    Ordered by ``finished_at DESC NULLS LAST`` so the freshest READY /
    READY_PARTIAL row wins even when an older study row is still in a
    failed terminal state.
    """
    stmt = (
        select(SchemaStudy)
        .where(SchemaStudy.source_id == source_id)
        .where(SchemaStudy.schema_document_json.is_not(None))
        .order_by(SchemaStudy.finished_at.desc().nulls_last())
        .limit(1)
    )
    return (await db.execute(stmt)).scalar_one_or_none()


def _build_chunk_dict(source: Source, text: str) -> dict[str, Any]:
    """Package the rendered text in the same shape `retrieve_context` emits.

    Schema context is a *pinned* grounding channel, not a vector hit: it must
    always be present for a studied DB source regardless of similarity. So we
    deliberately omit the ``score`` key rather than fake a perfect-match
    distance (the old ``score=0.0`` hack). ``render_system_prompt``'s
    low-confidence detector uses ``chunk.get("score")`` and skips chunks whose
    score is non-numeric, so a missing key cleanly excludes pinned schema
    context from the mean-distance confidence signal. ``chunk_id`` is
    namespaced with a ``schema:`` prefix so persist / citation code can
    recognise the synthetic origin.
    """
    return {
        "chunk_id": f"schema:{source.id}",
        "source_id": str(source.id),
        "text": text,
        "document_title": f"{source.name} — schema overview",
        "page_number": None,
        "source_name": source.name,
    }


async def load_schema_context_chunks(
    db: AsyncSession,
    *,
    source_ids: list[str],
) -> list[dict[str, Any]]:
    """Return synthesizer-ready chunks for every DB source with a study.

    For each ``source_id`` in *source_ids* that is (a) a DATABASE source
    and (b) has a completed SchemaStudy with a non-null
    ``schema_document_json``, emit exactly one chunk containing a compact
    text rendering of the schema (summary, table inventory, per-table
    columns + notes).

    Non-DB sources, soft-deleted sources, sources without a study, and
    sources whose study JSON fails strict validation are silently skipped
    — never raised — so a misconfigured corner case never takes the chat
    pipeline down.

    Returns an empty list when *source_ids* is empty or no DB sources
    qualify.
    """
    if not source_ids:
        return []

    uuids = _safe_uuids(source_ids)
    if not uuids:
        return []

    try:
        stmt = (
            select(Source)
            .where(Source.id.in_(uuids))
            .where(Source.deleted_at.is_(None))
            .where(Source.source_type == SourceType.DATABASE)
        )
        rows = (await db.execute(stmt)).scalars().all()
    except Exception:  # noqa: BLE001 - defensive
        logger.warning(
            "schema_context: source query failed — skipping schema chunks",
            exc_info=True,
        )
        return []

    chunks: list[dict[str, Any]] = []
    for source in rows:
        try:
            study = await _load_latest_study(db, source.id)
        except Exception:  # noqa: BLE001 - defensive
            logger.warning(
                "schema_context: study query failed for source=%s — skipping",
                source.id,
                exc_info=True,
            )
            continue

        if study is None or study.schema_document_json is None:
            logger.debug(
                "schema_context: no completed study for source=%s — skipping",
                source.id,
            )
            continue

        try:
            doc = SchemaDocument.model_validate(study.schema_document_json)
        except Exception:  # noqa: BLE001 - bad JSON shape is recoverable
            logger.warning(
                "schema_context: schema_document_json failed validation for "
                "source=%s — skipping",
                source.id,
                exc_info=True,
            )
            continue

        text = _render_chunk_text(source, doc)
        chunks.append(_build_chunk_dict(source, text))

    if chunks:
        logger.info(
            "schema_context: emitted %d schema chunk(s) for %d DB source(s)",
            len(chunks),
            len(rows),
        )
    return chunks
