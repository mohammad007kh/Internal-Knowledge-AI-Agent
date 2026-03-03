"""Integration tests for source permissions API (T-059).

Spec coverage: FR-018, FR-019
  FR-018 - admins grant and revoke individual users' access to specific sources
  FR-019 - users only receive answers derived from sources explicitly granted to them

Covers:
  POST   /api/v1/sources/{source_id}/permissions
  DELETE /api/v1/sources/{source_id}/permissions/{user_id}
  GET    /api/v1/sources/{source_id}/permissions
  GET    /api/v1/users/me/sources
"""

from __future__ import annotations

import os
import uuid

import pytest
from httpx import AsyncClient

from src.models.enums import SourceType
from src.repositories.source_permission_repository import SourcePermissionRepository
from src.repositories.source_repository import SourceRepository
from src.schemas.source import SourceCreate
from src.services.source_permission_service import SourcePermissionService
from src.services.source_service import SourceService
from tests.conftest import get_access_token

pytestmark = pytest.mark.skipif(
    os.getenv("RUN_INTEGRATION_TESTS") != "1",
    reason="Set RUN_INTEGRATION_TESTS=1 to run integration tests",
)

_ADMIN_EMAIL = "admin@example.com"
_ADMIN_PASS = "Admin@1234"
_USER_EMAIL = "user@example.com"
_USER_PASS = "User@12345"

SOURCES_PERMS_BASE = "/api/v1/sources"
ME_SOURCES_URL = "/api/v1/users/me/sources"


@pytest.fixture
async def svc_source(db_session, mock_settings, connector_factory) -> SourceService:
    repo = SourceRepository(session=db_session)
    return SourceService(repo, mock_settings, connector_factory)


@pytest.fixture
async def svc_perm(db_session) -> SourcePermissionService:
    perm_repo = SourcePermissionRepository(session=db_session)
    source_repo = SourceRepository(session=db_session)
    from src.repositories.user_repository import UserRepository  # noqa: PLC0415

    user_repo = UserRepository(session=db_session)
    return SourcePermissionService(perm_repo, source_repo, user_repo)


@pytest.fixture
async def sample_source(svc_source, admin_user):
    """A live source owned by admin_user."""
    return await svc_source.create_source(
        SourceCreate(
            name="Perm API Test Source",
            source_type=SourceType.WEB_URL,
            config={"url": "https://example.com"},
        ),
        owner_id=admin_user.id,
    )


@pytest.fixture
async def extra_source(svc_source, admin_user):
    """A second live source used in me/sources tests."""
    return await svc_source.create_source(
        SourceCreate(
            name="Extra Source",
            source_type=SourceType.FILE_UPLOAD,
            config={},
        ),
        owner_id=admin_user.id,
    )


# ---------------------------------------------------------------------------
# Tests – POST /api/v1/sources/{source_id}/permissions (grant)
# ---------------------------------------------------------------------------


