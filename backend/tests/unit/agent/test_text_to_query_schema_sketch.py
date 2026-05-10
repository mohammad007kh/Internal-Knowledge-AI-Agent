"""Tests for text_to_query's schema-sketch loader.

Covers the F-Z (#133) work: text_to_query now feeds the LLM the studying
agent's persisted SchemaDocument as the schema sketch, falling back to
``source.description`` only when no study has completed.
"""

from __future__ import annotations

import uuid
from datetime import datetime, timezone
from unittest.mock import AsyncMock, MagicMock

import pytest

from src.agent.nodes.text_to_query import _load_schema_sketch, _render_schema_sketch
from src.models.enums import SourceType
from src.models.source import Source
from src.services.db_introspection.schema_doc import (
    ColumnDoc,
    Relationship,
    SchemaDocument,
    TableDoc,
)

# asyncio mark is applied per-test (not module-wide) because half of these
# are sync renderer tests; pytest-asyncio warns when sync tests carry the mark.


def _make_source(description: str | None = None) -> Source:
    s = Source(
        name="orders-db",
        source_type=SourceType.DATABASE,
        owner_id=uuid.uuid4(),
        is_active=True,
    )
    s.id = uuid.uuid4()
    s.description = description
    return s


def _make_doc(
    *, tables: list[TableDoc] | None = None, dialect: str = "postgresql"
) -> SchemaDocument:
    return SchemaDocument(
        dialect=dialect,  # type: ignore[arg-type]
        fingerprint="x" * 64,
        generated_at=datetime.now(tz=timezone.utc),
        agent_version="1.0.0",
        study_duration_ms=42,
        partial=False,
        phase_errors=[],
        tables=tables or [],
        summary="",
    )


def _make_table(
    name: str,
    *,
    columns: list[tuple[str, str]] | None = None,
    pk: list[str] | None = None,
    description: str = "",
    fks: list[tuple[list[str], str, list[str]]] | None = None,
) -> TableDoc:
    cols = [
        ColumnDoc(name=n, type=t, native_type=t)  # type: ignore[arg-type]
        for n, t in (columns or [])
    ]
    rels = [
        Relationship(
            from_columns=fc, to_table=tt, to_columns=tc, kind="foreign_key"
        )
        for fc, tt, tc in (fks or [])
    ]
    return TableDoc(
        name=name,
        kind="table",
        primary_key=pk or [],
        indexes=[],
        columns=cols,
        relationships=rels,
        description=description,
        tags=[],
    )


def _mock_db_returning_study(study) -> object:
    db = MagicMock()
    result = MagicMock()
    result.scalar_one_or_none = MagicMock(return_value=study)
    db.execute = AsyncMock(return_value=result)
    return db


# ---------------------------------------------------------------------------
# _render_schema_sketch — the deterministic output shape
# ---------------------------------------------------------------------------


def test_render_includes_dialect_and_tables() -> None:
    doc = _make_doc(
        tables=[
            _make_table(
                "public.orders",
                columns=[("id", "int"), ("total", "float")],
                pk=["id"],
                description="Per-customer purchase orders.",
            ),
        ],
    )
    out = _render_schema_sketch(doc)
    assert "Dialect: postgresql" in out
    assert "public.orders" in out
    assert "PK=[id]" in out
    assert "columns: id:int, total:float" in out
    assert "description: Per-customer purchase orders." in out


def test_render_caps_columns_at_20_with_truncation_note() -> None:
    cols = [(f"c{i}", "int") for i in range(25)]
    doc = _make_doc(tables=[_make_table("t", columns=cols)])
    out = _render_schema_sketch(doc)
    assert "(+5 more)" in out


def test_render_emits_relationships_block() -> None:
    doc = _make_doc(
        tables=[
            _make_table(
                "orders",
                fks=[(["customer_id"], "customers", ["id"])],
            ),
            _make_table("customers"),
        ],
    )
    out = _render_schema_sketch(doc)
    assert "Relationships:" in out
    assert "orders.customer_id -> customers.id" in out


def test_render_omits_relationships_block_when_no_fks() -> None:
    doc = _make_doc(tables=[_make_table("orders")])
    out = _render_schema_sketch(doc)
    assert "Relationships:" not in out


def test_render_truncates_at_30_tables() -> None:
    doc = _make_doc(tables=[_make_table(f"t{i}") for i in range(35)])
    out = _render_schema_sketch(doc)
    assert "5 additional tables not shown" in out


# ---------------------------------------------------------------------------
# _load_schema_sketch — DB read + SchemaDocument validation
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_load_falls_back_to_description_when_no_study() -> None:
    source = _make_source(description="freeform description")
    db = _mock_db_returning_study(None)

    out = await _load_schema_sketch(db, source)

    assert out == "freeform description"


@pytest.mark.asyncio
async def test_load_falls_back_to_empty_when_no_study_and_no_description() -> None:
    source = _make_source(description=None)
    db = _mock_db_returning_study(None)

    out = await _load_schema_sketch(db, source)

    assert out == ""


@pytest.mark.asyncio
async def test_load_renders_schema_document_when_present() -> None:
    source = _make_source(description="freeform should be ignored")
    doc = _make_doc(tables=[_make_table("public.orders", columns=[("id", "int")])])
    study = MagicMock()
    study.schema_document_json = doc.model_dump(mode="json")
    db = _mock_db_returning_study(study)

    out = await _load_schema_sketch(db, source)

    assert "Dialect: postgresql" in out
    assert "public.orders" in out
    # Must NOT use the freeform description when a SchemaDocument is available.
    assert "freeform should be ignored" not in out


@pytest.mark.asyncio
async def test_load_falls_back_when_schema_document_invalid() -> None:
    source = _make_source(description="fallback description")
    bad_study = MagicMock()
    bad_study.schema_document_json = {"this": "is not a SchemaDocument"}
    db = _mock_db_returning_study(bad_study)

    out = await _load_schema_sketch(db, source)

    assert out == "fallback description"
