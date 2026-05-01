"""Integration tests for the sync jobs router (T-066).

Spec coverage: FR-016, FR-017
  FR-016 - admins configure sync modes: manual, scheduled, auto-detect per source
  FR-017 - sync status (last synced time, in-progress state, error details) visible to admins

Covers all three endpoints:
  POST /api/v1/sources/{source_id}/sync       – trigger sync  (admin only)
  GET  /api/v1/sync-jobs/{job_id}             – get job       (authenticated)
  GET  /api/v1/sources/{source_id}/sync-jobs  – list jobs     (admin only)
"""
from __future__ import annotations

import uuid
from unittest.mock import MagicMock

import pytest
from cryptography.fernet import Fernet
from httpx import AsyncClient
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from src.models.enums import SourceType
from src.models.user import User
from src.repositories.source_repository import SourceRepository
from src.schemas.source import SourceCreate
from src.services.source_service import SourceService
from tests.conftest import get_access_token

_ADMIN_EMAIL = "admin@example.com"
_ADMIN_PASS = "Admin@1234"
_USER_EMAIL = "user@example.com"
_USER_PASS = "User@12345"


# ---------------------------------------------------------------------------
# Local fixtures — provide settings/factory/source helpers for this domain
# ---------------------------------------------------------------------------


@pytest.fixture
def mock_settings() -> MagicMock:
    """Minimal settings mock with a valid Fernet encryption key."""
    s = MagicMock()
    s.ENCRYPTION_KEY = Fernet.generate_key().decode()
    return s


@pytest.fixture
def connector_factory() -> MagicMock:
    """Stub ConnectorFactory (source creation doesn't need a real one)."""
    return MagicMock()


@pytest.fixture
async def svc_source(
    db_session: AsyncSession,
    mock_settings: MagicMock,
    connector_factory: MagicMock,
) -> SourceService:
    """SourceService wired to the test db_session."""
    repo = SourceRepository(session=db_session)
    return SourceService(repo, mock_settings, connector_factory)


@pytest.fixture
async def sample_source(svc_source: SourceService, admin_user: User):
    """A WEB_URL source owned by the admin user, persisted via db_session."""
    return await svc_source.create_source(
        SourceCreate(
            name="Sync Test Source",
            source_type=SourceType.WEB_URL,
            config={"url": "https://example.com"},
        ),
        owner_id=admin_user.id,
    )


# ---------------------------------------------------------------------------
# Local client override
#
# The root conftest.py only overrides auth/user DI helpers.  We need to also
# override _get_source_service and _get_sync_job_service so that requests hit
# the test database instead of the production Container.
#
# SyncJobService uses an async_sessionmaker (session_factory) to open fresh
# sessions per-call; we supply a factory pointing at the test DB.
# SyncJobRepository.__init__ accepts a session but ignores it (all methods
# receive the session explicitly from the service's _session() context).
# ---------------------------------------------------------------------------


@pytest.fixture
async def client(  # type: ignore[override]
    db_session: AsyncSession,
    mock_settings: MagicMock,
    connector_factory: MagicMock,
) -> AsyncClient:
    """HTTPX test client with all DI overrides for the sync-jobs domain."""
    from httpx import ASGITransport
    from httpx import AsyncClient as _AsyncClient

    from src.api.v1.auth import _get_auth_service
    from src.api.v1.sync_jobs import _get_source_service, _get_sync_job_service
    from src.api.v1.users import _get_user_service
    from src.core.config import settings
    from src.core.database import get_db
    from src.main import create_app
    from src.repositories.invitation_repository import InvitationRepository
    from src.repositories.refresh_token_repository import RefreshTokenRepository
    from src.repositories.source_repository import SourceRepository as _SourceRepo
    from src.repositories.sync_job_repository import SyncJobRepository
    from src.repositories.user_repository import UserRepository
    from src.services.auth_service import AuthService
    from src.services.email_service import EmailService
    from src.services.password_service import PasswordService
    from src.services.source_service import SourceService as _SourceSvc
    from src.services.sync_job_service import SyncJobService
    from src.services.user_service import UserService

    # Derive test DB URL the same way root conftest.py does
    test_db_url: str = settings.DATABASE_URL.replace(
        "/knowledge_agent", "/test_knowledge_agent"
    )
    test_engine = create_async_engine(test_db_url)
    # SyncJobService expects a callable that returns an AsyncSession context manager
    test_factory = async_sessionmaker(
        test_engine, expire_on_commit=False, class_=AsyncSession
    )

    app = create_app()

    def _make_user_svc() -> UserService:
        return UserService(
            user_repo=UserRepository(session=db_session),
            invitation_repo=InvitationRepository(session=db_session),
            password_service=PasswordService(),
            refresh_token_repo=RefreshTokenRepository(session=db_session),
            email_service=EmailService(),
        )

    def _make_auth_svc() -> AuthService:
        return AuthService(
            user_repo=UserRepository(session=db_session),
            refresh_repo=RefreshTokenRepository(session=db_session),
            user_service=_make_user_svc(),
            password_service=PasswordService(),
            session=db_session,
        )

    def _make_source_svc() -> _SourceSvc:
        return _SourceSvc(
            _SourceRepo(session=db_session), mock_settings, connector_factory
        )

    def _make_sync_job_svc() -> SyncJobService:
        # session param is accepted but ignored by SyncJobRepository —
        # every method receives the session explicitly from the service.
        return SyncJobService(
            session_factory=test_factory,
            sync_job_repo=SyncJobRepository(session=None),
        )

    app.dependency_overrides[get_db] = lambda: db_session
    app.dependency_overrides[_get_auth_service] = _make_auth_svc
    app.dependency_overrides[_get_user_service] = _make_user_svc
    app.dependency_overrides[_get_source_service] = _make_source_svc
    app.dependency_overrides[_get_sync_job_service] = _make_sync_job_svc

    async with _AsyncClient(
        transport=ASGITransport(app=app), base_url="http://test"
    ) as ac:
        yield ac

    app.dependency_overrides.clear()
    await test_engine.dispose()