class TestGrantPermission:
    async def test_grant_returns_201(
        self, client: AsyncClient, admin_user, sample_source, regular_user
    ) -> None:
        token = await get_access_token(client, _ADMIN_EMAIL, _ADMIN_PASS)
        headers = {"Authorization": f"Bearer {token}"}
        url = f"{SOURCES_PERMS_BASE}/{sample_source.id}/permissions"
        resp = await client.post(url, json={"user_id": str(regular_user.id)}, headers=headers)
        assert resp.status_code == 201

    async def test_grant_creates_permission(
        self,
        client: AsyncClient,
        admin_user,
        sample_source,
        regular_user,
        svc_perm: SourcePermissionService,
    ) -> None:
        token = await get_access_token(client, _ADMIN_EMAIL, _ADMIN_PASS)
        headers = {"Authorization": f"Bearer {token}"}
        url = f"{SOURCES_PERMS_BASE}/{sample_source.id}/permissions"
        await client.post(url, json={"user_id": str(regular_user.id)}, headers=headers)
        user_ids = await svc_perm.list_for_source(sample_source.id)
        assert regular_user.id in user_ids

    async def test_grant_duplicate_returns_409(
        self, client: AsyncClient, admin_user, sample_source, regular_user
    ) -> None:
        token = await get_access_token(client, _ADMIN_EMAIL, _ADMIN_PASS)
        headers = {"Authorization": f"Bearer {token}"}
        url = f"{SOURCES_PERMS_BASE}/{sample_source.id}/permissions"
        await client.post(url, json={"user_id": str(regular_user.id)}, headers=headers)
        resp = await client.post(url, json={"user_id": str(regular_user.id)}, headers=headers)
        assert resp.status_code == 409

    async def test_grant_unknown_source_returns_404(
        self, client: AsyncClient, admin_user, regular_user
    ) -> None:
        token = await get_access_token(client, _ADMIN_EMAIL, _ADMIN_PASS)
        headers = {"Authorization": f"Bearer {token}"}
        url = f"{SOURCES_PERMS_BASE}/{uuid.uuid4()}/permissions"
        resp = await client.post(url, json={"user_id": str(regular_user.id)}, headers=headers)
        assert resp.status_code == 404

    async def test_grant_unknown_user_returns_404(
        self, client: AsyncClient, admin_user, sample_source
    ) -> None:
        token = await get_access_token(client, _ADMIN_EMAIL, _ADMIN_PASS)
        headers = {"Authorization": f"Bearer {token}"}
        url = f"{SOURCES_PERMS_BASE}/{sample_source.id}/permissions"
        resp = await client.post(url, json={"user_id": str(uuid.uuid4())}, headers=headers)
        assert resp.status_code == 404

    async def test_grant_requires_admin(
        self, client: AsyncClient, admin_user, regular_user, sample_source
    ) -> None:
        token = await get_access_token(client, _USER_EMAIL, _USER_PASS)
        headers = {"Authorization": f"Bearer {token}"}
        url = f"{SOURCES_PERMS_BASE}/{sample_source.id}/permissions"
        resp = await client.post(url, json={"user_id": str(regular_user.id)}, headers=headers)
        assert resp.status_code == 403

    async def test_grant_unauthenticated_returns_401(
        self, client: AsyncClient, admin_user, sample_source, regular_user
    ) -> None:
        url = f"{SOURCES_PERMS_BASE}/{sample_source.id}/permissions"
        resp = await client.post(url, json={"user_id": str(regular_user.id)})
        assert resp.status_code == 401


# ---------------------------------------------------------------------------
# Tests – DELETE /api/v1/sources/{source_id}/permissions/{user_id} (revoke)
# ---------------------------------------------------------------------------


class TestRevokePermission:
    async def test_revoke_returns_204(
        self,
        client: AsyncClient,
        admin_user,
        sample_source,
        regular_user,
        svc_perm: SourcePermissionService,
    ) -> None:
        await svc_perm.grant(source_id=sample_source.id, user_id=regular_user.id)
        token = await get_access_token(client, _ADMIN_EMAIL, _ADMIN_PASS)
        headers = {"Authorization": f"Bearer {token}"}
        url = f"{SOURCES_PERMS_BASE}/{sample_source.id}/permissions/{regular_user.id}"
        resp = await client.delete(url, headers=headers)
        assert resp.status_code == 204

    async def test_revoke_removes_permission(
        self,
        client: AsyncClient,
        admin_user,
        sample_source,
        regular_user,
        svc_perm: SourcePermissionService,
    ) -> None:
        await svc_perm.grant(source_id=sample_source.id, user_id=regular_user.id)
        token = await get_access_token(client, _ADMIN_EMAIL, _ADMIN_PASS)
        headers = {"Authorization": f"Bearer {token}"}
        url = f"{SOURCES_PERMS_BASE}/{sample_source.id}/permissions/{regular_user.id}"
        await client.delete(url, headers=headers)
        user_ids = await svc_perm.list_for_source(sample_source.id)
        assert regular_user.id not in user_ids

    async def test_revoke_nonexistent_returns_404(
        self, client: AsyncClient, admin_user, sample_source, regular_user
    ) -> None:
        token = await get_access_token(client, _ADMIN_EMAIL, _ADMIN_PASS)
        headers = {"Authorization": f"Bearer {token}"}
        url = f"{SOURCES_PERMS_BASE}/{sample_source.id}/permissions/{regular_user.id}"
        resp = await client.delete(url, headers=headers)
        assert resp.status_code == 404

    async def test_revoke_unknown_source_returns_404(
        self, client: AsyncClient, admin_user, regular_user
    ) -> None:
        token = await get_access_token(client, _ADMIN_EMAIL, _ADMIN_PASS)
        headers = {"Authorization": f"Bearer {token}"}
        url = f"{SOURCES_PERMS_BASE}/{uuid.uuid4()}/permissions/{regular_user.id}"
        resp = await client.delete(url, headers=headers)
        assert resp.status_code == 404

    async def test_revoke_requires_admin(
        self,
        client: AsyncClient,
        admin_user,
        regular_user,
        sample_source,
        svc_perm: SourcePermissionService,
    ) -> None:
        await svc_perm.grant(source_id=sample_source.id, user_id=regular_user.id)
        token = await get_access_token(client, _USER_EMAIL, _USER_PASS)
        headers = {"Authorization": f"Bearer {token}"}
        url = f"{SOURCES_PERMS_BASE}/{sample_source.id}/permissions/{regular_user.id}"
        resp = await client.delete(url, headers=headers)
        assert resp.status_code == 403

    async def test_revoke_unauthenticated_returns_401(
        self, client: AsyncClient, admin_user, sample_source, regular_user
    ) -> None:
        url = f"{SOURCES_PERMS_BASE}/{sample_source.id}/permissions/{regular_user.id}"
        resp = await client.delete(url)
        assert resp.status_code == 401


