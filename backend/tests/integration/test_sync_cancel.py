"""Integration tests for the U16 sync-cancel endpoint.

Spec coverage:

* ``POST /api/v1/sources/{source_id}/sync-jobs/{job_id}/cancel`` —
  cooperative cancellation. The endpoint:

  - 200 for an in-flight job (pending or running) → flips the row to
    cancelled + sets the Redis cancel flag.
  - 409 for an already-terminal job (success / failed / cancelled).
  - 404 for an unknown job.
  - 404 for a job whose source_id does not match the URL (IDOR guard).
  - 403 for a non-admin, non-owner caller.
  - 401 for an unauthenticated caller.

We do not exercise the celery task itself here — that lives in a separate
unit test that drives the checkpoint helper directly.
"""

from __future__ import annotations

import uuid
from unittest.mock import AsyncMock, MagicMock

import pytest
from cryptography.fernet import Fernet
from httpx import AsyncClient
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from src.models.enums import SourceType, SyncStatus
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
# Local fixtures
# ---------------------------------------------------------------------------


@pytest.fixture
def mock_settings() -> MagicMock:
    s = MagicMock()
    s.ENCRYPTION_KEY = Fernet.generate_key().decode()
    return s


@pytest.fixture
def connector_factory() -> MagicMock:
    return MagicMock()


@pytest.fixture
async def svc_source(
    db_session: AsyncSession,
    mock_settings: MagicMock,
    connector_factory: MagicMock,
) -> SourceService:
    repo = SourceRepository(session=db_session)
    return SourceService(repo, mock_settings, connector_factory)


@pytest.fixture
async def sample_source(svc_source: SourceService, admin_user: User):
    return await svc_source.create_source(
        SourceCreate(
            name="Cancel Test Source",
            source_type=SourceType.WEB_URL,
            config={"url": "https://example.com"},
        ),
        owner_id=admin_user.id,
    )


@pytest.fixture(autouse=True)
def stub_redis_cancel(monkeypatch) -> AsyncMock:
    """Stub the Redis cancel-flag write so tests don't need a live Redis.

    The endpoint calls ``set_sync_cancelled(source_id)`` which we replace
    with an AsyncMock so the test asserts the call site without needing
    a running Redis broker.
    """
    from src.api.v1 import sync_jobs as sj_module

    stub = AsyncMock(return_value=True)
    monkeypatch.setattr(sj_module, "set_sync_cancelled", stub)
    return stub


@pytest.fixture
async def client(
    db_session: AsyncSession,
    mock_settings: MagicMock,
    connector_factory: MagicMock,
) -> AsyncClient:
    """HTTPX test client with all DI overrides for the sync-jobs domain."""
    from httpx import ASGITransport
    from httpx import AsyncClient as _AsyncClient

    from src.api.v1.auth import _get_auth_service
    from src.api.v1.sync_jobs import (
        _get_source_service,
        _get_source_service_scoped,
        _get_sync_job_service,
    )
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

    test_db_url: str = settings.DATABASE_URL.replace(
        "/knowledge_agent", "/test_knowledge_agent"
    )
    test_engine = create_async_engine(test_db_url)
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
        return SyncJobService(
            session_factory=test_factory,
            sync_job_repo=SyncJobRepository(session=None),
        )

    app.dependency_overrides[get_db] = lambda: db_session
    app.dependency_overrides[_get_auth_service] = _make_auth_svc
    app.dependency_overrides[_get_user_service] = _make_user_svc
    app.dependency_overrides[_get_source_service] = _make_source_svc
    app.dependency_overrides[_get_source_service_scoped] = _make_source_svc
    app.dependency_overrides[_get_sync_job_service] = _make_sync_job_svc

    async with _AsyncClient(
        transport=ASGITransport(app=app), base_url="http://test"
    ) as ac:
        yield ac

    app.dependency_overrides.clear()
    await test_engine.dispose()


# ---------------------------------------------------------------------------
# Helper — trigger a sync and return its job_id
# ---------------------------------------------------------------------------


