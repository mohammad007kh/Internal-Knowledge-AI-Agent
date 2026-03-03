from __future__ import annotations

import os
from unittest.mock import MagicMock, patch

import pytest
from httpx import AsyncClient

pytestmark = pytest.mark.skipif(
    os.getenv("RUN_INTEGRATION_TESTS") != "1",
    reason="Integration tests require RUN_INTEGRATION_TESTS=1 and a live database",
)


class TestChatSession:
    async def test_create_and_delete_session(
        self, client: AsyncClient, user_token: str
    ) -> None:
        resp = await client.post(
            "/api/v1/chat/sessions",
            json={},
            headers={"Authorization": f"Bearer {user_token}"},
        )
        assert resp.status_code == 201
        session_id = resp.json()["id"]

        del_resp = await client.delete(
            f"/api/v1/chat/sessions/{session_id}",
            headers={"Authorization": f"Bearer {user_token}"},
        )
        assert del_resp.status_code == 204


class TestMessageSSE:
    async def test_message_returns_sse_stream(
        self, client: AsyncClient, user_token: str
    ) -> None:
        session_resp = await client.post(
            "/api/v1/chat/sessions",
            json={},
            headers={"Authorization": f"Bearer {user_token}"},
        )
        session_id = session_resp.json()["id"]

        mock_pipeline = MagicMock()

        async def fake_astream_events(state, config=None, version="v2"):  # type: ignore[misc]
            yield {
                "event": "on_chat_model_stream",
                "data": {"chunk": type("C", (), {"content": "Hello"})()},
            }
            yield {
                "event": "on_chat_model_stream",
                "data": {"chunk": type("C", (), {"content": " world"})()},
            }
            yield {
                "event": "on_chain_end",
                "name": "LangGraph",
                "data": {"output": {"final_answer": "Hello world"}},
            }

        mock_pipeline.astream_events = fake_astream_events

        with patch(
            "src.core.container.Container.pipeline",
            return_value=mock_pipeline,
        ):
            async with client.stream(
                "POST",
                f"/api/v1/chat/sessions/{session_id}/messages",
                json={"query": "What is our leave policy?"},
                headers={
                    "Authorization": f"Bearer {user_token}",
                    "Accept": "text/event-stream",
                },
            ) as response:
                assert response.status_code == 200
                assert "text/event-stream" in response.headers["content-type"]
                lines = []
                async for line in response.aiter_lines():
                    lines.append(line)
                assert len("\n".join(lines)) > 0

    async def test_no_accessible_sources_returns_message(
        self, client: AsyncClient, user_token: str
    ) -> None:
        session_resp = await client.post(
            "/api/v1/chat/sessions",
            json={},
            headers={"Authorization": f"Bearer {user_token}"},
        )
        session_id = session_resp.json()["id"]

        with patch(
            "src.services.source_service.SourceService.get_accessible_sources",
            return_value=[],
        ):
            resp = await client.post(
                f"/api/v1/chat/sessions/{session_id}/messages",
                json={"query": "Tell me about HR policy"},
                headers={"Authorization": f"Bearer {user_token}"},
            )
        assert resp.status_code == 200
