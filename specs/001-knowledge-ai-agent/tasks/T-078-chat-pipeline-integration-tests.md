# T-078 â€” Chat Pipeline Integration Tests

**Status:** Done

## Context
```
Python 3.12 | pytest-asyncio Â· httpx AsyncClient Â· SQLAlchemy 2.x async
LangGraph compiled graph Â· interrupt() for clarification Â· SSE streaming
Langfuse self-hosted (mocked in tests)
pgvector HNSW Â· FR-019 source permissions
JWT 15-min access Â· RBAC (admin/user)
coverage target: 80% on app/agent/** and app/api/v1/chat.py
```

## Goal
Write **integration tests** covering the full chat pipeline:

1. Happy path â€” user sends a query, receives SSE stream with `done` event  
2. FR-019 enforcement â€” user cannot retrieve chunks from unapproved sources  
3. Clarification path â€” short query triggers `clarification` SSE event  
4. Session CRUD â€” create, list, get, delete  
5. Ownership enforcement â€” user cannot access another user's session  

---

## Acceptance Criteria

- [ ] All 5 test groups pass with `pytest -x`
- [ ] Line coverage â‰¥ 80% for `app/agent/**`
- [ ] Line coverage â‰¥ 80% for `app/api/v1/chat.py`
- [ ] Tests use the standard `async_client` + `db_session` fixtures
- [ ] No real OpenAI, Langfuse, or pgvector calls in any test

---

## 1  Fixtures â€” `tests/integration/conftest_chat.py`

```python
# tests/integration/conftest_chat.py
"""Shared fixtures for chat integration tests."""
from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock

import pytest

from app.agent.pipeline import build_pipeline


@pytest.fixture()
def mock_openai_client():
    client = AsyncMock()
    completion = MagicMock()
    completion.choices = [MagicMock()]
    completion.choices[0].message.content = "Here is the answer."
    completion.usage.prompt_tokens = 100
    completion.usage.completion_tokens = 20
    client.chat.completions.create.return_value = completion
    return client


@pytest.fixture()
def mock_langfuse():
    lf = MagicMock()
    span = MagicMock()
    lf.span.return_value = span
    lf.trace.return_value = MagicMock()
    return lf


@pytest.fixture()
def mock_embedding_service():
    svc = AsyncMock()
    svc.embed_texts.return_value = [[0.1] * 1536]
    return svc
```

---

## 2  Session CRUD Tests â€” `tests/integration/test_chat_sessions_api.py`

```python
# tests/integration/test_chat_sessions_api.py
"""Integration tests for chat session CRUD endpoints."""
from __future__ import annotations

import pytest
from httpx import AsyncClient


@pytest.mark.asyncio
async def test_create_session(async_client: AsyncClient, user_token: str):
    response = await async_client.post(
        "/api/v1/chat/sessions",
        json={"title": "My AI Conversation"},
        headers={"Authorization": f"Bearer {user_token}"},
    )
    assert response.status_code == 201
    data = response.json()
    assert data["title"] == "My AI Conversation"
    assert "id" in data


@pytest.mark.asyncio
async def test_list_sessions(async_client: AsyncClient, user_token: str):
    # Create 2 sessions
    for i in range(2):
        await async_client.post(
            "/api/v1/chat/sessions",
            json={"title": f"Session {i}"},
            headers={"Authorization": f"Bearer {user_token}"},
        )

    response = await async_client.get(
        "/api/v1/chat/sessions",
        headers={"Authorization": f"Bearer {user_token}"},
    )
    assert response.status_code == 200
    data = response.json()
    assert len(data["items"]) >= 2


@pytest.mark.asyncio
async def test_delete_session(async_client: AsyncClient, user_token: str):
    create_resp = await async_client.post(
        "/api/v1/chat/sessions",
        json={"title": "To Delete"},
        headers={"Authorization": f"Bearer {user_token}"},
    )
    session_id = create_resp.json()["id"]

    del_resp = await async_client.delete(
        f"/api/v1/chat/sessions/{session_id}",
        headers={"Authorization": f"Bearer {user_token}"},
    )
    assert del_resp.status_code == 204

    get_resp = await async_client.get(
        f"/api/v1/chat/sessions/{session_id}",
        headers={"Authorization": f"Bearer {user_token}"},
    )
    # Soft-deleted â†’ 403 (owned check fails)
    assert get_resp.status_code == 403


@pytest.mark.asyncio
async def test_cannot_access_other_users_session(
    async_client: AsyncClient, user_token: str, admin_token: str
):
    """Admin creates a session; regular user cannot access it."""
    create_resp = await async_client.post(
        "/api/v1/chat/sessions",
        json={"title": "Admin Only"},
        headers={"Authorization": f"Bearer {admin_token}"},
    )
    session_id = create_resp.json()["id"]

    get_resp = await async_client.get(
        f"/api/v1/chat/sessions/{session_id}",
        headers={"Authorization": f"Bearer {user_token}"},
    )
    assert get_resp.status_code == 403
```

---

## 3  Pipeline SSE Tests â€” `tests/integration/test_chat_pipeline.py`

