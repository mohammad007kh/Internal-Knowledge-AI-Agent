from __future__ import annotations

import os

import pytest
from httpx import AsyncClient

pytestmark = pytest.mark.skipif(
    os.getenv("RUN_INTEGRATION_TESTS") != "1",
    reason="Integration tests require RUN_INTEGRATION_TESTS=1 and a live database",
)


class TestSourceAccessEnforcement:
    async def test_user_cannot_query_inaccessible_source(
        self, client: AsyncClient, admin_token: str, user_token: str
    ) -> None:
        src = await client.post(
            "/api/v1/sources",
            json={"name": "Restricted Docs", "type": "document", "mode": "snapshot"},
            headers={"Authorization": f"Bearer {admin_token}"},
        )
        source_id = src.json()["id"]

        await client.patch(
            f"/api/v1/sources/{source_id}",
            json={"is_approved": True},
            headers={"Authorization": f"Bearer {admin_token}"},
        )

        resp = await client.get(
            "/api/v1/sources",
            headers={"Authorization": f"Bearer {user_token}"},
        )
        ids = [s["id"] for s in resp.json()["items"]]
        assert source_id not in ids

    async def test_grant_then_revoke_access(
        self, client: AsyncClient, admin_token: str, user_token: str
    ) -> None:
        src = await client.post(
            "/api/v1/sources",
            json={"name": "Grantable", "type": "document", "mode": "snapshot"},
            headers={"Authorization": f"Bearer {admin_token}"},
        )
        source_id = src.json()["id"]

        me = await client.get(
            "/api/v1/users/me",
            headers={"Authorization": f"Bearer {user_token}"},
        )
        user_id = me.json()["id"]

        grant = await client.put(
            f"/api/v1/sources/{source_id}/access/{user_id}",
            headers={"Authorization": f"Bearer {admin_token}"},
        )
        assert grant.status_code == 204

        list_resp = await client.get(
            "/api/v1/sources",
            headers={"Authorization": f"Bearer {user_token}"},
        )
        assert source_id in [s["id"] for s in list_resp.json()["items"]]

        revoke = await client.delete(
            f"/api/v1/sources/{source_id}/access/{user_id}",
            headers={"Authorization": f"Bearer {admin_token}"},
        )
        assert revoke.status_code == 204

        list_after = await client.get(
            "/api/v1/sources",
            headers={"Authorization": f"Bearer {user_token}"},
        )
        assert source_id not in [s["id"] for s in list_after.json()["items"]]