# ---------------------------------------------------------------------------
# Tests – GET /api/v1/sources/{source_id}/permissions (list for source)
# ---------------------------------------------------------------------------


class TestListPermissionsForSource:
    async def test_list_empty_by_default(
        self, client: AsyncClient, admin_user, sample_source
    ) -> None:
        token = await get_access_token(client, _ADMIN_EMAIL, _ADMIN_PASS)
        headers = {"Authorization": f"Bearer {token}"}
        url = f"{SOURCES_PERMS_BASE}/{sample_source.id}/permissions"
        resp = await client.get(url, headers=headers)
        assert resp.status_code == 200
        assert resp.json()["user_ids"] == []

    async def test_list_returns_granted_user(
        self,
        client: AsyncClient,
        admin_user,
        sample_source,
        regular_user,
        svc_perm: SourcePermissionService,
    ) -> None:
        await svc_perm.grant(source_id=sample_source.id, user_id=regular_user.id)
        token = await get_access_token(client, _ADMIN_EMAIL, _ADMIN_PASS)
        headers = {"Authorization": f"Bearer {token}"}
        url = f"{SOURCES_PERMS_BASE}/{sample_source.id}/permissions"
        resp = await client.get(url, headers=headers)
        assert resp.status_code == 200
        assert str(regular_user.id) in resp.json()["user_ids"]

    async def test_list_has_user_ids_key(
        self, client: AsyncClient, admin_user, sample_source
    ) -> None:
        token = await get_access_token(client, _ADMIN_EMAIL, _ADMIN_PASS)
        headers = {"Authorization": f"Bearer {token}"}
        url = f"{SOURCES_PERMS_BASE}/{sample_source.id}/permissions"
        resp = await client.get(url, headers=headers)
        assert resp.status_code == 200
        assert "user_ids" in resp.json()

    async def test_list_multiple_users(
        self,
        client: AsyncClient,
        admin_user,
        sample_source,
        regular_user,
        svc_perm: SourcePermissionService,
    ) -> None:
        await svc_perm.grant(source_id=sample_source.id, user_id=regular_user.id)
        await svc_perm.grant(source_id=sample_source.id, user_id=admin_user.id)
        token = await get_access_token(client, _ADMIN_EMAIL, _ADMIN_PASS)
        headers = {"Authorization": f"Bearer {token}"}
        url = f"{SOURCES_PERMS_BASE}/{sample_source.id}/permissions"
        resp = await client.get(url, headers=headers)
        assert len(resp.json()["user_ids"]) == 2

    async def test_list_requires_admin(
        self, client: AsyncClient, admin_user, regular_user, sample_source
    ) -> None:
        token = await get_access_token(client, _USER_EMAIL, _USER_PASS)
        headers = {"Authorization": f"Bearer {token}"}
        url = f"{SOURCES_PERMS_BASE}/{sample_source.id}/permissions"
        resp = await client.get(url, headers=headers)
        assert resp.status_code == 403

    async def test_list_unauthenticated_returns_401(
        self, client: AsyncClient, admin_user, sample_source
    ) -> None:
        url = f"{SOURCES_PERMS_BASE}/{sample_source.id}/permissions"
        resp = await client.get(url)
        assert resp.status_code == 401