async def _trigger_pending_sync(
    client: AsyncClient, source_id: uuid.UUID, admin_token: str
) -> str:
    """Create a `pending` SyncJob via the trigger endpoint.

    The Celery worker is not running in tests, so the job stays `pending`
    forever — perfect for the cancel-endpoint contract tests.
    """
    resp = await client.post(
        f"/api/v1/sources/{source_id}/sync",
        headers={"Authorization": f"Bearer {admin_token}"},
    )
    assert resp.status_code == 202
    return resp.json()["id"]


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
class TestCancelSyncEndpoint:
    """HTTP-level contract for POST /sources/{id}/sync-jobs/{job_id}/cancel."""

    async def test_pending_job_returns_cancelled(
        self,
        client: AsyncClient,
        admin_user: User,
        sample_source,
        stub_redis_cancel: AsyncMock,
    ) -> None:
        token = await get_access_token(client, _ADMIN_EMAIL, _ADMIN_PASS)
        job_id = await _trigger_pending_sync(client, sample_source.id, token)

        resp = await client.post(
            f"/api/v1/sources/{sample_source.id}/sync-jobs/{job_id}/cancel",
            headers={"Authorization": f"Bearer {token}"},
        )
        assert resp.status_code == 200
        body = resp.json()
        assert body["id"] == job_id
        assert body["status"] == SyncStatus.CANCELLED.value
        assert body["cancelled_at"] is not None

        # The Redis flag was set with the source_id (not the job_id).
        stub_redis_cancel.assert_awaited()
        # The first positional arg is the source_id (UUID).
        call_args = stub_redis_cancel.await_args
        assert call_args.args[0] == sample_source.id

    async def test_already_terminal_returns_409(
        self,
        client: AsyncClient,
        admin_user: User,
        sample_source,
    ) -> None:
        token = await get_access_token(client, _ADMIN_EMAIL, _ADMIN_PASS)
        job_id = await _trigger_pending_sync(client, sample_source.id, token)

        # Cancel once → terminal.
        first = await client.post(
            f"/api/v1/sources/{sample_source.id}/sync-jobs/{job_id}/cancel",
            headers={"Authorization": f"Bearer {token}"},
        )
        assert first.status_code == 200

        # Second cancel → 409 Conflict.
        second = await client.post(
            f"/api/v1/sources/{sample_source.id}/sync-jobs/{job_id}/cancel",
            headers={"Authorization": f"Bearer {token}"},
        )
        assert second.status_code == 409

    async def test_unknown_job_returns_404(
        self,
        client: AsyncClient,
        admin_user: User,
        sample_source,
    ) -> None:
        token = await get_access_token(client, _ADMIN_EMAIL, _ADMIN_PASS)
        resp = await client.post(
            f"/api/v1/sources/{sample_source.id}/sync-jobs/{uuid.uuid4()}/cancel",
            headers={"Authorization": f"Bearer {token}"},
        )
        assert resp.status_code == 404

    async def test_mismatched_source_and_job_returns_404(
        self,
        client: AsyncClient,
        admin_user: User,
        sample_source,
        svc_source: SourceService,
    ) -> None:
        """IDOR guard — cancelling job-A under source-B URL must 404.

        Mirrors the audit-emit + the auth check so a caller who happens to
        own source-B cannot drive a cancel against an unrelated source's
        sync just by guessing the job id.
        """
        token = await get_access_token(client, _ADMIN_EMAIL, _ADMIN_PASS)
        job_id = await _trigger_pending_sync(client, sample_source.id, token)

        # Create a SECOND source. Cancel job_id under the second source's URL.
        other = await svc_source.create_source(
            SourceCreate(
                name="Other Source",
                source_type=SourceType.WEB_URL,
                config={"url": "https://example.org"},
            ),
            owner_id=admin_user.id,
        )

        resp = await client.post(
            f"/api/v1/sources/{other.id}/sync-jobs/{job_id}/cancel",
            headers={"Authorization": f"Bearer {token}"},
        )
        assert resp.status_code == 404

    async def test_non_admin_non_owner_returns_403(
        self,
        client: AsyncClient,
        admin_user: User,
        regular_user: User,
        sample_source,
    ) -> None:
        # Admin creates the sync (admin owns the source).
        admin_token = await get_access_token(client, _ADMIN_EMAIL, _ADMIN_PASS)
        job_id = await _trigger_pending_sync(client, sample_source.id, admin_token)

        # Regular user (NOT the owner) attempts to cancel → 403.
        user_token = await get_access_token(client, _USER_EMAIL, _USER_PASS)
        resp = await client.post(
            f"/api/v1/sources/{sample_source.id}/sync-jobs/{job_id}/cancel",
            headers={"Authorization": f"Bearer {user_token}"},
        )
        assert resp.status_code == 403

    async def test_unauthenticated_returns_401(
        self,
        client: AsyncClient,
        sample_source,
    ) -> None:
        resp = await client.post(
            f"/api/v1/sources/{sample_source.id}/sync-jobs/{uuid.uuid4()}/cancel"
        )
        assert resp.status_code == 401
