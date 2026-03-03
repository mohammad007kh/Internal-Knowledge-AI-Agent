# T-058 â€” Source Service & Repository Integration Tests

**Status:** Done

## Context
```
Python 3.12 Â· pytest Â· pytest-asyncio Â· asyncio_mode=auto
SQLAlchemy 2.x async test session (in-process SQLite for non-vector tests,
real PostgreSQL via Docker for vector-index tests)
pytest fixtures from conftest: `db_session`, `async_client` (HTTPX)
RBAC: admin token + regular-user token fixtures
```

## Goal
Integration tests for `SourceRepository`, `SourceService`, `SourcePermissionRepository`,
and `SourcePermissionService`.  Uses an in-memory SQLite database (or a test-scoped
Postgres from `docker-compose.test.yml`) to verify real DB writes.

---

## File 1 â€” `tests/integration/test_source_repository.py`

```python
"""Integration tests for SourceRepository (SQLAlchemy async session)."""
from __future__ import annotations

import uuid

import pytest
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.enums import SourceType
from app.models.source import Source
from app.repositories.source_repository import SourceRepository


@pytest.fixture()
async def repo(db_session: AsyncSession) -> SourceRepository:
    return SourceRepository(session=db_session)


@pytest.fixture()
async def sample_source(db_session: AsyncSession) -> Source:
    src = Source(
        name="Integration Source",
        source_type=SourceType.WEB_URL,
        config_encrypted=b"encrypted_placeholder",
        owner_id=uuid.uuid4(),
    )
    db_session.add(src)
    await db_session.flush()
    await db_session.refresh(src)
    return src


class TestCreate:
    async def test_creates_and_returns_source(self, repo: SourceRepository) -> None:
        src = Source(
            name="New Source",
            source_type=SourceType.FILE_UPLOAD,
            config_encrypted=b"enc",
            owner_id=uuid.uuid4(),
        )
        created = await repo.create(src)
        assert created.id is not None
        assert created.name == "New Source"

    async def test_created_source_is_active(self, repo: SourceRepository) -> None:
        src = Source(
            name="Active",
            source_type=SourceType.WEB_URL,
            config_encrypted=b"enc",
            owner_id=uuid.uuid4(),
        )
        created = await repo.create(src)
        assert created.is_active is True


class TestRead:
    async def test_get_by_id_returns_source(
        self, repo: SourceRepository, sample_source: Source
    ) -> None:
        found = await repo.get_by_id(sample_source.id)
        assert found is not None
        assert found.id == sample_source.id

    async def test_get_by_id_returns_none_for_invalid(
        self, repo: SourceRepository
    ) -> None:
        found = await repo.get_by_id(uuid.uuid4())
        assert found is None

    async def test_get_by_id_returns_none_for_deleted(
        self, repo: SourceRepository, sample_source: Source
    ) -> None:
        await repo.soft_delete(sample_source.id)
        found = await repo.get_by_id(sample_source.id)
        assert found is None

    async def test_list_excludes_deleted(
        self, repo: SourceRepository, sample_source: Source
    ) -> None:
        await repo.soft_delete(sample_source.id)
        sources = await repo.list(offset=0, limit=100)
        ids = [s.id for s in sources]
        assert sample_source.id not in ids


class TestPagination:
    async def test_list_pagination(
        self, repo: SourceRepository, db_session: AsyncSession
    ) -> None:
        owner = uuid.uuid4()
        for i in range(5):
            src = Source(
                name=f"Source {i}",
                source_type=SourceType.WEB_URL,
                config_encrypted=b"enc",
                owner_id=owner,
            )
            db_session.add(src)
        await db_session.flush()

        page1 = await repo.list(offset=0, limit=3)
        page2 = await repo.list(offset=3, limit=3)
        assert len(page1) == 3
        assert len(page2) >= 2  # at least 2 more (may have sources from other tests)
```

---

## File 2 â€” `tests/integration/test_source_service.py`