# ---------------------------------------------------------------------------
# Tests – GET /api/v1/users/me/sources (list source IDs for current user)
# ---------------------------------------------------------------------------


class TestListMySources:
    async def test_returns_200(
        self, client: AsyncClient, admin_user, regular_user
    ) -> None:
        token = await get_access_token(client, _USER_EMAIL, _USER_PASS)
        headers = {"Authorization": f"Bearer {token}"}
        resp = await client.get(ME_SOURCES_URL, headers=headers)
        assert resp.status_code == 200

    async def test_empty_by_default(
        self, client: AsyncClient, admin_user, regular_user
    ) -> None:
        token = await get_access_token(client, _USER_EMAIL, _USER_PASS)
        headers = {"Authorization": f"Bearer {token}"}
        resp = await client.get(ME_SOURCES_URL, headers=headers)
        assert resp.json() == []

    async def test_returns_granted_source_id(
        self,
        client: AsyncClient,
        admin_user,
        sample_source,
        regular_user,
        svc_perm: SourcePermissionService,
    ) -> None:
        await svc_perm.grant(source_id=sample_source.id, user_id=regular_user.id)
        token = await get_access_token(client, _USER_EMAIL, _USER_PASS)
        headers = {"Authorization": f"Bearer {token}"}
        resp = await client.get(ME_SOURCES_URL, headers=headers)
        assert resp.status_code == 200
        assert str(sample_source.id) in resp.json()

    async def test_returns_multiple_source_ids(
        self,
        client: AsyncClient,
        admin_user,
        sample_source,
        extra_source,
        regular_user,
        svc_perm: SourcePermissionService,
    ) -> None:
        await svc_perm.grant(source_id=sample_source.id, user_id=regular_user.id)
        await svc_perm.grant(source_id=extra_source.id, user_id=regular_user.id)
        token = await get_access_token(client, _USER_EMAIL, _USER_PASS)
        headers = {"Authorization": f"Bearer {token}"}
        resp = await client.get(ME_SOURCES_URL, headers=headers)
        ids = resp.json()
        assert str(sample_source.id) in ids
        assert str(extra_source.id) in ids

    async def test_does_not_return_revoked_source(
        self,
        client: AsyncClient,
        admin_user,
        sample_source,
        extra_source,
        regular_user,
        svc_perm: SourcePermissionService,
    ) -> None:
        await svc_perm.grant(source_id=sample_source.id, user_id=regular_user.id)
        await svc_perm.grant(source_id=extra_source.id, user_id=regular_user.id)
        await svc_perm.revoke(source_id=sample_source.id, user_id=regular_user.id)
        token = await get_access_token(client, _USER_EMAIL, _USER_PASS)
        headers = {"Authorization": f"Bearer {token}"}
        resp = await client.get(ME_SOURCES_URL, headers=headers)
        ids = resp.json()
        assert str(sample_source.id) not in ids
        assert str(extra_source.id) in ids

    async def test_admin_sees_empty_without_explicit_grant(
        self,
        client: AsyncClient,
        admin_user,
        sample_source,
    ) -> None:
        """Admin role bypass is check_access-level; me/sources reflects explicit grants only."""
        token = await get_access_token(client, _ADMIN_EMAIL, _ADMIN_PASS)
        headers = {"Authorization": f"Bearer {token}"}
        resp = await client.get(ME_SOURCES_URL, headers=headers)
        assert resp.status_code == 200
        assert str(sample_source.id) not in resp.json()

    async def test_unauthenticated_returns_401(
        self, client: AsyncClient
    ) -> None:
        resp = await client.get(ME_SOURCES_URL)
        assert resp.status_code == 401
