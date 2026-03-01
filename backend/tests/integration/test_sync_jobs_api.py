"""Integration tests: sync jobs API router — T-068."""
from __future__ import annotations

import uuid
from unittest.mock import patch

import pytest
import pytest_asyncio
from httpx import AsyncClient
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

from src.core.config import settings

_TEST_DB_URL = settings.DATABASE_URL.replace("/knowledge_agent", "/test_knowledge_agent")

_ADMIN_EMAIL = "admin@example.com"
_ADMIN_PASS = "Admin@1234"
_USER_EMAIL = "user@example.com"
_USER_PASS = "User@12345"


async def _get_token(client: AsyncClient, email: str, password: str) -> str:
    resp = await client.post(
        "/api/v1/auth/login",
        json={"email": email, "password": password},
    )
    return resp.json()["access_token"]


@pytest_asyncio.fixture
async def client(admin_user, regular_user):  # noqa: ARG001
    """File-local AsyncClient with test-DB overrides."""
    from src.api.deps import get_db

    from src.main import app

    test_engine = create_async_engine(_TEST_DB_URL)
    test_factory = async_sessionmaker(test_engine, expire_on_commit=False)

    async def _override_get_db():
        async with test_factory() as session:
            yield session

    app.dependency_overrides[get_db] = _override_get_db
    async with AsyncClient(app=app, base_url="http://test") as c:
        yield c
    app.dependency_overrides.clear()
    await test_engine.dispose()


@pytest.mark.asyncio
class TestTriggerSync:
    """POST /{source_id}/sync — admin only, returns 202 with pending job."""

    async def test_trigger_sync_returns_202_pending(
        self, client: AsyncClient, db_source
    ) -> None:
        token = await _get_token(client, _ADMIN_EMAIL, _ADMIN_PASS)
        with patch("src.tasks.sync_source.sync_source.delay") as mock_delay:
            mock_delay.return_value = None
            resp = await client.post(
                f"/api/v1/sources/{db_source.id}/sync",
                headers={"Authorization": f"Bearer {token}"},
            )
        assert resp.status_code == 202
        body = resp.json()
        assert "id" in body
        assert body["status"] == "pending"

    async def test_trigger_sync_non_admin_403(
        self, client: AsyncClient, db_source
    ) -> None:
        token = await _get_token(client, _USER_EMAIL, _USER_PASS)
        resp = await client.post(
            f"/api/v1/sources/{db_source.id}/sync",
            headers={"Authorization": f"Bearer {token}"},
        )
        assert resp.status_code == 403

    async def test_trigger_sync_unknown_source_404(
        self, client: AsyncClient
    ) -> None:
        token = await _get_token(client, _ADMIN_EMAIL, _ADMIN_PASS)
        fake_id = uuid.uuid4()
        with patch("src.tasks.sync_source.sync_source.delay"):
            resp = await client.post(
                f"/api/v1/sources/{fake_id}/sync",
                headers={"Authorization": f"Bearer {token}"},
            )
        assert resp.status_code == 404


@pytest.mark.asyncio
class TestGetSyncJob:
    """GET /sync-jobs/{job_id} — any authenticated user."""

    async def test_get_sync_job_200(
        self, client: AsyncClient, db_sync_job
    ) -> None:
        token = await _get_token(client, _USER_EMAIL, _USER_PASS)
        resp = await client.get(
            f"/api/v1/sync-jobs/{db_sync_job.id}",
            headers={"Authorization": f"Bearer {token}"},
        )
        assert resp.status_code == 200
        assert str(resp.json()["id"]) == str(db_sync_job.id)

    async def test_get_sync_job_not_found_404(
        self, client: AsyncClient
    ) -> None:
        token = await _get_token(client, _USER_EMAIL, _USER_PASS)
        fake_id = uuid.uuid4()
        resp = await client.get(
            f"/api/v1/sync-jobs/{fake_id}",
            headers={"Authorization": f"Bearer {token}"},
        )
        assert resp.status_code == 404


@pytest.mark.asyncio
class TestListSyncJobs:
    """GET /{source_id}/sync-jobs — admin only."""

    async def test_list_sync_jobs_returns_items(
        self, client: AsyncClient, db_source, db_sync_job
    ) -> None:
        token = await _get_token(client, _ADMIN_EMAIL, _ADMIN_PASS)
        resp = await client.get(
            f"/api/v1/sources/{db_source.id}/sync-jobs",
            headers={"Authorization": f"Bearer {token}"},
        )
        assert resp.status_code == 200
        body = resp.json()
        assert "items" in body
        assert body["total"] >= 1
        ids = [item["id"] for item in body["items"]]
        assert str(db_sync_job.id) in ids

    async def test_list_sync_jobs_non_admin_403(
        self, client: AsyncClient, db_source
    ) -> None:
        token = await _get_token(client, _USER_EMAIL, _USER_PASS)
        resp = await client.get(
            f"/api/v1/sources/{db_source.id}/sync-jobs",
            headers={"Authorization": f"Bearer {token}"},
        )
        assert resp.status_code == 403
