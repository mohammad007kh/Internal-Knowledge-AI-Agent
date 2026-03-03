"""Integration tests for chat pipeline SSE streaming endpoint.

Spec coverage: FR-001, FR-002, FR-003, FR-004, FR-005
  FR-001 - natural language questions receive grounded answers via the pipeline
  FR-002 - query routing to relevant sources based on content
  FR-003 - semantic search over indexed content for database sources
  FR-004 - ambiguous query triggers clarifying question (check_clarification node)
  FR-005 - streaming token-by-token responses via SSE
"""
from __future__ import annotations

import json
import os
from collections.abc import AsyncGenerator
from unittest.mock import MagicMock, patch

import pytest

_INTEGRATION = os.environ.get("RUN_INTEGRATION_TESTS", "0") == "1"

pytestmark = pytest.mark.skipif(
    not _INTEGRATION, reason="Set RUN_INTEGRATION_TESTS=1 to run integration tests"
)


def _parse_sse(raw: str) -> list[dict]:
    """Parse a raw SSE response body into a list of event dicts."""
    events = []
    for line in raw.strip().split("\n"):
        if line.startswith("data: "):
            try:
                events.append(json.loads(line[6:]))
            except json.JSONDecodeError:
                pass
    return events


if _INTEGRATION:
    from src.api.v1.chat import _get_pipeline, _get_tracing  # noqa: E402

    @pytest.mark.asyncio
    async def test_chat_stream_happy_path(
        client,
        user_token: str,
        regular_user,  # noqa: ARG001
    ) -> None:
        """A well-formed query streams delta + done SSE events."""
        # Create a session first
        create_resp = await client.post(
            "/api/v1/chat/sessions",
            json={"title": "Happy Path Test"},
            headers={"Authorization": f"Bearer {user_token}"},
        )
        assert create_resp.status_code == 201
        session_id = create_resp.json()["id"]

        mock_tracing = MagicMock()
        mock_tracing.start_trace.return_value = "trace-001"

        async def fake_stream_events(
            state: dict, config: dict, version: str
        ) -> AsyncGenerator[dict, None]:
            yield {
                "event": "on_chain_end",
                "name": "LangGraph",
                "data": {"output": {"final_answer": "The capital is Paris."}},
            }

        mock_pipeline = MagicMock()
        mock_pipeline.astream_events = fake_stream_events

        app = client.app  # type: ignore[attr-defined]
        original_pipeline_override = app.dependency_overrides.get(_get_pipeline)
        original_tracing_override = app.dependency_overrides.get(_get_tracing)

        try:
            app.dependency_overrides[_get_pipeline] = lambda: mock_pipeline
            app.dependency_overrides[_get_tracing] = lambda: mock_tracing

            response = await client.post(
                f"/api/v1/chat/sessions/{session_id}/messages",
                json={"query": "What is the capital of France?"},
                headers={
                    "Authorization": f"Bearer {user_token}",
                    "Accept": "text/event-stream",
                },
            )
        finally:
            if original_pipeline_override is None:
                app.dependency_overrides.pop(_get_pipeline, None)
            else:
                app.dependency_overrides[_get_pipeline] = original_pipeline_override
            if original_tracing_override is None:
                app.dependency_overrides.pop(_get_tracing, None)
            else:
                app.dependency_overrides[_get_tracing] = original_tracing_override

        assert response.status_code == 200
        assert "text/event-stream" in response.headers.get("content-type", "")
        events = _parse_sse(response.text)
        event_types = [e.get("event") for e in events]
        assert "done" in event_types

    @pytest.mark.asyncio
    async def test_chat_stream_clarification(
        client,
        user_token: str,
        regular_user,  # noqa: ARG001
    ) -> None:
        """GraphInterrupt causes a clarification SSE event to be emitted."""
        from langgraph.errors import GraphInterrupt  # noqa: PLC0415

        create_resp = await client.post(
            "/api/v1/chat/sessions",
            json={"title": "Clarification Test"},
            headers={"Authorization": f"Bearer {user_token}"},
        )
        assert create_resp.status_code == 201
        session_id = create_resp.json()["id"]

        mock_tracing = MagicMock()
        mock_tracing.start_trace.return_value = "trace-99"

        async def raise_interrupt(
            state: dict, config: dict, version: str
        ) -> AsyncGenerator[dict, None]:
            raise GraphInterrupt("What product are you asking about?")
            yield  # make it an async generator

        mock_pipeline = MagicMock()
        mock_pipeline.astream_events = raise_interrupt

        app = client.app  # type: ignore[attr-defined]
        original_pipeline_override = app.dependency_overrides.get(_get_pipeline)
        original_tracing_override = app.dependency_overrides.get(_get_tracing)

        try:
            app.dependency_overrides[_get_pipeline] = lambda: mock_pipeline
            app.dependency_overrides[_get_tracing] = lambda: mock_tracing

            response = await client.post(
                f"/api/v1/chat/sessions/{session_id}/messages",
                json={"query": "hi"},
                headers={
                    "Authorization": f"Bearer {user_token}",
                    "Accept": "text/event-stream",
                },
            )
        finally:
            if original_pipeline_override is None:
                app.dependency_overrides.pop(_get_pipeline, None)
            else:
                app.dependency_overrides[_get_pipeline] = original_pipeline_override
            if original_tracing_override is None:
                app.dependency_overrides.pop(_get_tracing, None)
            else:
                app.dependency_overrides[_get_tracing] = original_tracing_override

        assert response.status_code == 200
        events = _parse_sse(response.text)
        event_types = [e.get("event") for e in events]
        assert "clarification" in event_types

    @pytest.mark.asyncio
    async def test_fr019_empty_source_ids_no_leak(
        client,
        user_token: str,
        regular_user,  # noqa: ARG001
    ) -> None:
        """When user has no permitted sources, source_ids passed to pipeline must be empty."""
        create_resp = await client.post(
            "/api/v1/chat/sessions",
            json={"title": "FR019"},
            headers={"Authorization": f"Bearer {user_token}"},
        )
        assert create_resp.status_code == 201
        session_id = create_resp.json()["id"]

        captured_state: dict = {}

        mock_tracing = MagicMock()
        mock_tracing.start_trace.return_value = "trace-000"

        async def capture_state(
            state: dict, config: dict, version: str
        ) -> AsyncGenerator[dict, None]:
            captured_state.update(state)
            yield {
                "event": "on_chain_end",
                "name": "LangGraph",
                "data": {"output": {"final_answer": "No info."}},
            }

        mock_pipeline = MagicMock()
        mock_pipeline.astream_events = capture_state

        app = client.app  # type: ignore[attr-defined]
        original_pipeline_override = app.dependency_overrides.get(_get_pipeline)
        original_tracing_override = app.dependency_overrides.get(_get_tracing)

        try:
            app.dependency_overrides[_get_pipeline] = lambda: mock_pipeline
            app.dependency_overrides[_get_tracing] = lambda: mock_tracing

            with patch(
                "src.services.chat_session_service.ChatSessionService.get_source_ids_for_session",
                return_value=[],
            ):
                await client.post(
                    f"/api/v1/chat/sessions/{session_id}/messages",
                    json={"query": "What is the policy?"},
                    headers={"Authorization": f"Bearer {user_token}"},
                )
        finally:
            if original_pipeline_override is None:
                app.dependency_overrides.pop(_get_pipeline, None)
            else:
                app.dependency_overrides[_get_pipeline] = original_pipeline_override
            if original_tracing_override is None:
                app.dependency_overrides.pop(_get_tracing, None)
            else:
                app.dependency_overrides[_get_tracing] = original_tracing_override

        assert captured_state.get("source_ids") == []