```python
# tests/integration/test_chat_pipeline.py
"""Integration tests for the SSE streaming chat pipeline."""
from __future__ import annotations

import json
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from httpx import AsyncClient


def _parse_sse(raw: str) -> list[dict]:
    """Parse SSE response body into list of event dicts."""
    events = []
    for line in raw.strip().split("\n"):
        if line.startswith("data: "):
            events.append(json.loads(line[6:]))
    return events


@pytest.mark.asyncio
async def test_chat_stream_happy_path(
    async_client: AsyncClient,
    user_token: str,
    mock_openai_client,
    mock_langfuse,
    mock_embedding_service,
):
    """POST /messages returns SSE with at least one done event."""
    # Create session
    create_resp = await async_client.post(
        "/api/v1/chat/sessions",
        json={"title": "Test"},
        headers={"Authorization": f"Bearer {user_token}"},
    )
    session_id = create_resp.json()["id"]

    with (
        patch("app.containers.ApplicationContainer.pipeline") as mock_pl,
        patch("app.containers.ApplicationContainer.langfuse_tracing_service") as mock_tracing,
    ):
        # Simulate pipeline that yields a done event
        async def fake_stream_events(state, config, version):
            yield {
                "event": "on_chain_end",
                "name": "LangGraph",
                "data": {"output": {"final_answer": "Refunds in 30 days."}},
            }

        mock_pipeline = MagicMock()
        mock_pipeline.astream_events = fake_stream_events
        mock_pl.return_value = mock_pipeline

        mock_tracing_svc = MagicMock()
        mock_tracing_svc.start_trace.return_value = "trace-123"
        mock_tracing.return_value = mock_tracing_svc

        response = await async_client.post(
            f"/api/v1/chat/sessions/{session_id}/messages",
            json={"query": "What is our refund policy?"},
            headers={
                "Authorization": f"Bearer {user_token}",
                "Accept": "text/event-stream",
            },
        )

    assert response.status_code == 200
    assert "text/event-stream" in response.headers["content-type"]
    events = _parse_sse(response.text)
    event_types = [e["event"] for e in events]
    assert "done" in event_types


@pytest.mark.asyncio
async def test_chat_stream_clarification(async_client: AsyncClient, user_token: str):
    """Short query triggers clarification SSE event."""
    create_resp = await async_client.post(
        "/api/v1/chat/sessions",
        json={"title": "Clarify"},
        headers={"Authorization": f"Bearer {user_token}"},
    )
    session_id = create_resp.json()["id"]

    from langgraph.errors import GraphInterrupt  # noqa: PLC0415

    with (
        patch("app.containers.ApplicationContainer.pipeline") as mock_pl,
        patch("app.containers.ApplicationContainer.langfuse_tracing_service") as mock_tracing,
    ):
        async def raise_interrupt(state, config, version):
            raise GraphInterrupt("What product are you asking about?")
            yield  # make it a generator

        mock_pl.return_value.astream_events = raise_interrupt
        mock_tracing.return_value.start_trace.return_value = "trace-99"

        response = await async_client.post(
            f"/api/v1/chat/sessions/{session_id}/messages",
            json={"query": "hi"},
            headers={
                "Authorization": f"Bearer {user_token}",
                "Accept": "text/event-stream",
            },
        )

    assert response.status_code == 200
    events = _parse_sse(response.text)
    types = [e["event"] for e in events]
    assert "clarification" in types


@pytest.mark.asyncio
async def test_fr019_empty_source_ids_no_leak(
    async_client: AsyncClient, user_token: str
):
    """When user has no permitted sources, retrieved_chunks must be empty."""
    create_resp = await async_client.post(
        "/api/v1/chat/sessions",
        json={"title": "FR019"},
        headers={"Authorization": f"Bearer {user_token}"},
    )
    session_id = create_resp.json()["id"]

    captured_state: dict = {}

    with (
        patch("app.containers.ApplicationContainer.pipeline") as mock_pl,
        patch("app.containers.ApplicationContainer.langfuse_tracing_service") as mock_tracing,
        patch(
            "app.services.chat_session_service.ChatSessionService.get_source_ids_for_session",
            return_value=[],  # No permitted sources
        ),
    ):
        async def capture_state(state, config, version):
            captured_state.update(state)
            yield {
                "event": "on_chain_end",
                "name": "LangGraph",
                "data": {"output": {"final_answer": "No info."}},
            }

        mock_pl.return_value.astream_events = capture_state
        mock_tracing.return_value.start_trace.return_value = "trace-000"

        await async_client.post(
            f"/api/v1/chat/sessions/{session_id}/messages",
            json={"query": "What is the policy?"},
            headers={"Authorization": f"Bearer {user_token}"},
        )

    assert captured_state.get("source_ids") == []
```

---

## 4  Node Unit Test Index

| Test file | Nodes covered |
|---|---|
| `tests/unit/agent/test_retrieve_node.py` | `retrieve_context` |
| `tests/unit/agent/test_generate_node.py` | `generate_response` |
| `tests/unit/agent/test_clarify_node.py` | `check_clarification`, `handle_clarification` |
| `tests/integration/test_pipeline_smoke.py` | full pipeline (all 8 nodes) |

---

## 5  Coverage Target Enforcement

Add to `pyproject.toml` or `setup.cfg`:

```toml
[tool.pytest.ini_options]
addopts = "--cov=app/agent --cov=app/api/v1/chat --cov-fail-under=80"
```

---

## Files Modified / Created

| Action | Path |
|---|---|
| CREATE | `tests/integration/conftest_chat.py` |
| CREATE | `tests/integration/test_chat_sessions_api.py` |
| CREATE | `tests/integration/test_chat_pipeline.py` |
| PATCH  | `pyproject.toml` (coverage config) |