# ---------------------------------------------------------------------------
# Integration tests
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
class TestSyncJobsRouter:
    """HTTP-level integration tests for sync-jobs endpoints."""

    # ------------------------------------------------------------------
    # POST /api/v1/sources/{source_id}/sync  (trigger sync, admin-only)
    # ------------------------------------------------------------------

    async def test_trigger_sync_returns_202(
        self,
        client: AsyncClient,
        admin_user: User,
        sample_source,
    ) -> None:
        token = await get_access_token(client, _ADMIN_EMAIL, _ADMIN_PASS)
        resp = await client.post(
            f"/api/v1/sources/{sample_source.id}/sync",
            headers={"Authorization": f"Bearer {token}"},
        )
        assert resp.status_code == 202
        body = resp.json()
        assert body["source_id"] == str(sample_source.id)
        assert body["status"] == "pending"
        assert "id" in body

    async def test_trigger_sync_non_admin_returns_403(
        self,
        client: AsyncClient,
        regular_user: User,
        sample_source,
    ) -> None:
        token = await get_access_token(client, _USER_EMAIL, _USER_PASS)
        resp = await client.post(
            f"/api/v1/sources/{sample_source.id}/sync",
            headers={"Authorization": f"Bearer {token}"},
        )
        assert resp.status_code == 403

    async def test_trigger_sync_unauthenticated_returns_401(
        self,
        client: AsyncClient,
        sample_source,
    ) -> None:
        resp = await client.post(f"/api/v1/sources/{sample_source.id}/sync")
        assert resp.status_code == 401

    async def test_trigger_sync_unknown_source_returns_404(
        self,
        client: AsyncClient,
        admin_user: User,
    ) -> None:
        token = await get_access_token(client, _ADMIN_EMAIL, _ADMIN_PASS)
        resp = await client.post(
            f"/api/v1/sources/{uuid.uuid4()}/sync",
            headers={"Authorization": f"Bearer {token}"},
        )
        assert resp.status_code == 404

    # ------------------------------------------------------------------
    # GET /api/v1/sync-jobs/{job_id}  (get job, any authenticated user)
    # ------------------------------------------------------------------

    async def test_get_sync_job_returns_200(
        self,
        client: AsyncClient,
        admin_user: User,
        regular_user: User,
        sample_source,
    ) -> None:
        # Trigger a sync first to create a job record
        admin_token = await get_access_token(client, _ADMIN_EMAIL, _ADMIN_PASS)
        trigger = await client.post(
            f"/api/v1/sources/{sample_source.id}/sync",
            headers={"Authorization": f"Bearer {admin_token}"},
        )
        assert trigger.status_code == 202
        job_id = trigger.json()["id"]

        # Any authenticated user may fetch the job
        user_token = await get_access_token(client, _USER_EMAIL, _USER_PASS)
        resp = await client.get(
            f"/api/v1/sync-jobs/{job_id}",
            headers={"Authorization": f"Bearer {user_token}"},
        )
        assert resp.status_code == 200
        assert resp.json()["id"] == job_id

    async def test_get_sync_job_unauthenticated_returns_401(
        self,
        client: AsyncClient,
    ) -> None:
        resp = await client.get(f"/api/v1/sync-jobs/{uuid.uuid4()}")
        assert resp.status_code == 401

    async def test_get_sync_job_unknown_returns_404(
        self,
        client: AsyncClient,
        regular_user: User,
    ) -> None:
        token = await get_access_token(client, _USER_EMAIL, _USER_PASS)
        resp = await client.get(
            f"/api/v1/sync-jobs/{uuid.uuid4()}",
            headers={"Authorization": f"Bearer {token}"},
        )
        assert resp.status_code == 404

    # ------------------------------------------------------------------
    # GET /api/v1/sources/{source_id}/sync-jobs  (list jobs, admin-only)
    # ------------------------------------------------------------------

    async def test_list_sync_jobs_returns_200(
        self,
        client: AsyncClient,
        admin_user: User,
        sample_source,
    ) -> None:
        token = await get_access_token(client, _ADMIN_EMAIL, _ADMIN_PASS)
        # Ensure at least one job exists
        await client.post(
            f"/api/v1/sources/{sample_source.id}/sync",
            headers={"Authorization": f"Bearer {token}"},
        )
        resp = await client.get(
            f"/api/v1/sources/{sample_source.id}/sync-jobs",
            headers={"Authorization": f"Bearer {token}"},
        )
        assert resp.status_code == 200
        body = resp.json()
        assert "items" in body
        assert "total" in body
        assert len(body["items"]) >= 1

    async def test_list_sync_jobs_non_admin_returns_403(
        self,
        client: AsyncClient,
        regular_user: User,
        sample_source,
    ) -> None:
        token = await get_access_token(client, _USER_EMAIL, _USER_PASS)
        resp = await client.get(
            f"/api/v1/sources/{sample_source.id}/sync-jobs",
            headers={"Authorization": f"Bearer {token}"},
        )
        assert resp.status_code == 403

    async def test_list_sync_jobs_unknown_source_returns_404(
        self,
        client: AsyncClient,
        admin_user: User,
    ) -> None:
        token = await get_access_token(client, _ADMIN_EMAIL, _ADMIN_PASS)
        resp = await client.get(
            f"/api/v1/sources/{uuid.uuid4()}/sync-jobs",
            headers={"Authorization": f"Bearer {token}"},
        )
        assert resp.status_code == 404