```python
"""Integration tests for SourceService using real DB session."""
from __future__ import annotations

import uuid
from unittest.mock import AsyncMock, MagicMock

import pytest
from cryptography.fernet import Fernet
from sqlalchemy.ext.asyncio import AsyncSession

from app.connectors.factory import ConnectorFactory
from app.core.exceptions import ForbiddenException, NotFoundException
from app.models.enums import SourceType
from app.models.user import User, UserRole
from app.repositories.source_repository import SourceRepository
from app.services.source_service import SourceService


@pytest.fixture()
def fernet_key() -> bytes:
    return Fernet.generate_key()


@pytest.fixture()
def fernet(fernet_key: bytes) -> Fernet:
    return Fernet(fernet_key)


@pytest.fixture()
async def admin_user(db_session: AsyncSession) -> User:
    u = User(
        email="admin@test.com",
        hashed_password="hashed",
        role=UserRole.ADMIN,
        full_name="Admin User",
    )
    db_session.add(u)
    await db_session.flush()
    await db_session.refresh(u)
    return u


@pytest.fixture()
async def regular_user(db_session: AsyncSession) -> User:
    u = User(
        email="user@test.com",
        hashed_password="hashed",
        role=UserRole.USER,
        full_name="Regular User",
    )
    db_session.add(u)
    await db_session.flush()
    await db_session.refresh(u)
    return u


@pytest.fixture()
def mock_connector_factory() -> ConnectorFactory:
    factory = MagicMock(spec=ConnectorFactory)
    connector = AsyncMock()
    connector.__aenter__ = AsyncMock(return_value=connector)
    connector.__aexit__ = AsyncMock(return_value=False)
    connector.test_connection = AsyncMock(return_value=True)
    factory.build.return_value = connector
    return factory


@pytest.fixture()
async def svc(
    db_session: AsyncSession,
    fernet: Fernet,
    mock_connector_factory: ConnectorFactory,
) -> SourceService:
    return SourceService(
        source_repo=SourceRepository(session=db_session),
        fernet=fernet,
        connector_factory=mock_connector_factory,
    )


class TestCreateSource:
    async def test_creates_source(
        self, svc: SourceService, admin_user: User
    ) -> None:
        src = await svc.create_source(
            name="Web",
            source_type=SourceType.WEB_URL,
            config={"url": "https://example.com"},
            owner_id=admin_user.id,
        )
        assert src.id is not None
        assert src.name == "Web"

    async def test_encrypts_config(
        self, svc: SourceService, admin_user: User, fernet: Fernet
    ) -> None:
        await svc.create_source(
            name="DB",
            source_type=SourceType.DATABASE,
            config={"connection_string": "postgresql://u:secret@db/n", "query": "SELECT 1"},
            owner_id=admin_user.id,
        )
        # Retrieve raw row
        repo = SourceRepository(session=svc._repo._session)
        sources = await repo.list()
        raw_bytes = sources[-1].config_encrypted
        # Must be Fernet-decryptable
        decrypted = fernet.decrypt(raw_bytes)
        assert b"secret" in decrypted

    async def test_config_encrypted_not_plaintext_in_db(
        self, svc: SourceService, admin_user: User
    ) -> None:
        await svc.create_source(
            name="DB2",
            source_type=SourceType.DATABASE,
            config={"connection_string": "postgresql://u:secret@db/n", "query": "SELECT 1"},
            owner_id=admin_user.id,
        )
        repo = SourceRepository(session=svc._repo._session)
        sources = await repo.list()
        raw_bytes = sources[-1].config_encrypted
        # Plaintext must NOT appear in the raw bytes stored in DB
        assert b"secret" not in raw_bytes


class TestDeleteSource:
    async def test_admin_can_delete_any(
        self, svc: SourceService, admin_user: User, regular_user: User
    ) -> None:
        src = await svc.create_source(
            name="To Delete",
            source_type=SourceType.WEB_URL,
            config={"url": "https://x.com"},
            owner_id=regular_user.id,
        )
        await svc.delete_source(source_id=src.id, requester=admin_user)
        found = await svc.get_source(src.id)
        assert found is None

    async def test_owner_can_delete_own(
        self, svc: SourceService, regular_user: User
    ) -> None:
        src = await svc.create_source(
            name="Mine",
            source_type=SourceType.WEB_URL,
            config={"url": "https://x.com"},
            owner_id=regular_user.id,
        )
        await svc.delete_source(source_id=src.id, requester=regular_user)
        found = await svc.get_source(src.id)
        assert found is None

    async def test_non_owner_cannot_delete(
        self, svc: SourceService, regular_user: User, db_session: AsyncSession
    ) -> None:
        other_user = User(
            email="other@test.com",
            hashed_password="hashed",
            role=UserRole.USER,
            full_name="Other",
        )
        db_session.add(other_user)
        await db_session.flush()
        await db_session.refresh(other_user)
        src = await svc.create_source(
            name="Theirs",
            source_type=SourceType.WEB_URL,
            config={"url": "https://x.com"},
            owner_id=regular_user.id,
        )
        with pytest.raises(ForbiddenException):
            await svc.delete_source(source_id=src.id, requester=other_user)


class TestTestConnection:
    async def test_delegates_to_connector(
        self,
        svc: SourceService,
        admin_user: User,
        mock_connector_factory: ConnectorFactory,
    ) -> None:
        src = await svc.create_source(
            name="Testable",
            source_type=SourceType.WEB_URL,
            config={"url": "https://example.com"},
            owner_id=admin_user.id,
        )
        result = await svc.test_connection(src.id)
        assert result is True
        mock_connector_factory.build.assert_called_once()

    async def test_returns_false_on_exception(
        self,
        svc: SourceService,
        admin_user: User,
        mock_connector_factory: ConnectorFactory,
    ) -> None:
        mock_connector_factory.build.side_effect = Exception("boom")
        src = await svc.create_source(
            name="Broken",
            source_type=SourceType.WEB_URL,
            config={"url": "https://broken.com"},
            owner_id=admin_user.id,
        )
        result = await svc.test_connection(src.id)
        assert result is False
```

