"""Unit tests for the source_router LangGraph node."""
from __future__ import annotations

import json
import uuid
from unittest.mock import AsyncMock, MagicMock

import pytest

from src.agent.nodes.source_router import route_sources
from src.models.enums import SourceType
from src.services.ai_model_resolver import AIModelClient


def _resolver_for(http_client) -> AsyncMock:
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


def _openai_returning(payload: dict) -> AsyncMock:
    client = AsyncMock()
    completion = MagicMock()
    completion.choices = [MagicMock()]
    completion.choices[0].message.content = json.dumps(payload)
    client.chat.completions.create.return_value = completion
    return client


def _make_source(*, type_: SourceType, name: str = "src") -> MagicMock:
    src = MagicMock()
    src.id = uuid.uuid4()
    src.name = name
    src.source_type = type_
    src.description = f"{name} description"
    return src


def _repo_with(sources: list) -> AsyncMock:
    repo = AsyncMock()
    repo.list_by_ids.return_value = sources
    return repo


def _langfuse() -> MagicMock:
    lf = MagicMock()
    lf.span.return_value = MagicMock()
    return lf


def _state(source_ids: list[str], query: str = "Where are the docs?") -> dict:
    return {
        "query": query,
        "source_ids": source_ids,
        "trace_id": "trace-1",
        "session_id": "sess-1",
        "user_id": "user-1",
    }


@pytest.mark.asyncio
async def test_selects_subset_from_llm() -> None:
    s1 = _make_source(type_=SourceType.WEB_URL, name="docs")
    s2 = _make_source(type_=SourceType.DATABASE, name="orders_db")
    accessible = [str(s1.id), str(s2.id)]

    payload = {
        "selected_source_ids": [str(s1.id)],
        "use_text_to_query_for": [],
    }
    resolver = _resolver_for(_openai_returning(payload))

    result = await route_sources(
        _state(accessible),
        ai_model_resolver=resolver,
        db_session=AsyncMock(),
        source_repository=_repo_with([s1, s2]),
        langfuse=_langfuse(),
    )

    resolver.resolve.assert_awaited_once_with("source_router")
    assert result["selected_source_ids"] == [str(s1.id)]
    assert result["text_to_query_source_ids"] == []


@pytest.mark.asyncio
async def test_text_to_query_only_for_database_type() -> None:
    s1 = _make_source(type_=SourceType.WEB_URL, name="docs")
    s2 = _make_source(type_=SourceType.DATABASE, name="orders_db")
    accessible = [str(s1.id), str(s2.id)]

    # LLM tries to route a non-DB source to text_to_query — must be filtered.
    payload = {
        "selected_source_ids": [str(s1.id), str(s2.id)],
        "use_text_to_query_for": [str(s1.id), str(s2.id)],
    }
    resolver = _resolver_for(_openai_returning(payload))

    result = await route_sources(
        _state(accessible),
        ai_model_resolver=resolver,
        db_session=AsyncMock(),
        source_repository=_repo_with([s1, s2]),
        langfuse=_langfuse(),
    )

    assert set(result["selected_source_ids"]) == {str(s1.id), str(s2.id)}
    # Only the database-typed source survives.
    assert result["text_to_query_source_ids"] == [str(s2.id)]


@pytest.mark.asyncio
async def test_falls_back_to_all_on_empty_selection() -> None:
    s1 = _make_source(type_=SourceType.WEB_URL, name="docs")
    accessible = [str(s1.id)]

    payload = {"selected_source_ids": [], "use_text_to_query_for": []}
    resolver = _resolver_for(_openai_returning(payload))

    result = await route_sources(
        _state(accessible),
        ai_model_resolver=resolver,
        db_session=AsyncMock(),
        source_repository=_repo_with([s1]),
        langfuse=_langfuse(),
    )

    assert result["selected_source_ids"] == accessible


@pytest.mark.asyncio
async def test_falls_back_to_all_on_llm_error() -> None:
    s1 = _make_source(type_=SourceType.WEB_URL, name="docs")
    accessible = [str(s1.id)]

    failing = AsyncMock()
    failing.chat.completions.create.side_effect = RuntimeError("boom")
    resolver = _resolver_for(failing)

    result = await route_sources(
        _state(accessible),
        ai_model_resolver=resolver,
        db_session=AsyncMock(),
        source_repository=_repo_with([s1]),
        langfuse=_langfuse(),
    )

    assert result["selected_source_ids"] == accessible
    assert result["text_to_query_source_ids"] == []


@pytest.mark.asyncio
async def test_empty_accessible_returns_empty_lists() -> None:
    resolver = _resolver_for(_openai_returning({"selected_source_ids": [], "use_text_to_query_for": []}))
    result = await route_sources(
        _state([]),
        ai_model_resolver=resolver,
        db_session=AsyncMock(),
        source_repository=_repo_with([]),
        langfuse=_langfuse(),
    )
    assert result == {"selected_source_ids": [], "text_to_query_source_ids": []}
    resolver.resolve.assert_not_called()


@pytest.mark.asyncio
async def test_filters_out_inaccessible_ids() -> None:
    """LLM hallucinates an id outside the user's allowlist — filtered out."""
    s1 = _make_source(type_=SourceType.WEB_URL, name="docs")
    accessible = [str(s1.id)]
    rogue_id = str(uuid.uuid4())

    payload = {
        "selected_source_ids": [str(s1.id), rogue_id],
        "use_text_to_query_for": [],
    }
    resolver = _resolver_for(_openai_returning(payload))

    result = await route_sources(
        _state(accessible),
        ai_model_resolver=resolver,
        db_session=AsyncMock(),
        source_repository=_repo_with([s1]),
        langfuse=_langfuse(),
    )

    assert result["selected_source_ids"] == [str(s1.id)]
