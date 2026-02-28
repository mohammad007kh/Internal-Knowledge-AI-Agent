"""Integration tests for SourcePermissionService (T-058).

Requires a live PostgreSQL database.
Run with:  RUN_INTEGRATION_TESTS=1 pytest tests/integration/test_source_permission_service.py -v
"""

from __future__ import annotations

import os
import uuid
from unittest.mock import AsyncMock, MagicMock

import pytest
from cryptography.fernet import Fernet

from src.core.exceptions import ConflictError, NotFoundError
from src.models.enums import SourceType
from src.models.user import UserRole
from src.repositories.source_permission_repository import SourcePermissionRepository
from src.repositories.source_repository import SourceRepository
from src.repositories.user_repository import UserRepository
from src.schemas.source import SourceCreate
from src.services.source_permission_service import SourcePermissionService
from src.services.source_service import SourceService

pytestmark = pytest.mark.skipif(
    os.getenv("RUN_INTEGRATION_TESTS") != "1",
    reason="Set RUN_INTEGRATION_TESTS=1 to run integration tests",
)

# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest.fixture
def mock_settings() -> MagicMock:
    settings = MagicMock()
    settings.ENCRYPTION_KEY = Fernet.generate_key().decode()
    return settings


@pytest.fixture
def connector_factory() -> MagicMock:
    factory = MagicMock()
    connector = MagicMock()
    connector.test_connection = AsyncMock(return_value=True)
    factory.build = MagicMock(return_value=connector)
    return factory


@pytest.fixture
async def svc_source(db_session, mock_settings, connector_factory) -> SourceService:
    repo = SourceRepository(session=db_session)
    return SourceService(repo, mock_settings, connector_factory)


@pytest.fixture
async def svc_perm(db_session) -> SourcePermissionService:
    perm_repo = SourcePermissionRepository(session=db_session)
    source_repo = SourceRepository(session=db_session)
    user_repo = UserRepository(session=db_session)
    return SourcePermissionService(perm_repo, source_repo, user_repo)


@pytest.fixture
async def sample_source(svc_source, admin_user):
    return await svc_source.create_source(
        SourceCreate(
            name="Perm Test Source",
            source_type=SourceType.WEB_URL,
            config={"url": "https://example.com"},
        ),
        owner_id=admin_user.id,
    )


@pytest.fixture
async def extra_user(db_session):
    """A second regular user distinct from the `regular_user` conftest fixture."""
    from src.models.user import User
    from src.services.password_service import PasswordService

    user = User(
        email="extra@example.com",
        hashed_password=PasswordService.hash_password("Passw0rd!"),
        role=UserRole.user,
        is_active=True,
    )
    db_session.add(user)
    await db_session.flush()
    return user


# ---------------------------------------------------------------------------
# TestGrant
# ---------------------------------------------------------------------------


class TestGrant:
    async def test_grant_success_returns_none(
        self, svc_perm, sample_source, regular_user
    ) -> None:
        result = await svc_perm.grant(sample_source.id, regular_user.id)
        assert result is None

    async def test_grant_duplicate_raises_conflict(
        self, svc_perm, sample_source, regular_user
    ) -> None:
        await svc_perm.grant(sample_source.id, regular_user.id)
        with pytest.raises(ConflictError):
            await svc_perm.grant(sample_source.id, regular_user.id)

    async def test_grant_missing_source_raises_not_found(
        self, svc_perm, regular_user
    ) -> None:
        nonexistent_source_id = uuid.uuid4()
        with pytest.raises(NotFoundError):
            await svc_perm.grant(nonexistent_source_id, regular_user.id)

    async def test_grant_missing_user_raises_not_found(
        self, svc_perm, sample_source
    ) -> None:
        nonexistent_user_id = uuid.uuid4()
        with pytest.raises(NotFoundError):
            await svc_perm.grant(sample_source.id, nonexistent_user_id)


# ---------------------------------------------------------------------------
# TestRevoke
# ---------------------------------------------------------------------------


class TestRevoke:
    async def test_revoke_success_returns_none(
        self, svc_perm, sample_source, regular_user
    ) -> None:
        await svc_perm.grant(sample_source.id, regular_user.id)
        result = await svc_perm.revoke(sample_source.id, regular_user.id)
        assert result is None

    async def test_revoke_not_found_raises_not_found(
        self, svc_perm, sample_source, regular_user
    ) -> None:
        with pytest.raises(NotFoundError):
            await svc_perm.revoke(sample_source.id, regular_user.id)

    async def test_revoke_nonexistent_source_raises_not_found(
        self, svc_perm, regular_user
    ) -> None:
        with pytest.raises(NotFoundError):
            await svc_perm.revoke(uuid.uuid4(), regular_user.id)

    async def test_revoke_nonexistent_user_raises_not_found(
        self, svc_perm, sample_source
    ) -> None:
        with pytest.raises(NotFoundError):
            await svc_perm.revoke(sample_source.id, uuid.uuid4())


# ---------------------------------------------------------------------------
# TestCheckAccess
# ---------------------------------------------------------------------------


