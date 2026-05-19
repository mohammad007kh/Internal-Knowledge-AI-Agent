"""Unit tests for the FX37 schema-context chunk builder.

The helper is used by :func:`src.agent.nodes.retrieve.retrieve_context`
to surface the studying-agent's SchemaDocument into the synthesizer's
prompt for DB sources — without it, a question like "tell me about this
database" reaches an empty context block and the LLM falls back to a
generic greeting.

These tests are pure-async unit coverage: no live DB, no live LLM.
"""

from __future__ import annotations

import os
import uuid
from datetime import datetime, timezone
from unittest.mock import AsyncMock, MagicMock

# Same env-var preamble as the rest of the agent unit suite — required
# before ``src.*`` imports load core.config.
os.environ.setdefault("DATABASE_URL", "postgresql+asyncpg://test:test@localhost/test")
os.environ.setdefault("JWT_SECRET_KEY", "test-jwt-secret-key-at-least-32-chars-long!!")
os.environ.setdefault("JWT_REFRESH_SECRET_KEY", "test-jwt-refresh-secret-key-32-chars!!")
os.environ.setdefault("MINIO_ENDPOINT", "localhost:9000")
os.environ.setdefault("MINIO_ACCESS_KEY", "testaccess")
os.environ.setdefault("MINIO_SECRET_KEY", "testsecret")
os.environ.setdefault("ENCRYPTION_KEY", "dGVzdGVuY3J5cHRpb25rZXkxMjM0NTY3ODk=")

import pytest  # noqa: E402

from src.agent.nodes._schema_context import (  # noqa: E402
    _build_chunk_dict,
    _render_chunk_text,
    load_schema_context_chunks,
)
from src.models.enums import SourceType  # noqa: E402
from src.models.source import Source  # noqa: E402
from src.services.db_introspection.schema_doc import (  # noqa: E402
    ColumnDoc,
    SchemaDocument,
    TableDoc,
)


# ---------------------------------------------------------------------------
# Fixture builders
# ---------------------------------------------------------------------------


def _make_db_source(name: str = "orders-db") -> Source:
    s = Source(
        name=name,
        source_type=SourceType.DATABASE,
        owner_id=uuid.uuid4(),
        is_active=True,
    )
    s.id = uuid.uuid4()
    s.description = "stale description that should NOT show up in the chunk"
    return s


def _make_web_source(name: str = "blog") -> Source:
    s = Source(
        name=name,
        source_type=SourceType.WEB_URL,
        owner_id=uuid.uuid4(),
        is_active=True,
    )
    s.id = uuid.uuid4()
    s.description = "Web URL source"
    return s


def _make_table(
    name: str,
    *,
    columns: list[tuple[str, str]] | None = None,
    pk: list[str] | None = None,
    description: str = "",
) -> TableDoc:
    cols = [
        ColumnDoc(name=n, type=t, native_type=t)  # type: ignore[arg-type]
        for n, t in (columns or [])
    ]
    return TableDoc(
        name=name,
        kind="table",
        primary_key=pk or [],
        indexes=[],
        columns=cols,
        relationships=[],
        description=description,
        tags=[],
    )


def _make_doc(
    *,
    tables: list[TableDoc] | None = None,
    summary: str = "",
    dialect: str = "postgresql",
) -> SchemaDocument:
    return SchemaDocument(
        dialect=dialect,  # type: ignore[arg-type]
        fingerprint="x" * 64,
        generated_at=datetime.now(tz=timezone.utc),
        agent_version="1.0.0",
        study_duration_ms=1,
        partial=False,
        phase_errors=[],
        tables=tables or [],
        summary=summary,
    )


def _study_with(doc: SchemaDocument | None) -> MagicMock:
    s = MagicMock()
    s.schema_document_json = doc.model_dump(mode="json") if doc else None
    s.finished_at = datetime.now(tz=timezone.utc)
    return s


