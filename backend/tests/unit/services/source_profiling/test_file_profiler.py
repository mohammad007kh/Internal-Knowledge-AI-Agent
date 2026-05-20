"""Tests for FileSourceProfiler.

The profiler queries Documents + Chunks via SQLAlchemy ``execute()`` calls
and makes a single LLM call. We mock the AsyncSession so each test controls
what the two queries (documents, then per-doc chunks) return, and stub the
AIModelResolver / Langfuse pair the same way ``test_source_router_node``
does.
"""

from __future__ import annotations

import json
import uuid
from typing import Any
from unittest.mock import AsyncMock, MagicMock

import pytest

from src.models.enums import SourceType
from src.models.source import Source
from src.services.ai_model_resolver import AIModelClient
from src.services.source_profiling.file_profiler import (
    FileProfilerError,
    FileSourceProfiler,
)

pytestmark = pytest.mark.asyncio


# ---------------------------------------------------------------------------
# Builders
# ---------------------------------------------------------------------------


def _make_source(source_type: SourceType = SourceType.FILE_UPLOAD) -> Source:
    s = Source(
        name="onboarding-pdfs",
        source_type=source_type,
        owner_id=uuid.uuid4(),
        is_active=True,
    )
    s.id = uuid.uuid4()
    return s


def _make_document(
    *,
    original_name: str | None = "policy.pdf",
    storage_path: str | None = "minio://kb/abc/policy.pdf",
) -> MagicMock:
    """Return a MagicMock that quacks like a :class:`Document` ORM row."""
    doc = MagicMock()
    doc.id = uuid.uuid4()
    doc.metadata_ = {"original_name": original_name} if original_name else {}
    doc.raw_storage_path = storage_path
    return doc


def _make_chunk(text: str, index: int = 0) -> MagicMock:
    """Return a MagicMock that quacks like a :class:`Chunk` ORM row."""
    c = MagicMock()
    c.id = uuid.uuid4()
    c.chunk_text = text
    c.chunk_index = index
    return c


def _scalar_result(items: list[Any]) -> MagicMock:
    """Build a SQLAlchemy ``Result`` mock whose ``.scalars().all()`` yields
    *items*. Mirrors the shape AsyncSession.execute() returns."""
    scalars = MagicMock()
    scalars.all = MagicMock(return_value=items)
    result = MagicMock()
    result.scalars = MagicMock(return_value=scalars)
    return result


def _mock_db_with_queries(*query_results: list[Any]) -> MagicMock:
    """An AsyncSession whose successive ``execute()`` calls return scalar
    results for each provided list — first call returns documents, then one
    chunk-list per document."""
    db = MagicMock()
    db.execute = AsyncMock(
        side_effect=[_scalar_result(r) for r in query_results]
    )
    return db


def _resolver_for(http_client: AsyncMock | MagicMock) -> AsyncMock:
    resolver = AsyncMock()
    resolver.resolve.return_value = AIModelClient(
        ai_model_id=uuid.uuid4(),
        provider="openai",
        model_id="gpt-4o-mini",
        temperature=0.0,
        max_tokens=512,
        custom_prompt=None,
        capabilities={},
        http_client=http_client,
    )
    return resolver


def _openai_returning(payload: dict[str, Any]) -> AsyncMock:
    client = AsyncMock()
    completion = MagicMock()
    completion.choices = [MagicMock()]
    completion.choices[0].message.content = json.dumps(payload)
    client.chat.completions.create.return_value = completion
    return client


def _openai_returning_raw(raw_content: str) -> AsyncMock:
    client = AsyncMock()
    completion = MagicMock()
    completion.choices = [MagicMock()]
    completion.choices[0].message.content = raw_content
    client.chat.completions.create.return_value = completion
    return client


def _langfuse_stub() -> MagicMock:
    lf = MagicMock()
    span = MagicMock()
    lf.span.return_value = span
    return lf