class TestCheckAccess:
    async def test_admin_always_has_access(
        self, svc_perm, sample_source, admin_user
    ) -> None:
        result = await svc_perm.check_access(
            sample_source.id, admin_user.id, UserRole.admin
        )
        assert result is True

    async def test_admin_access_even_without_explicit_grant(
        self, svc_perm, sample_source, extra_user
    ) -> None:
        """Admin role bypasses the permission table entirely."""
        result = await svc_perm.check_access(
            sample_source.id, extra_user.id, UserRole.admin
        )
        assert result is True

    async def test_granted_user_has_access(
        self, svc_perm, sample_source, regular_user
    ) -> None:
        await svc_perm.grant(sample_source.id, regular_user.id)
        result = await svc_perm.check_access(
            sample_source.id, regular_user.id, UserRole.user
        )
        assert result is True

    async def test_non_granted_user_has_no_access(
        self, svc_perm, sample_source, regular_user
    ) -> None:
        result = await svc_perm.check_access(
            sample_source.id, regular_user.id, UserRole.user
        )
        assert result is False

    async def test_access_removed_after_revoke(
        self, svc_perm, sample_source, regular_user
    ) -> None:
        await svc_perm.grant(sample_source.id, regular_user.id)
        await svc_perm.revoke(sample_source.id, regular_user.id)
        result = await svc_perm.check_access(
            sample_source.id, regular_user.id, UserRole.user
        )
        assert result is False


# ---------------------------------------------------------------------------
# TestListForUser
# ---------------------------------------------------------------------------


class TestListForUser:
    async def test_returns_list(
        self, svc_perm, sample_source, regular_user
    ) -> None:
        await svc_perm.grant(sample_source.id, regular_user.id)
        result = await svc_perm.list_for_user(regular_user.id)
        assert isinstance(result, list)

    async def test_includes_granted_source_id(
        self, svc_perm, sample_source, regular_user
    ) -> None:
        await svc_perm.grant(sample_source.id, regular_user.id)
        result = await svc_perm.list_for_user(regular_user.id)
        assert sample_source.id in result

    async def test_empty_when_no_grants(
        self, svc_perm, regular_user
    ) -> None:
        result = await svc_perm.list_for_user(regular_user.id)
        assert result == []

    async def test_excludes_revoked_source(
        self, svc_perm, sample_source, regular_user
    ) -> None:
        await svc_perm.grant(sample_source.id, regular_user.id)
        await svc_perm.revoke(sample_source.id, regular_user.id)
        result = await svc_perm.list_for_user(regular_user.id)
        assert sample_source.id not in result

    async def test_multiple_sources_all_listed(
        self,
        svc_perm,
        svc_source,
        admin_user,
        regular_user,
        sample_source,
    ) -> None:
        second_source = await svc_source.create_source(
            SourceCreate(
                name="Second Source",
                source_type=SourceType.FILE_UPLOAD,
                config={},
            ),
            owner_id=admin_user.id,
        )
        await svc_perm.grant(sample_source.id, regular_user.id)
        await svc_perm.grant(second_source.id, regular_user.id)
        result = await svc_perm.list_for_user(regular_user.id)
        assert sample_source.id in result
        assert second_source.id in result

    async def test_user_isolation(
        self, svc_perm, sample_source, regular_user, extra_user
    ) -> None:
        """Granting to regular_user should not appear for extra_user."""
        await svc_perm.grant(sample_source.id, regular_user.id)
        result = await svc_perm.list_for_user(extra_user.id)
        assert sample_source.id not in result


# ---------------------------------------------------------------------------
# TestListForSource
# ---------------------------------------------------------------------------


class TestListForSource:
    async def test_returns_list(
        self, svc_perm, sample_source, regular_user
    ) -> None:
        await svc_perm.grant(sample_source.id, regular_user.id)
        result = await svc_perm.list_for_source(sample_source.id)
        assert isinstance(result, list)

    async def test_includes_granted_user_id(
        self, svc_perm, sample_source, regular_user
    ) -> None:
        await svc_perm.grant(sample_source.id, regular_user.id)
        result = await svc_perm.list_for_source(sample_source.id)
        assert regular_user.id in result

    async def test_empty_when_no_grants(
        self, svc_perm, sample_source
    ) -> None:
        result = await svc_perm.list_for_source(sample_source.id)
        assert result == []

    async def test_excludes_revoked_user(
        self, svc_perm, sample_source, regular_user
    ) -> None:
        await svc_perm.grant(sample_source.id, regular_user.id)
        await svc_perm.revoke(sample_source.id, regular_user.id)
        result = await svc_perm.list_for_source(sample_source.id)
        assert regular_user.id not in result

    async def test_multiple_users_all_listed(
        self, svc_perm, sample_source, regular_user, extra_user
    ) -> None:
        await svc_perm.grant(sample_source.id, regular_user.id)
        await svc_perm.grant(sample_source.id, extra_user.id)
        result = await svc_perm.list_for_source(sample_source.id)
        assert regular_user.id in result
        assert extra_user.id in result

    async def test_source_isolation(
        self,
        svc_perm,
        svc_source,
        admin_user,
        regular_user,
        sample_source,
    ) -> None:
        """Grant on one source must not appear under a different source."""
        other_source = await svc_source.create_source(
            SourceCreate(
                name="Other Source",
                source_type=SourceType.DATABASE,
                config={},
            ),
            owner_id=admin_user.id,
        )
        await svc_perm.grant(sample_source.id, regular_user.id)
        result = await svc_perm.list_for_source(other_source.id)
        assert regular_user.id not in result