def _db_mock(*, sources: list[Source], study_by_source_id: dict | None = None) -> MagicMock:
    """Build a tiny AsyncSession stub that returns *sources* for the Source
    query and a per-source study (or None) for the SchemaStudy query.

    The helper always issues TWO kinds of queries: one initial Source
    select that returns DB sources, then one SchemaStudy select per
    source. The mock dispatches by call order.
    """
    study_by_source_id = study_by_source_id or {}
    db = MagicMock()
    call_count = {"n": 0}

    async def _execute(stmt):  # noqa: ANN001 — opaque sa.Select
        call_count["n"] += 1
        result = MagicMock()
        if call_count["n"] == 1:
            # First call: the Source.id.in_(...) select.
            scalars = MagicMock()
            scalars.all = MagicMock(return_value=sources)
            result.scalars = MagicMock(return_value=scalars)
            return result
        # Subsequent calls: SchemaStudy lookups, one per DB source.
        idx = call_count["n"] - 2
        source = sources[idx] if idx < len(sources) else None
        study = study_by_source_id.get(source.id) if source else None
        result.scalar_one_or_none = MagicMock(return_value=study)
        return result

    db.execute = AsyncMock(side_effect=_execute)
    return db


# ---------------------------------------------------------------------------
# _render_chunk_text — deterministic output shape
# ---------------------------------------------------------------------------


def test_render_includes_source_name_dialect_and_summary() -> None:
    source = _make_db_source(name="my-orders")
    doc = _make_doc(
        summary="An order-tracking database with customers and shipments.",
        tables=[_make_table("public.orders", pk=["id"])],
    )
    text = _render_chunk_text(source, doc)
    assert "Database source: my-orders" in text
    assert "dialect: postgresql" in text
    assert "An order-tracking database" in text
    assert "public.orders" in text


def test_render_lists_table_inventory_one_line() -> None:
    source = _make_db_source()
    doc = _make_doc(
        tables=[
            _make_table("public.customers"),
            _make_table("public.orders"),
            _make_table("public.shipments"),
        ]
    )
    text = _render_chunk_text(source, doc)
    # Inventory line names every table.
    assert "Tables (3 total): public.customers, public.orders, public.shipments" in text


def test_render_includes_per_table_columns_and_pk() -> None:
    source = _make_db_source()
    doc = _make_doc(
        tables=[
            _make_table(
                "public.customers",
                pk=["id"],
                columns=[("id", "int"), ("email", "text")],
                description="Master customer record.",
            )
        ]
    )
    text = _render_chunk_text(source, doc)
    assert "- public.customers (table) PK=[id]" in text
    assert "columns: id:int, email:text" in text
    assert "note: Master customer record." in text


def test_render_truncates_wide_table_column_list() -> None:
    source = _make_db_source()
    wide_cols = [(f"c{i}", "text") for i in range(50)]
    doc = _make_doc(tables=[_make_table("public.wide", columns=wide_cols)])
    text = _render_chunk_text(source, doc)
    assert "(+38 more)" in text  # 50 cols - 12 rendered = 38 extras


def test_render_truncates_long_table_inventory() -> None:
    source = _make_db_source()
    many = [_make_table(f"public.t{i}") for i in range(40)]
    doc = _make_doc(tables=many)
    text = _render_chunk_text(source, doc)
    assert "40 total" in text
    assert "+15 more" in text  # 40 - 25 cap = 15
    assert "truncated" in text.lower()


def test_render_no_tables_emits_explicit_placeholder() -> None:
    source = _make_db_source()
    doc = _make_doc(tables=[])
    text = _render_chunk_text(source, doc)
    assert "Tables: (none" in text


# ---------------------------------------------------------------------------
# _build_chunk_dict — synthesizer-shaped chunk
# ---------------------------------------------------------------------------


def test_chunk_dict_uses_synthetic_chunk_id_and_zero_score() -> None:
    source = _make_db_source(name="orders-db")
    chunk = _build_chunk_dict(source, "rendered text")
    assert chunk["chunk_id"] == f"schema:{source.id}"
    assert chunk["source_id"] == str(source.id)
    assert chunk["text"] == "rendered text"
    assert chunk["score"] == 0.0
    assert chunk["source_name"] == "orders-db"


# ---------------------------------------------------------------------------
# load_schema_context_chunks — full helper
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_helper_returns_empty_on_empty_source_ids() -> None:
    db = _db_mock(sources=[])
    out = await load_schema_context_chunks(db, source_ids=[])
    assert out == []
    # Crucially, no DB query was issued.
    db.execute.assert_not_called()


