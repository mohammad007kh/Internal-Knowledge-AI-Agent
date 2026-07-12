"""Unit tests for T-024 — source-intent prompt wiring.

Covers the three existing consumers of ``source.description`` plus the shared
pure render helpers:

* ``_intent_render.render_intent_block`` — ramp tiers + delimiters + directive.
* ``_schema_context._render_chunk_text`` — intent renders ABOVE the schema
  block inside the pinned chunk (FR-004 / survives ``_MAX_TABLES`` truncation).
* ``source_router._load_catalog`` — per-source intent + tiered out_of_scope
  authority (advisory at ``ai_set``, hard-decline-capable at ``user_set``).
* ``text_to_query._description_fallback`` — purpose precedence over bare
  description in the schema-sketch fallback.

Security rule 1: intent fields render inside ``<source_purpose>`` /
``<example_questions>`` / ``<out_of_scope_topics>`` delimiters with a
treat-as-data directive — asserted directly here.

Pure-async unit coverage: no live DB, no live LLM.
"""

from __future__ import annotations

import os
import uuid
from datetime import UTC, datetime
from unittest.mock import AsyncMock, MagicMock

# Env-var preamble required before ``src.*`` imports load core.config.
os.environ.setdefault("DATABASE_URL", "postgresql+asyncpg://test:test@localhost/test")
os.environ.setdefault("JWT_SECRET_KEY", "test-jwt-secret-key-at-least-32-chars-long!!")
os.environ.setdefault("JWT_REFRESH_SECRET_KEY", "test-jwt-refresh-secret-key-32-chars!!")
os.environ.setdefault("MINIO_ENDPOINT", "localhost:9000")
os.environ.setdefault("MINIO_ACCESS_KEY", "testaccess")
os.environ.setdefault("MINIO_SECRET_KEY", "testsecret")
os.environ.setdefault("ENCRYPTION_KEY", "dGVzdGVuY3J5cHRpb25rZXkxMjM0NTY3ODk=")

import pytest  # noqa: E402

from src.agent.nodes import _intent_render as ir  # noqa: E402
from src.agent.nodes._intent_render import (  # noqa: E402
    EXAMPLES_CLOSE,
    EXAMPLES_OPEN,
    OUT_OF_SCOPE_CLOSE,
    OUT_OF_SCOPE_OPEN,
    PURPOSE_CLOSE,
    PURPOSE_OPEN,
    TREAT_AS_DATA_DIRECTIVE,
    out_of_scope_has_authority,
    render_intent_block,
    render_router_intent,
)
from src.agent.nodes._schema_context import _render_chunk_text  # noqa: E402
from src.agent.nodes.source_router import _load_catalog  # noqa: E402
from src.agent.nodes.text_to_query import _description_fallback  # noqa: E402
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

_PURPOSE = "Answers questions about customer billing and invoices."
_EXAMPLES = ["How much did customer X owe?", "List unpaid invoices."]
_OUT_OF_SCOPE = ["HR / payroll questions", "Marketing analytics"]


def _make_db_source(
    *,
    name: str = "billing-db",
    purpose: str | None = _PURPOSE,
    example_questions: list[str] | None = None,
    out_of_scope: list[str] | None = None,
    intent_status: str = "ai_set",
    description: str | None = "bare freeform description",
) -> Source:
    s = Source(
        name=name,
        source_type=SourceType.DATABASE,
        owner_id=uuid.uuid4(),
        is_active=True,
    )
    s.id = uuid.uuid4()
    s.description = description
    s.purpose = purpose
    s.example_questions = (
        example_questions if example_questions is not None else list(_EXAMPLES)
    )
    s.out_of_scope = (
        out_of_scope if out_of_scope is not None else list(_OUT_OF_SCOPE)
    )
    s.intent_status = intent_status
    return s


def _make_doc(*, tables: list[TableDoc] | None = None) -> SchemaDocument:
    return SchemaDocument(
        dialect="postgresql",  # type: ignore[arg-type]
        fingerprint="x" * 64,
        generated_at=datetime.now(tz=UTC),
        agent_version="1.0.0",
        study_duration_ms=1,
        partial=False,
        phase_errors=[],
        tables=tables or [],
        summary="Billing data store.",
    )


def _make_table(name: str) -> TableDoc:
    return TableDoc(
        name=name,
        kind="table",
        primary_key=["id"],
        indexes=[],
        columns=[ColumnDoc(name="id", type="int", native_type="int")],  # type: ignore[arg-type]
        relationships=[],
        description="",
        tags=[],
    )


# ---------------------------------------------------------------------------
# render_intent_block — delimiters + treat-as-data directive (security rule 1)
# ---------------------------------------------------------------------------


