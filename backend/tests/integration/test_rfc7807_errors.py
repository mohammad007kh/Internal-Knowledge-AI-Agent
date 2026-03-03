from __future__ import annotations

import os

import pytest
from httpx import AsyncClient

pytestmark = pytest.mark.skipif(
    os.getenv("RUN_INTEGRATION_TESTS") != "1",
    reason="Integration tests require RUN_INTEGRATION_TESTS=1 and a live database",
)

REQUIRED_FIELDS = {"type", "title", "status", "detail"}
PROBLEM_JSON_CONTENT_TYPE = "application/problem+json"


async def assert_problem_response(resp, expected_status: int) -> None:  # type: ignore[misc]
    assert resp.status_code == expected_status
    assert PROBLEM_JSON_CONTENT_TYPE in resp.headers.get("content-type", "")
    body = resp.json()
    for field in REQUIRED_FIELDS:
        assert field in body, f"Missing RFC 7807 field: {field}"
    assert body["status"] == expected_status


class TestRFC7807Errors:
    async def test_404_not_found(
        self, client: AsyncClient, admin_token: str
    ) -> None:
        resp = await client.get(
            "/api/v1/sources/00000000-0000-0000-0000-000000000000",
            headers={"Authorization": f"Bearer {admin_token}"},
        )
        await assert_problem_response(resp, 404)

    async def test_401_unauthenticated(self, client: AsyncClient) -> None:
        resp = await client.get("/api/v1/sources")
        await assert_problem_response(resp, 401)

    async def test_403_insufficient_role(
        self, client: AsyncClient, user_token: str
    ) -> None:
        resp = await client.post(
            "/api/v1/users/invitations",
            json={"email": "hack@example.com", "role": "admin"},
            headers={"Authorization": f"Bearer {user_token}"},
        )
        await assert_problem_response(resp, 403)

    async def test_422_validation_error(
        self, client: AsyncClient, admin_token: str
    ) -> None:
        resp = await client.post(
            "/api/v1/sources",
            json={"name": "", "type": "invalid_type"},
            headers={"Authorization": f"Bearer {admin_token}"},
        )
        await assert_problem_response(resp, 422)

    async def test_413_file_too_large(
        self, client: AsyncClient, admin_token: str
    ) -> None:
        src = await client.post(
            "/api/v1/sources",
            json={"name": "Upload Test", "type": "document", "mode": "snapshot"},
            headers={"Authorization": f"Bearer {admin_token}"},
        )
        source_id = src.json()["id"]
        resp = await client.get(
            f"/api/v1/sources/{source_id}/upload-url",
            params={"filename": "huge.pdf", "size_bytes": str(51 * 1024 * 1024)},
            headers={"Authorization": f"Bearer {admin_token}"},
        )
        await assert_problem_response(resp, 413)

    async def test_410_expired_invitation(self, client: AsyncClient) -> None:
        resp = await client.post(
            "/api/v1/auth/setup",
            json={"token": "definitely_expired_token", "password": "NewPass1!"},
        )
        await assert_problem_response(resp, 410)