# ---------------------------------------------------------------------------
# Edge case: no documents — must NOT call the LLM
# ---------------------------------------------------------------------------


async def test_empty_source_short_circuits_without_llm_call() -> None:
    source = _make_source()
    db = _mock_db_with_queries([])  # documents query returns []

    resolver = _resolver_for(_openai_returning({}))
    profiler = FileSourceProfiler(
        ai_model_resolver=resolver,
        langfuse=_langfuse_stub(),
    )

    profile = await profiler.profile(source, db)

    assert profile.topics == []
    assert profile.entities == []
    assert profile.scope_exclusions == ""
    assert profile.coverage_summary.startswith("No content yet")
    assert profile.sample_count == 0
    assert profile.source_id == str(source.id)
    assert profile.source_type is SourceType.FILE_UPLOAD
    resolver.resolve.assert_not_called()


async def test_documents_present_but_zero_chunks_emits_empty_profile() -> None:
    source = _make_source()
    doc = _make_document()
    # First execute(): documents. Second: chunks (empty).
    db = _mock_db_with_queries([doc], [])

    resolver = _resolver_for(_openai_returning({}))
    profiler = FileSourceProfiler(
        ai_model_resolver=resolver,
        langfuse=_langfuse_stub(),
    )

    profile = await profiler.profile(source, db)

    assert profile.sample_count == 0
    assert profile.coverage_summary.startswith("No content yet")
    resolver.resolve.assert_not_called()


# ---------------------------------------------------------------------------
# Happy path
# ---------------------------------------------------------------------------


async def test_happy_path_returns_profile_with_llm_payload() -> None:
    source = _make_source()
    doc1 = _make_document(original_name="report-q1.pdf")
    doc2 = _make_document(original_name="notes.docx")

    chunks_doc1 = [_make_chunk(f"Chunk {i} of report-q1", i) for i in range(5)]
    chunks_doc2 = [_make_chunk(f"Notes line {i}", i) for i in range(2)]
    db = _mock_db_with_queries([doc1, doc2], chunks_doc1, chunks_doc2)

    payload = {
        "topics": ["quarterly reporting", "team notes"],
        "entities": ["Q1 2026", "Acme Corp"],
        "content_types": ["PDF reports", "DOCX notes"],
        "coverage_summary": "Quarterly business reports plus internal notes.",
        "scope_exclusions": "No HR records.",
    }
    http_client = _openai_returning(payload)
    resolver = _resolver_for(http_client)

    profiler = FileSourceProfiler(
        ai_model_resolver=resolver,
        langfuse=_langfuse_stub(),
    )
    profile = await profiler.profile(source, db)

    resolver.resolve.assert_awaited_once_with("source_profiler")
    http_client.chat.completions.create.assert_awaited_once()

    assert profile.topics == ["quarterly reporting", "team notes"]
    assert profile.entities == ["Q1 2026", "Acme Corp"]
    assert profile.content_types == ["PDF reports", "DOCX notes"]
    assert profile.coverage_summary == (
        "Quarterly business reports plus internal notes."
    )
    assert profile.scope_exclusions == "No HR records."
    # 3 chunks from doc1 (head/middle/tail) + 2 chunks from doc2 (≤ 3) = 5.
    assert profile.sample_count == 5
    assert profile.source_id == str(source.id)


async def test_happy_path_passes_metadata_and_samples_to_llm() -> None:
    source = _make_source()
    doc = _make_document(original_name="manual.pdf")
    chunks = [_make_chunk(f"manual page {i}", i) for i in range(10)]
    db = _mock_db_with_queries([doc], chunks)

    payload = {
        "topics": ["product manual"],
        "entities": [],
        "content_types": ["PDF"],
        "coverage_summary": "Product manual.",
        "scope_exclusions": "",
    }
    http_client = _openai_returning(payload)
    resolver = _resolver_for(http_client)

    await FileSourceProfiler(
        ai_model_resolver=resolver,
        langfuse=_langfuse_stub(),
    ).profile(source, db)

    call_kwargs = http_client.chat.completions.create.call_args.kwargs
    user_message = call_kwargs["messages"][1]["content"]
    sent_payload = json.loads(user_message)

    assert sent_payload["metadata"]["document_count"] == 1
    assert sent_payload["metadata"]["total_chunk_count"] == 10
    assert sent_payload["metadata"]["sample_count"] == 3
    assert "pdf" in sent_payload["metadata"]["file_extensions"]
    # response_format is the strict json_schema flavour.
    assert call_kwargs["response_format"]["type"] == "json_schema"


