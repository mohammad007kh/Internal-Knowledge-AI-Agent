"""Tests for DatabaseSourceProfiler.

The profiler is a pure projector — given a SchemaDocument it produces a
SourceProfile. We mock the DB session so we don't need a real Postgres.
"""

from __future__ import annotations

import uuid
from datetime import datetime, timezone
from unittest.mock import AsyncMock, MagicMock

import pytest

from src.models.enums import SourceType
from src.models.source import Source
from src.services.db_introspection.schema_doc import (
    ColumnDoc,
    PhaseError,
    Relationship,
    SchemaDocument,
    TableDoc,
)
from src.services.source_profiling.database_profiler import DatabaseSourceProfiler

pytestmark = pytest.mark.asyncio


def _make_source() -> Source:
    s = Source(
        name="prod-db",
        source_type=SourceType.DATABASE,
        owner_id=uuid.uuid4(),
        is_active=True,
    )
    s.id = uuid.uuid4()
    return s


def _make_doc(
    *,
    tables: list[TableDoc] | None = None,
    summary: str = "",
    partial: bool = False,
    phase_errors: list[PhaseError] | None = None,
    dialect: str = "postgresql",
) -> SchemaDocument:
    return SchemaDocument(
        dialect=dialect,  # type: ignore[arg-type]
        fingerprint="x" * 64,
        generated_at=datetime.now(tz=timezone.utc),
        agent_version="1.0.0",
        study_duration_ms=1234,
        partial=partial,
        phase_errors=phase_errors or [],
        tables=tables or [],
        summary=summary,
    )


def _make_table(
    name: str,
    *,
    kind: str = "table",
    tags: list[str] | None = None,
    rows: int | None = None,
    description: str = "",
    has_fk: bool = False,
) -> TableDoc:
    rels = (
        [Relationship(from_columns=["a"], to_table="other", to_columns=["b"], kind="foreign_key")]
        if has_fk
        else []
    )
    return TableDoc(
        name=name,
        kind=kind,  # type: ignore[arg-type]
        row_count_estimate=rows,
        primary_key=["id"],
        indexes=[],
        columns=[ColumnDoc(name="id", type="int", native_type="integer")],
        relationships=rels,
        description=description,
        tags=tags or [],
    )


def _mock_db_returning_study(study) -> AsyncMock:
    """Build an AsyncSession.execute mock that returns *study* from
    .scalar_one_or_none()."""
    db = MagicMock()
    result = MagicMock()
    result.scalar_one_or_none = MagicMock(return_value=study)
    db.execute = AsyncMock(return_value=result)
    return db


# ---------------------------------------------------------------------------
# Empty / fallback paths
# ---------------------------------------------------------------------------


async def test_returns_empty_profile_when_no_study() -> None:
    profiler = DatabaseSourceProfiler()
    db = _mock_db_returning_study(None)

    profile = await profiler.profile(_make_source(), db)

    assert profile.topics == []
    assert profile.entities == []
    assert profile.coverage_summary.startswith("Database source")
    assert profile.sample_count == 0
    assert profile.content_types == ["database tables"]


async def test_returns_empty_profile_when_schema_document_json_invalid() -> None:
    profiler = DatabaseSourceProfiler()
    bad_study = MagicMock()
    bad_study.schema_document_json = {"this": "isn't a SchemaDocument"}
    db = _mock_db_returning_study(bad_study)

    profile = await profiler.profile(_make_source(), db)

    assert profile.topics == []
    # Still produces a profile rather than blowing up the caller.
    assert profile.coverage_summary != ""


# ---------------------------------------------------------------------------
# Happy-path projection
# ---------------------------------------------------------------------------


async def test_topics_pulled_from_table_tags() -> None:
    profiler = DatabaseSourceProfiler()
    doc = _make_doc(
        tables=[
            _make_table("public.orders", tags=["transactional"]),
            _make_table("public.audit_events", tags=["audit_log"]),
            _make_table("public.users", tags=["transactional"]),  # duplicate tag
        ],
    )
    study = MagicMock()
    study.schema_document_json = doc.model_dump(mode="json")
    db = _mock_db_returning_study(study)

    profile = await profiler.profile(_make_source(), db)

    # Tags first, deduped, in insertion order.
    assert profile.topics[:2] == ["transactional", "audit_log"]