---

## File 3 â€” `tests/integration/test_source_permission_service.py`

```python
"""Integration tests for SourcePermissionService."""
from __future__ import annotations

import uuid

import pytest
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.exceptions import ConflictException, NotFoundException
from app.models.enums import SourceType
from app.models.source import Source
from app.models.user import User, UserRole
from app.repositories.source_permission_repository import SourcePermissionRepository
from app.repositories.source_repository import SourceRepository
from app.repositories.user_repository import UserRepository
from app.services.source_permission_service import SourcePermissionService


@pytest.fixture()
async def svc(db_session: AsyncSession) -> SourcePermissionService:
    return SourcePermissionService(
        source_permission_repo=SourcePermissionRepository(session=db_session),
        source_repo=SourceRepository(session=db_session),
        user_repo=UserRepository(session=db_session),
    )


@pytest.fixture()
async def source(db_session: AsyncSession) -> Source:
    s = Source(
        name="Perm Test Source",
        source_type=SourceType.WEB_URL,
        config_encrypted=b"enc",
        owner_id=uuid.uuid4(),
    )
    db_session.add(s)
    await db_session.flush()
    await db_session.refresh(s)
    return s


@pytest.fixture()
async def user(db_session: AsyncSession) -> User:
    u = User(
        email="perm_user@test.com",
        hashed_password="h",
        role=UserRole.USER,
        full_name="Perm User",
    )
    db_session.add(u)
    await db_session.flush()
    await db_session.refresh(u)
    return u


class TestGrant:
    async def test_grant_creates_permission(
        self, svc: SourcePermissionService, source: Source, user: User
    ) -> None:
        await svc.grant(source_id=source.id, user_id=user.id)
        source_ids = await svc.list_for_user(user.id)
        assert source.id in source_ids

    async def test_grant_raises_conflict_on_duplicate(
        self, svc: SourcePermissionService, source: Source, user: User
    ) -> None:
        await svc.grant(source_id=source.id, user_id=user.id)
        with pytest.raises(ConflictException):
            await svc.grant(source_id=source.id, user_id=user.id)

    async def test_grant_raises_not_found_for_missing_source(
        self, svc: SourcePermissionService, user: User
    ) -> None:
        with pytest.raises(NotFoundException):
            await svc.grant(source_id=uuid.uuid4(), user_id=user.id)

    async def test_grant_raises_not_found_for_missing_user(
        self, svc: SourcePermissionService, source: Source
    ) -> None:
        with pytest.raises(NotFoundException):
            await svc.grant(source_id=source.id, user_id=uuid.uuid4())


class TestRevoke:
    async def test_revoke_removes_permission(
        self, svc: SourcePermissionService, source: Source, user: User
    ) -> None:
        await svc.grant(source_id=source.id, user_id=user.id)
        await svc.revoke(source_id=source.id, user_id=user.id)
        source_ids = await svc.list_for_user(user.id)
        assert source.id not in source_ids

    async def test_revoke_raises_not_found_when_no_row(
        self, svc: SourcePermissionService, source: Source, user: User
    ) -> None:
        with pytest.raises(NotFoundException):
            await svc.revoke(source_id=source.id, user_id=user.id)


class TestCheckAccess:
    async def test_admin_always_has_access(
        self, svc: SourcePermissionService, source: Source
    ) -> None:
        has = await svc.check_access(
            source_id=source.id,
            user_id=uuid.uuid4(),
            user_role=UserRole.ADMIN,
        )
        assert has is True

    async def test_user_without_permission_denied(
        self, svc: SourcePermissionService, source: Source, user: User
    ) -> None:
        has = await svc.check_access(
            source_id=source.id,
            user_id=user.id,
            user_role=UserRole.USER,
        )
        assert has is False

    async def test_user_with_permission_allowed(
        self, svc: SourcePermissionService, source: Source, user: User
    ) -> None:
        await svc.grant(source_id=source.id, user_id=user.id)
        has = await svc.check_access(
            source_id=source.id,
            user_id=user.id,
            user_role=UserRole.USER,
        )
        assert has is True
```

---

## Acceptance Criteria

1. All three test files use the `db_session` fixture from `conftest.py`.
2. `TestCreate.test_config_encrypted_not_plaintext_in_db` verifies raw bytes in DB.
3. `TestDeleteSource.test_non_owner_cannot_delete` asserts `ForbiddenException`.
4. `TestTestConnection.test_returns_false_on_exception` asserts `False`, not raise.
5. All `TestCheckAccess` cases pass, especially admin bypass without DB call.
6. All tests run without external services (Fernet, SQLite or test-PG only).
7. Integration tests are in `tests/integration/` (separate from `tests/unit/`).