# ---------------------------------------------------------------------------
# Sampling strategy
# ---------------------------------------------------------------------------


async def test_sampling_picks_head_middle_tail_from_long_document() -> None:
    """For a document with 11 chunks, we expect indices 0, 5 and 10 to be
    the ones forwarded to the LLM."""
    source = _make_source()
    doc = _make_document()
    chunks = [_make_chunk(f"BODY-{i}", i) for i in range(11)]
    db = _mock_db_with_queries([doc], chunks)

    captured: dict[str, Any] = {}

    def _capture(**kwargs: Any) -> Any:
        captured.update(kwargs)
        completion = MagicMock()
        completion.choices = [MagicMock()]
        completion.choices[0].message.content = json.dumps(
            {
                "topics": [],
                "entities": [],
                "content_types": [],
                "coverage_summary": "",
                "scope_exclusions": "",
            }
        )
        return completion

    http_client = AsyncMock()
    http_client.chat.completions.create.side_effect = _capture
    resolver = _resolver_for(http_client)

    await FileSourceProfiler(
        ai_model_resolver=resolver,
        langfuse=_langfuse_stub(),
    ).profile(source, db)

    sent = json.loads(captured["messages"][1]["content"])
    samples = sent["samples"]
    assert len(samples) == 3
    # Order: head, middle, tail.
    assert samples[0].startswith("BODY-0")
    assert samples[1].startswith("BODY-5")
    assert samples[2].startswith("BODY-10")
    # Indices 1-4 and 6-9 must be absent.
    for idx in (1, 2, 3, 4, 6, 7, 8, 9):
        marker = f"BODY-{idx}"
        # ``BODY-1`` is a substring of ``BODY-10`` — guard with whitespace edges.
        assert all(marker != s.strip() for s in samples), (
            f"Unexpected chunk {marker} leaked into samples"
        )


async def test_sampling_keeps_short_documents_intact() -> None:
    """When a document only has 1 chunk we still send it (don't drop)."""
    source = _make_source()
    doc = _make_document()
    chunks = [_make_chunk("only chunk", 0)]
    db = _mock_db_with_queries([doc], chunks)

    payload = {
        "topics": [],
        "entities": [],
        "content_types": [],
        "coverage_summary": "single-chunk source",
        "scope_exclusions": "",
    }
    http_client = _openai_returning(payload)

    profile = await FileSourceProfiler(
        ai_model_resolver=_resolver_for(http_client),
        langfuse=_langfuse_stub(),
    ).profile(source, db)

    assert profile.sample_count == 1


# ---------------------------------------------------------------------------
# MinIO path stripping
# ---------------------------------------------------------------------------


async def test_minio_paths_are_stripped_before_sending_to_llm() -> None:
    source = _make_source()
    doc = _make_document()
    chunks = [
        _make_chunk(
            "Onboarding from minio://kb/abc/intro.pdf and "
            "s3://internal/raw/foo.txt as well as /var/data/secret.csv "
            "should not leak.",
            0,
        ),
    ]
    db = _mock_db_with_queries([doc], chunks)

    captured: dict[str, Any] = {}

    def _capture(**kwargs: Any) -> Any:
        captured.update(kwargs)
        completion = MagicMock()
        completion.choices = [MagicMock()]
        completion.choices[0].message.content = json.dumps(
            {
                "topics": [],
                "entities": [],
                "content_types": [],
                "coverage_summary": "",
                "scope_exclusions": "",
            }
        )
        return completion

    http_client = AsyncMock()
    http_client.chat.completions.create.side_effect = _capture

    await FileSourceProfiler(
        ai_model_resolver=_resolver_for(http_client),
        langfuse=_langfuse_stub(),
    ).profile(source, db)

    sent = json.loads(captured["messages"][1]["content"])
    sample_text = sent["samples"][0]
    # All forms of internal path should be gone.
    assert "minio://" not in sample_text
    assert "s3://" not in sample_text
    assert "/var/data/secret.csv" not in sample_text
    # The surrounding sentence should still be readable.
    assert "Onboarding" in sample_text
    assert "should not leak" in sample_text