async def test_topics_falls_back_to_table_names_sorted_by_row_count() -> None:
    profiler = DatabaseSourceProfiler()
    doc = _make_doc(
        tables=[
            _make_table("public.tiny", rows=5),
            _make_table("public.huge", rows=10_000_000),
            _make_table("public.medium", rows=1_000),
        ],
    )
    study = MagicMock()
    study.schema_document_json = doc.model_dump(mode="json")
    db = _mock_db_returning_study(study)

    profile = await profiler.profile(_make_source(), db)

    # No tags, so falls back to table names sorted by row count desc.
    assert profile.topics == ["huge", "medium", "tiny"]


async def test_entities_are_fully_qualified_table_names() -> None:
    profiler = DatabaseSourceProfiler()
    doc = _make_doc(
        tables=[
            _make_table("public.orders"),
            _make_table("public.customers"),
        ],
    )
    study = MagicMock()
    study.schema_document_json = doc.model_dump(mode="json")
    db = _mock_db_returning_study(study)

    profile = await profiler.profile(_make_source(), db)

    assert profile.entities == ["public.orders", "public.customers"]


async def test_content_types_reflect_relations_present() -> None:
    profiler = DatabaseSourceProfiler()
    doc = _make_doc(
        tables=[
            _make_table("public.t1", has_fk=True),
            _make_table("public.v1", kind="view"),
        ],
        dialect="postgresql",
    )
    study = MagicMock()
    study.schema_document_json = doc.model_dump(mode="json")
    db = _mock_db_returning_study(study)

    profile = await profiler.profile(_make_source(), db)

    assert "postgresql database" in profile.content_types
    assert "views" in profile.content_types
    assert "relational tables" in profile.content_types


async def test_coverage_summary_uses_doc_summary_when_present() -> None:
    profiler = DatabaseSourceProfiler()
    doc = _make_doc(
        tables=[_make_table("public.x")],
        summary="This is the corpus summary written by the studying agent.",
    )
    study = MagicMock()
    study.schema_document_json = doc.model_dump(mode="json")
    db = _mock_db_returning_study(study)

    profile = await profiler.profile(_make_source(), db)

    assert profile.coverage_summary.startswith("This is the corpus summary")


async def test_coverage_summary_synthesises_when_doc_summary_empty() -> None:
    profiler = DatabaseSourceProfiler()
    doc = _make_doc(
        tables=[
            _make_table("public.a", description="users"),
            _make_table("public.b"),
        ],
    )
    study = MagicMock()
    study.schema_document_json = doc.model_dump(mode="json")
    db = _mock_db_returning_study(study)

    profile = await profiler.profile(_make_source(), db)

    assert "2 documented" in profile.coverage_summary
    assert "1 with table-level descriptions" in profile.coverage_summary


async def test_scope_exclusions_set_when_partial() -> None:
    profiler = DatabaseSourceProfiler()
    doc = _make_doc(
        tables=[_make_table("public.x")],
        partial=True,
        phase_errors=[
            PhaseError(phase="DESCRIBING", error_key="LLM_TIMEOUT", message="x"),
        ],
    )
    study = MagicMock()
    study.schema_document_json = doc.model_dump(mode="json")
    db = _mock_db_returning_study(study)

    profile = await profiler.profile(_make_source(), db)

    assert "DESCRIBING" in profile.scope_exclusions
    assert "Partial" in profile.scope_exclusions


async def test_scope_exclusions_set_when_truncated() -> None:
    profiler = DatabaseSourceProfiler()
    # 35 tables — past the _MAX_TABLES_FOR_SUMMARY cap of 30.
    doc = _make_doc(
        tables=[_make_table(f"public.t{i}") for i in range(35)],
    )
    study = MagicMock()
    study.schema_document_json = doc.model_dump(mode="json")
    db = _mock_db_returning_study(study)

    profile = await profiler.profile(_make_source(), db)

    assert "5 additional tables" in profile.scope_exclusions


async def test_sample_count_reflects_tables_examined() -> None:
    profiler = DatabaseSourceProfiler()
    doc = _make_doc(tables=[_make_table(f"public.t{i}") for i in range(10)])
    study = MagicMock()
    study.schema_document_json = doc.model_dump(mode="json")
    db = _mock_db_returning_study(study)

    profile = await profiler.profile(_make_source(), db)

    assert profile.sample_count == 10
