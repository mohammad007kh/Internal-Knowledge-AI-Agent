"""Tests for SourceNamingService.

The service makes a single LLM call: we mock the AIModelResolver and
its returned AsyncOpenAI HTTP client at the same level the F5
profilers' tests do (see ``test_file_profiler``). Langfuse is a thin
no-op stub.
"""

from __future__ import annotations

import json
import uuid
from typing import Any
from unittest.mock import AsyncMock, MagicMock

import pytest

from src.models.enums import SourceType
from src.services.ai_model_resolver import AIModelClient
from src.services.source_naming_service import (
    AINaming,
    SourceNamingError,
    SourceNamingService,
)
from src.services.source_profiling.protocol import SourceProfile

pytestmark = pytest.mark.asyncio


# ---------------------------------------------------------------------------
# Builders
# ---------------------------------------------------------------------------


def _make_profile(
    *,
    topics: list[str] | None = None,
    entities: list[str] | None = None,
    coverage_summary: str = "Folder of quarterly sales reports.",
    scope_exclusions: str = "No HR or payroll data.",
    source_type: SourceType = SourceType.FILE_UPLOAD,
) -> SourceProfile:
    return SourceProfile(
        source_id=str(uuid.uuid4()),
        source_type=source_type,
        topics=topics if topics is not None else ["sales reports", "Q4 numbers"],
        entities=entities if entities is not None else ["Acme Corp"],
        content_types=["PDF reports"],
        coverage_summary=coverage_summary,
        scope_exclusions=scope_exclusions,
        sample_count=5,
    )


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
# Happy path
# ---------------------------------------------------------------------------


async def test_happy_path_returns_naming_in_template_format() -> None:
    profile = _make_profile()
    payload = {
        "name": "Q4 Sales Reports",
        "summary": "Quarterly sales reporting bundle for FY2026",
        "topics": ["sales reports", "Q4 numbers", "deal pipeline"],
        "intent": "Q4 revenue, deal pipeline, account owners",
        "scope": "HR records or payroll information",
    }
    http_client = _openai_returning(payload)
    resolver = _resolver_for(http_client)

    service = SourceNamingService(
        ai_model_resolver=resolver,
        langfuse=_langfuse_stub(),
    )
    naming = await service.name_from_profile(profile)

    resolver.resolve.assert_awaited_once_with("source_autoname")
    http_client.chat.completions.create.assert_awaited_once()

    assert isinstance(naming, AINaming)
    assert naming.name == "Q4 Sales Reports"
    # Deterministic template — these markers must appear in this order.
    assert naming.description.startswith(
        "Quarterly sales reporting bundle for FY2026."
    )
    assert "Covers: sales reports, Q4 numbers, deal pipeline." in naming.description
    assert (
        "Useful for questions about Q4 revenue, deal pipeline, account owners."
        in naming.description
    )
    assert "Does not contain HR records or payroll information." in naming.description
    # Description sits inside the persistence-ready window.
    assert 50 <= len(naming.description) <= 400


async def test_happy_path_uses_strict_json_schema_response_format() -> None:
    profile = _make_profile()
    payload = {
        "name": "Sales Bundle",
        "summary": "Sales reports for FY2026",
        "topics": ["sales"],
        "intent": "sales numbers",
        "scope": "",
    }
    http_client = _openai_returning(payload)
    service = SourceNamingService(
        ai_model_resolver=_resolver_for(http_client),
        langfuse=_langfuse_stub(),
    )
    await service.name_from_profile(profile)

    call_kwargs = http_client.chat.completions.create.call_args.kwargs
    assert call_kwargs["response_format"]["type"] == "json_schema"
    assert (
        call_kwargs["response_format"]["json_schema"]["name"]
        == "source_autoname_payload"
    )
    assert call_kwargs["response_format"]["json_schema"]["strict"] is True


# ---------------------------------------------------------------------------
# Empty topics — service must forward the empty list, not synthesise topics
# ---------------------------------------------------------------------------


async def test_empty_topics_in_profile_are_passed_through_to_llm() -> None:
    profile = _make_profile(topics=[])
    payload = {
        "name": "Empty Source",
        "summary": "Source has been created but no content has landed yet.",
        "topics": [],
        "intent": "future ingested content",
        "scope": "",
    }
    http_client = _openai_returning(payload)
    service = SourceNamingService(
        ai_model_resolver=_resolver_for(http_client),
        langfuse=_langfuse_stub(),
    )
    await service.name_from_profile(profile)

    call_kwargs = http_client.chat.completions.create.call_args.kwargs
    user_message = call_kwargs["messages"][1]["content"]
    sent_payload = json.loads(user_message)
    # The service must not invent topics — empty stays empty.
    assert sent_payload["topics"] == []


# ---------------------------------------------------------------------------
# LLM error paths
# ---------------------------------------------------------------------------


async def test_invalid_json_raises_source_naming_error() -> None:
    profile = _make_profile()
    http_client = _openai_returning_raw("definitely not json")
    service = SourceNamingService(
        ai_model_resolver=_resolver_for(http_client),
        langfuse=_langfuse_stub(),
    )

    with pytest.raises(SourceNamingError, match="non-JSON"):
        await service.name_from_profile(profile)


async def test_payload_failing_strict_validation_raises() -> None:
    profile = _make_profile()
    bad_payload = {
        "name": "X",
        "summary": "valid",
        "topics": [],
        "intent": "stuff",
        "scope": "",
        "definitely_not_in_schema": True,
    }
    http_client = _openai_returning(bad_payload)
    service = SourceNamingService(
        ai_model_resolver=_resolver_for(http_client),
        langfuse=_langfuse_stub(),
    )

    with pytest.raises(SourceNamingError, match="malformed payload"):
        await service.name_from_profile(profile)