def test_intent_block_wraps_every_field_in_its_delimiter() -> None:
    block = render_intent_block(
        purpose=_PURPOSE,
        example_questions=_EXAMPLES,
        out_of_scope=_OUT_OF_SCOPE,
        intent_status="ai_set",
    )
    assert PURPOSE_OPEN in block and PURPOSE_CLOSE in block
    assert EXAMPLES_OPEN in block and EXAMPLES_CLOSE in block
    assert OUT_OF_SCOPE_OPEN in block and OUT_OF_SCOPE_CLOSE in block
    # Each value lives strictly inside its delimiters.
    assert _PURPOSE in block
    assert _EXAMPLES[0] in block
    assert _OUT_OF_SCOPE[0] in block


def test_intent_block_includes_treat_as_data_directive() -> None:
    block = render_intent_block(
        purpose=_PURPOSE,
        example_questions=_EXAMPLES,
        out_of_scope=_OUT_OF_SCOPE,
        intent_status="ai_set",
    )
    assert TREAT_AS_DATA_DIRECTIVE in block
    # Directive precedes the delimited content (frames it as data first).
    assert block.index(TREAT_AS_DATA_DIRECTIVE) < block.index(PURPOSE_OPEN)


def test_intent_block_empty_when_nothing_authored() -> None:
    assert (
        render_intent_block(
            purpose=None,
            example_questions=None,
            out_of_scope=None,
            intent_status="ai_set",
        )
        == ""
    )


def test_intent_block_ignores_blank_and_non_string_list_entries() -> None:
    block = render_intent_block(
        purpose="   ",  # blank -> dropped
        example_questions=["", "  ", 123, "real question"],  # only last survives
        out_of_scope=[None, "real topic"],
        intent_status="ai_set",
    )
    # Blank purpose dropped -> no purpose delimiter.
    assert PURPOSE_OPEN not in block
    assert "real question" in block
    assert "123" not in block
    assert "real topic" in block


# ---------------------------------------------------------------------------
# render_intent_block — capability ramp tiers
# ---------------------------------------------------------------------------


def test_ramp_pending_ai_suppresses_examples_and_out_of_scope() -> None:
    """pending_ai: purpose-only; examples + out_of_scope suppressed."""
    block = render_intent_block(
        purpose=_PURPOSE,
        example_questions=_EXAMPLES,
        out_of_scope=_OUT_OF_SCOPE,
        intent_status="pending_ai",
    )
    assert PURPOSE_OPEN in block
    assert EXAMPLES_OPEN not in block
    assert OUT_OF_SCOPE_OPEN not in block


def test_ramp_pending_ai_empty_when_no_purpose() -> None:
    assert (
        render_intent_block(
            purpose=None,
            example_questions=_EXAMPLES,
            out_of_scope=_OUT_OF_SCOPE,
            intent_status="pending_ai",
        )
        == ""
    )


def test_ramp_ai_set_renders_out_of_scope_advisory() -> None:
    block = render_intent_block(
        purpose=_PURPOSE,
        example_questions=_EXAMPLES,
        out_of_scope=_OUT_OF_SCOPE,
        intent_status="ai_set",
    )
    assert OUT_OF_SCOPE_OPEN in block
    # ...but at ai_set out_of_scope is NOT authoritative (advisory only).
    assert out_of_scope_has_authority("ai_set") is False


def test_ramp_user_set_grants_out_of_scope_authority() -> None:
    assert out_of_scope_has_authority("user_set") is True


@pytest.mark.parametrize("status", ["pending_ai", "ai_set", "", None, "garbage"])
def test_only_user_set_has_out_of_scope_authority(status) -> None:  # noqa: ANN001
    assert out_of_scope_has_authority(status) is False


# ---------------------------------------------------------------------------
# render_router_intent — ~150 token / ~600 char cap
# ---------------------------------------------------------------------------


def test_router_intent_capped_to_budget() -> None:
    long_purpose = "word " * 500  # ~2500 chars
    block = render_router_intent(
        purpose=long_purpose,
        example_questions=None,
        out_of_scope=None,
        intent_status="ai_set",
    )
    assert len(block) <= ir._ROUTER_INTENT_CHAR_CAP
    assert "(truncated)" in block


# ---------------------------------------------------------------------------
# _schema_context._render_chunk_text — intent ABOVE schema (FR-004)
# ---------------------------------------------------------------------------


def test_schema_chunk_renders_intent_above_schema() -> None:
    source = _make_db_source(intent_status="ai_set")
    doc = _make_doc(tables=[_make_table("public.invoices")])
    text = _render_chunk_text(source, doc)

    # Purpose delimiter must precede the "Database source:" schema header AND
    # the per-table render — this is what survives _MAX_TABLES truncation.
    assert text.index(PURPOSE_OPEN) < text.index("Database source:")
    assert text.index(PURPOSE_OPEN) < text.index("public.invoices")
    # Intent fields wrapped + directive present.
    assert TREAT_AS_DATA_DIRECTIVE in text
    assert _PURPOSE in text


def test_schema_chunk_intent_survives_empty_table_set() -> None:
    """The no-tables early-return path still carries the intent block."""
    source = _make_db_source(intent_status="ai_set")
    doc = _make_doc(tables=[])
    text = _render_chunk_text(source, doc)
    assert PURPOSE_OPEN in text
    assert text.index(PURPOSE_OPEN) < text.index("Database source:")