# ---------------------------------------------------------------------------
# Error paths
# ---------------------------------------------------------------------------


async def test_malformed_llm_json_raises_file_profiler_error() -> None:
    source = _make_source()
    doc = _make_document()
    chunks = [_make_chunk("any text", 0)]
    db = _mock_db_with_queries([doc], chunks)

    http_client = _openai_returning_raw("not-json-at-all")
    resolver = _resolver_for(http_client)

    profiler = FileSourceProfiler(
        ai_model_resolver=resolver,
        langfuse=_langfuse_stub(),
    )

    with pytest.raises(FileProfilerError, match="non-JSON"):
        await profiler.profile(source, db)


async def test_payload_failing_strict_validation_raises() -> None:
    source = _make_source()
    doc = _make_document()
    chunks = [_make_chunk("any text", 0)]
    db = _mock_db_with_queries([doc], chunks)

    # Extra fields rejected by ``extra='forbid'`` on _LLMProfilePayload.
    bad_payload = {
        "topics": [],
        "entities": [],
        "content_types": [],
        "coverage_summary": "",
        "scope_exclusions": "",
        "definitely_not_in_schema": True,
    }
    http_client = _openai_returning(bad_payload)

    profiler = FileSourceProfiler(
        ai_model_resolver=_resolver_for(http_client),
        langfuse=_langfuse_stub(),
    )

    with pytest.raises(FileProfilerError, match="malformed payload"):
        await profiler.profile(source, db)


async def test_llm_call_exception_wrapped_in_file_profiler_error() -> None:
    source = _make_source()
    doc = _make_document()
    chunks = [_make_chunk("hello", 0)]
    db = _mock_db_with_queries([doc], chunks)

    failing = AsyncMock()
    failing.chat.completions.create.side_effect = RuntimeError("boom")
    resolver = _resolver_for(failing)

    profiler = FileSourceProfiler(
        ai_model_resolver=resolver,
        langfuse=_langfuse_stub(),
    )

    with pytest.raises(FileProfilerError, match="LLM call failed"):
        await profiler.profile(source, db)


# ---------------------------------------------------------------------------
# Source-type coverage
# ---------------------------------------------------------------------------


async def test_handles_web_url_source_type() -> None:
    """FILE_UPLOAD and WEB_URL collapse to the same profiler."""
    assert SourceType.WEB_URL in FileSourceProfiler.source_types
    assert SourceType.FILE_UPLOAD in FileSourceProfiler.source_types

    source = _make_source(source_type=SourceType.WEB_URL)
    doc = _make_document(original_name="docs.acme.com/index.html")
    chunks = [_make_chunk("Welcome to Acme docs", 0)]
    db = _mock_db_with_queries([doc], chunks)

    payload = {
        "topics": ["docs"],
        "entities": ["Acme"],
        "content_types": ["web pages"],
        "coverage_summary": "Acme documentation site.",
        "scope_exclusions": "",
    }
    http_client = _openai_returning(payload)

    profile = await FileSourceProfiler(
        ai_model_resolver=_resolver_for(http_client),
        langfuse=_langfuse_stub(),
    ).profile(source, db)

    assert profile.source_type is SourceType.WEB_URL
    assert profile.topics == ["docs"]
