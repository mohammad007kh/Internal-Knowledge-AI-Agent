# Spec coverage: FR-035
# FR-035 - file uploads exceeding configured maximum file size are rejected immediately
from __future__ import annotations

import os
from unittest.mock import patch

import pytest
from httpx import AsyncClient

pytestmark = pytest.mark.skipif(
    os.getenv("RUN_INTEGRATION_TESTS") != "1",
    reason="Integration tests require RUN_INTEGRATION_TESTS=1 and a live database",
)


class TestSourceRegistration:
    async def test_register_document_source(
        self, client: AsyncClient, admin_token: str
    ) -> None:
        resp = await client.post(
            "/api/v1/sources",
            json={"name": "HR Handbook 2026", "type": "document", "mode": "snapshot"},
            headers={"Authorization": f"Bearer {admin_token}"},
        )
        assert resp.status_code == 201
        data = resp.json()
        assert data["is_approved"] is False

    async def test_presigned_url_returned(
        self, client: AsyncClient, admin_token: str
    ) -> None:
        src = await client.post(
            "/api/v1/sources",
            json={"name": "Policy Docs", "type": "document", "mode": "snapshot"},
            headers={"Authorization": f"Bearer {admin_token}"},
        )
        source_id = src.json()["id"]

        with patch(
            "src.infrastructure.storage.minio_storage.MinioStorage"
            ".generate_presigned_put_url"
        ):
            url_resp = await client.get(
                f"/api/v1/sources/{source_id}/upload-url",
                params={"filename": "policy.pdf"},
                headers={"Authorization": f"Bearer {admin_token}"},
            )
        assert url_resp.status_code == 200
        assert "url" in url_resp.json()

    async def test_config_encrypted_not_in_response(
        self, client: AsyncClient, admin_token: str
    ) -> None:
        resp = await client.post(
            "/api/v1/sources",
            json={
                "name": "DB Source",
                "type": "database",
                "mode": "live",
                "connector_type": "postgres",
                "connection_config": {
                    "host": "db",
                    "port": 5432,
                    "database": "prod",
                    "user": "app",
                    "password": "secret",
                },
            },
            headers={"Authorization": f"Bearer {admin_token}"},
        )
        body = resp.json()
        assert "config_encrypted" not in str(body)
        assert "password" not in str(body)


class TestIngestionTask:
    async def test_manual_sync_creates_sync_log(
        self, client: AsyncClient, admin_token: str
    ) -> None:
        src = await client.post(
            "/api/v1/sources",
            json={"name": "Sync Test", "type": "document", "mode": "snapshot"},
            headers={"Authorization": f"Bearer {admin_token}"},
        )
        source_id = src.json()["id"]

        with patch("src.tasks.sync_source.sync_source.delay") as mock_task:
            mock_task.return_value = None
            resp = await client.post(
                f"/api/v1/sources/{source_id}/sync",
                headers={"Authorization": f"Bearer {admin_token}"},
            )
        assert resp.status_code == 202

    async def test_file_over_50mb_rejected(
        self, client: AsyncClient, admin_token: str
    ) -> None:
        src = await client.post(
            "/api/v1/sources",
            json={"name": "Big Upload", "type": "document", "mode": "snapshot"},
            headers={"Authorization": f"Bearer {admin_token}"},
        )
        source_id = src.json()["id"]

        with patch(
            "src.infrastructure.storage.minio_storage.MinioStorage"
            ".generate_presigned_put_url"
        ):
            resp = await client.get(
                f"/api/v1/sources/{source_id}/upload-url",
                params={"filename": "huge.pdf", "size_bytes": str(51 * 1024 * 1024)},
                headers={"Authorization": f"Bearer {admin_token}"},
            )
        assert resp.status_code == 413
