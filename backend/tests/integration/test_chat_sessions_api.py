"""Integration tests for chat session CRUD endpoints."""
from __future__ import annotations

import os

import pytest

_INTEGRATION = os.environ.get("RUN_INTEGRATION_TESTS", "0") == "1"

pytestmark = pytest.mark.skipif(
    not _INTEGRATION, reason="Set RUN_INTEGRATION_TESTS=1 to run integration tests"
)

if _INTEGRATION:

    @pytest.mark.asyncio
    async def test_create_session(client, user_token: str, regular_user) -> None:  # noqa: ARG001
        """POST /api/v1/chat/sessions creates a new session and returns 201."""
        response = await client.post(
            "/api/v1/chat/sessions",
            json={"title": "My AI Conversation"},
            headers={"Authorization": f"Bearer {user_token}"},
        )
        assert response.status_code == 201
        data = response.json()
        assert data["title"] == "My AI Conversation"
        assert "id" in data

    @pytest.mark.asyncio
    async def test_list_sessions(client, user_token: str, regular_user) -> None:  # noqa: ARG001
        """GET /api/v1/chat/sessions returns owned sessions."""
        # Create two sessions
        for title in ("Session Alpha", "Session Beta"):
            await client.post(
                "/api/v1/chat/sessions",
                json={"title": title},
                headers={"Authorization": f"Bearer {user_token}"},
            )

        response = await client.get(
            "/api/v1/chat/sessions",
            headers={"Authorization": f"Bearer {user_token}"},
        )
        assert response.status_code == 200
        data = response.json()
        assert "sessions" in data
        assert len(data["sessions"]) >= 2

    @pytest.mark.asyncio
    async def test_delete_session(client, user_token: str, regular_user) -> None:  # noqa: ARG001
        """DELETE /api/v1/chat/sessions/{id} soft-deletes; subsequent GET returns 403."""
        create_resp = await client.post(
            "/api/v1/chat/sessions",
            json={"title": "To Be Deleted"},
            headers={"Authorization": f"Bearer {user_token}"},
        )
        assert create_resp.status_code == 201
        session_id = create_resp.json()["id"]

        delete_resp = await client.delete(
            f"/api/v1/chat/sessions/{session_id}",
            headers={"Authorization": f"Bearer {user_token}"},
        )
        assert delete_resp.status_code == 204

        get_resp = await client.get(
            f"/api/v1/chat/sessions/{session_id}",
            headers={"Authorization": f"Bearer {user_token}"},
        )
        assert get_resp.status_code == 403

    @pytest.mark.asyncio
    async def test_cannot_access_other_users_session(
        client,
        user_token: str,
        admin_token: str,
        regular_user,  # noqa: ARG001
        admin_user,  # noqa: ARG001
    ) -> None:
        """A session owned by admin cannot be read by a regular user."""
        create_resp = await client.post(
            "/api/v1/chat/sessions",
            json={"title": "Admin Session"},
            headers={"Authorization": f"Bearer {admin_token}"},
        )
        assert create_resp.status_code == 201
        session_id = create_resp.json()["id"]

        get_resp = await client.get(
            f"/api/v1/chat/sessions/{session_id}",
            headers={"Authorization": f"Bearer {user_token}"},
        )
        assert get_resp.status_code == 403