@pytest.mark.asyncio
async def test_helper_returns_empty_on_all_invalid_uuids() -> None:
    db = _db_mock(sources=[])
    out = await load_schema_context_chunks(
        db, source_ids=["not-a-uuid", "also-bad"]
    )
    assert out == []
    db.execute.assert_not_called()


@pytest.mark.asyncio
async def test_helper_returns_empty_when_no_db_sources() -> None:
    # All sources are non-DB → the Source query filters them out and returns [].
    db = _db_mock(sources=[])
    out = await load_schema_context_chunks(
        db, source_ids=[str(uuid.uuid4())]
    )
    assert out == []


@pytest.mark.asyncio
async def test_helper_returns_empty_when_db_source_has_no_study() -> None:
    src = _make_db_source()
    db = _db_mock(sources=[src], study_by_source_id={src.id: None})
    out = await load_schema_context_chunks(db, source_ids=[str(src.id)])
    assert out == []


@pytest.mark.asyncio
async def test_helper_returns_empty_when_study_json_is_none() -> None:
    src = _make_db_source()
    study = _study_with(None)
    db = _db_mock(sources=[src], study_by_source_id={src.id: study})
    out = await load_schema_context_chunks(db, source_ids=[str(src.id)])
    assert out == []


@pytest.mark.asyncio
async def test_helper_renders_chunk_for_db_source_with_completed_study() -> None:
    src = _make_db_source(name="cctp-db")
    doc = _make_doc(
        summary="cctp = customer-care-tracking-platform main store.",
        tables=[
            _make_table("public.tickets", pk=["id"]),
            _make_table("public.agents", pk=["id"]),
        ],
    )
    db = _db_mock(
        sources=[src], study_by_source_id={src.id: _study_with(doc)}
    )

    out = await load_schema_context_chunks(db, source_ids=[str(src.id)])

    assert len(out) == 1
    chunk = out[0]
    assert chunk["source_id"] == str(src.id)
    # The rendered text actually contains the schema — this is the property
    # that fixes FX37.  An empty / generic synthesizer prompt would not.
    text = chunk["text"]
    assert "cctp = customer-care-tracking-platform" in text
    assert "public.tickets" in text
    assert "public.agents" in text


@pytest.mark.asyncio
async def test_helper_swallows_invalid_schema_json() -> None:
    src = _make_db_source()
    bad_study = MagicMock()
    # ``schema_document_json`` is non-null but the shape is bogus.
    bad_study.schema_document_json = {"this": "is not a SchemaDocument"}
    bad_study.finished_at = datetime.now(tz=timezone.utc)
    db = _db_mock(sources=[src], study_by_source_id={src.id: bad_study})

    out = await load_schema_context_chunks(db, source_ids=[str(src.id)])

    assert out == []


@pytest.mark.asyncio
async def test_helper_swallows_db_failure() -> None:
    db = MagicMock()
    db.execute = AsyncMock(side_effect=RuntimeError("network down"))

    out = await load_schema_context_chunks(
        db, source_ids=[str(uuid.uuid4())]
    )

    assert out == []


# ---------------------------------------------------------------------------
# Integration with the prompt template — schema chunk drives the synthesizer
# ---------------------------------------------------------------------------


def test_rendered_chunk_text_flows_through_render_system_prompt() -> None:
    """Defence-in-depth: the chunk shape we emit MUST be readable by the
    synthesizer's prompt template.  If render_system_prompt ever stops
    rendering ``text`` for chunks with score=0.0 this test catches it.
    """
    from src.agent.prompts import render_system_prompt

    source = _make_db_source(name="finance-warehouse")
    doc = _make_doc(
        summary="Q3 financial roll-ups for the consolidated ledger.",
        tables=[_make_table("dwh.journal_entries", pk=["entry_id"])],
    )
    chunk = _build_chunk_dict(source, _render_chunk_text(source, doc))
    prompt = render_system_prompt([chunk])

    assert "finance-warehouse" in prompt
    assert "Q3 financial roll-ups" in prompt
    assert "dwh.journal_entries" in prompt
    # And it's NOT the empty-context branch.
    assert "(No relevant context found)" not in prompt