def test_schema_chunk_without_intent_renders_schema_only() -> None:
    source = _make_db_source(
        purpose=None, example_questions=[], out_of_scope=[], intent_status="ai_set"
    )
    doc = _make_doc(tables=[_make_table("public.invoices")])
    text = _render_chunk_text(source, doc)
    assert PURPOSE_OPEN not in text
    assert text.startswith("Database source:")


# ---------------------------------------------------------------------------
# source_router._load_catalog — intent + tiered out_of_scope authority
# ---------------------------------------------------------------------------


def _catalog_repo(sources: list) -> AsyncMock:
    repo = AsyncMock()
    repo.list_by_ids.return_value = sources
    return repo


@pytest.mark.asyncio
async def test_router_catalog_includes_delimited_intent() -> None:
    src = _make_db_source(intent_status="ai_set")
    catalog = await _load_catalog(
        db_session=MagicMock(),
        source_repository=_catalog_repo([src]),
        source_ids=[str(src.id)],
    )
    assert len(catalog) == 1
    entry = catalog[0]
    assert PURPOSE_OPEN in entry["intent"]
    assert OUT_OF_SCOPE_OPEN in entry["intent"]
    assert TREAT_AS_DATA_DIRECTIVE in entry["intent"]


@pytest.mark.asyncio
async def test_router_catalog_ai_set_out_of_scope_is_advisory() -> None:
    """ai_set: out_of_scope renders but carries NO hard-decline authority.

    The source stays a candidate (down-rank only) — the authority flag the
    routing prompt keys on is explicitly False.
    """
    src = _make_db_source(intent_status="ai_set")
    catalog = await _load_catalog(
        db_session=MagicMock(),
        source_repository=_catalog_repo([src]),
        source_ids=[str(src.id)],
    )
    entry = catalog[0]
    assert entry["out_of_scope_authoritative"] is False
    # out_of_scope topics ARE present (advisory signal), just not authoritative.
    assert OUT_OF_SCOPE_OPEN in entry["intent"]


@pytest.mark.asyncio
async def test_router_catalog_user_set_enables_hard_decline() -> None:
    src = _make_db_source(intent_status="user_set")
    catalog = await _load_catalog(
        db_session=MagicMock(),
        source_repository=_catalog_repo([src]),
        source_ids=[str(src.id)],
    )
    entry = catalog[0]
    assert entry["out_of_scope_authoritative"] is True


@pytest.mark.asyncio
async def test_router_catalog_pending_ai_no_authority() -> None:
    src = _make_db_source(intent_status="pending_ai")
    catalog = await _load_catalog(
        db_session=MagicMock(),
        source_repository=_catalog_repo([src]),
        source_ids=[str(src.id)],
    )
    entry = catalog[0]
    assert entry["out_of_scope_authoritative"] is False
    # pending_ai suppresses out_of_scope rendering entirely.
    assert OUT_OF_SCOPE_OPEN not in entry["intent"]


@pytest.mark.asyncio
async def test_router_catalog_fallback_shape_on_repo_error() -> None:
    """Repo blows up -> id-only fallback still carries the new keys."""
    repo = AsyncMock()
    repo.list_by_ids.side_effect = RuntimeError("db down")
    sid = str(uuid.uuid4())
    catalog = await _load_catalog(
        db_session=MagicMock(),
        source_repository=repo,
        source_ids=[sid],
    )
    assert catalog == [
        {
            "id": sid,
            "name": sid,
            "type": "unknown",
            "description": "",
            "intent": "",
            "out_of_scope_authoritative": False,
        }
    ]


# ---------------------------------------------------------------------------
# text_to_query._description_fallback — purpose precedence
# ---------------------------------------------------------------------------


def test_fallback_purpose_takes_precedence_over_description() -> None:
    src = _make_db_source(intent_status="ai_set", description="bare desc")
    out = _description_fallback(src)
    # Intent block leads; bare description trails.
    assert out.index(PURPOSE_OPEN) < out.index("bare desc")
    assert TREAT_AS_DATA_DIRECTIVE in out


def test_fallback_uses_bare_description_when_no_intent() -> None:
    src = _make_db_source(
        purpose=None,
        example_questions=[],
        out_of_scope=[],
        intent_status="ai_set",
        description="only the bare description",
    )
    out = _description_fallback(src)
    assert out == "only the bare description"


def test_fallback_intent_only_when_no_description() -> None:
    src = _make_db_source(intent_status="ai_set", description=None)
    out = _description_fallback(src)
    assert PURPOSE_OPEN in out
    assert out.endswith(PURPOSE_CLOSE) or OUT_OF_SCOPE_CLOSE in out


def test_fallback_empty_when_neither_present() -> None:
    src = _make_db_source(
        purpose=None,
        example_questions=[],
        out_of_scope=[],
        intent_status="ai_set",
        description=None,
    )
    assert _description_fallback(src) == ""