async def test_llm_call_exception_wrapped_in_source_naming_error() -> None:
    profile = _make_profile()
    failing = AsyncMock()
    failing.chat.completions.create.side_effect = RuntimeError("boom")
    service = SourceNamingService(
        ai_model_resolver=_resolver_for(failing),
        langfuse=_langfuse_stub(),
    )

    with pytest.raises(SourceNamingError, match="LLM call failed"):
        await service.name_from_profile(profile)


async def test_empty_content_raises() -> None:
    profile = _make_profile()
    http_client = _openai_returning_raw("")
    service = SourceNamingService(
        ai_model_resolver=_resolver_for(http_client),
        langfuse=_langfuse_stub(),
    )

    with pytest.raises(SourceNamingError, match="empty content"):
        await service.name_from_profile(profile)


# ---------------------------------------------------------------------------
# Name length validation
# ---------------------------------------------------------------------------


async def test_name_longer_than_60_chars_raises() -> None:
    profile = _make_profile()
    payload = {
        "name": "x" * 61,  # too long
        "summary": "valid summary",
        "topics": [],
        "intent": "things",
        "scope": "",
    }
    service = SourceNamingService(
        ai_model_resolver=_resolver_for(_openai_returning(payload)),
        langfuse=_langfuse_stub(),
    )

    with pytest.raises(SourceNamingError, match="61 chars"):
        await service.name_from_profile(profile)


async def test_name_shorter_than_3_chars_raises() -> None:
    profile = _make_profile()
    payload = {
        "name": "AB",  # too short
        "summary": "valid summary",
        "topics": [],
        "intent": "things",
        "scope": "",
    }
    service = SourceNamingService(
        ai_model_resolver=_resolver_for(_openai_returning(payload)),
        langfuse=_langfuse_stub(),
    )

    with pytest.raises(SourceNamingError, match="2 chars"):
        await service.name_from_profile(profile)


async def test_name_with_slash_raises() -> None:
    profile = _make_profile()
    payload = {
        "name": "Sales / Marketing",
        "summary": "valid summary",
        "topics": [],
        "intent": "things",
        "scope": "",
    }
    service = SourceNamingService(
        ai_model_resolver=_resolver_for(_openai_returning(payload)),
        langfuse=_langfuse_stub(),
    )

    with pytest.raises(SourceNamingError, match="slash"):
        await service.name_from_profile(profile)


# ---------------------------------------------------------------------------
# Description length / truncation
# ---------------------------------------------------------------------------


async def test_empty_summary_raises() -> None:
    profile = _make_profile()
    payload = {
        "name": "Some Source",
        "summary": "",
        "topics": ["x"],
        "intent": "y",
        "scope": "z",
    }
    service = SourceNamingService(
        ai_model_resolver=_resolver_for(_openai_returning(payload)),
        langfuse=_langfuse_stub(),
    )

    with pytest.raises(SourceNamingError, match="empty summary"):
        await service.name_from_profile(profile)


async def test_oversize_description_is_truncated_to_fit() -> None:
    """When the rendered description exceeds 400 chars the service trims
    optional pieces (scope -> intent -> summary) until it fits."""
    profile = _make_profile()
    payload = {
        "name": "Big Source",
        "summary": "A" * 200,  # massive summary
        "topics": ["topic-one", "topic-two", "topic-three"],
        "intent": "B" * 200,  # massive intent
        "scope": "C" * 200,  # massive scope
    }
    service = SourceNamingService(
        ai_model_resolver=_resolver_for(_openai_returning(payload)),
        langfuse=_langfuse_stub(),
    )
    naming = await service.name_from_profile(profile)

    assert len(naming.description) <= 400
    # Summary is the last piece truncated, so its prefix should still
    # show up — we want the most informative bit to survive.
    assert "AAAA" in naming.description
    # The description must remain valid template format.
    assert "Covers: topic-one, topic-two, topic-three." in naming.description


async def test_topics_capped_at_five_in_description() -> None:
    profile = _make_profile()
    payload = {
        "name": "Many Topics",
        "summary": "Source covers many topics across the company.",
        "topics": [f"topic-{i}" for i in range(10)],
        "intent": "broad questions",
        "scope": "",
    }
    service = SourceNamingService(
        ai_model_resolver=_resolver_for(_openai_returning(payload)),
        langfuse=_langfuse_stub(),
    )
    naming = await service.name_from_profile(profile)

    # Only the first 5 topics should appear.
    for i in range(5):
        assert f"topic-{i}" in naming.description
    for i in range(5, 10):
        assert f"topic-{i}" not in naming.description


async def test_strips_quotes_from_name() -> None:
    profile = _make_profile()
    payload = {
        "name": '"Quoted Name"',
        "summary": "valid summary text that fills space",
        "topics": ["x"],
        "intent": "things",
        "scope": "",
    }
    service = SourceNamingService(
        ai_model_resolver=_resolver_for(_openai_returning(payload)),
        langfuse=_langfuse_stub(),
    )
    naming = await service.name_from_profile(profile)
    assert naming.name == "Quoted Name"


async def test_resolves_correct_stage_slot() -> None:
    """The resolver MUST be asked for the source_autoname slot, not anything else."""
    profile = _make_profile()
    payload = {
        "name": "Some Source",
        "summary": "A small valid summary",
        "topics": ["x"],
        "intent": "things",
        "scope": "",
    }
    resolver = _resolver_for(_openai_returning(payload))
    service = SourceNamingService(
        ai_model_resolver=resolver,
        langfuse=_langfuse_stub(),
    )
    await service.name_from_profile(profile)

    resolver.resolve.assert_awaited_once_with("source_autoname")
