"""
Unit test fixtures — mock all external I/O so unit tests run without
a real database, Redis, or MinIO.
"""
from unittest.mock import AsyncMock, MagicMock, patch

import pytest


@pytest.fixture(autouse=True)
def mock_db_session():
    """Replace the real AsyncSession with a MagicMock for unit tests."""
    mock_session = AsyncMock()
    mock_session.execute = AsyncMock()
    mock_session.commit = AsyncMock()
    mock_session.rollback = AsyncMock()
    mock_session.close = AsyncMock()
    return mock_session


@pytest.fixture(autouse=True)
def mock_redis():
    """Mock Redis client for unit tests."""
    with patch("src.core.redis.redis_client", new=AsyncMock()) as mock:
        yield mock


@pytest.fixture(autouse=True)
def mock_minio():
    """Mock MinIO client for unit tests."""
    with patch("src.core.storage.minio_client", new=MagicMock()) as mock:
        yield mock


@pytest.fixture(autouse=True)
def mock_celery():
    """Mock Celery task dispatch for unit tests."""
    with patch("src.worker.tasks.celery_app", new=MagicMock()) as mock:
        yield mock


# ---------------------------------------------------------------------------
# T-090 fixtures — models, repos, services
# ---------------------------------------------------------------------------

@pytest.fixture
def fake_user() -> "User":
    from src.models.user import User, UserRole

    return User(
        email="alice@example.com",
        hashed_password="$2b$12$hashed",
        full_name="Alice Example",
        role=UserRole.user,
        is_active=True,
        must_change_password=False,
    )


@pytest.fixture
def fake_admin(fake_user: "User") -> "User":
    from src.models.user import UserRole

    fake_user.role = UserRole.admin
    return fake_user


@pytest.fixture
def mock_user_repo() -> AsyncMock:
    repo = AsyncMock()
    repo.get_by_email = AsyncMock(return_value=None)
    repo.get_by_id = AsyncMock(return_value=None)
    repo.create = AsyncMock()
    repo.update = AsyncMock()
    repo.list = AsyncMock(return_value=[])
    return repo


@pytest.fixture
def mock_source_repo() -> AsyncMock:
    repo = AsyncMock()
    repo.get_by_id = AsyncMock(return_value=None)
    repo.list = AsyncMock(return_value=[])
    repo.create = AsyncMock()
    repo.update = AsyncMock()
    repo.soft_delete = AsyncMock(return_value=True)
    return repo


@pytest.fixture
def mock_policy_repo() -> AsyncMock:
    repo = AsyncMock()
    repo.list_active = AsyncMock(return_value=[])
    repo.get_by_id = AsyncMock(return_value=None)
    repo.create = AsyncMock()
    repo.update = AsyncMock()
    repo.delete = AsyncMock()
    return repo


@pytest.fixture
def mock_llm_repo() -> AsyncMock:
    repo = AsyncMock()
    repo.get_by_id = AsyncMock(return_value=None)
    repo.get_default = AsyncMock(return_value=None)
    repo.get_by_source_id = AsyncMock(return_value=None)
    repo.list = AsyncMock(return_value=[])
    repo.create = AsyncMock()
    repo.update = AsyncMock()
    repo.delete = AsyncMock()
    repo.upsert_source_override = AsyncMock()
    return repo


@pytest.fixture
def mock_guardrail_event_repo() -> AsyncMock:
    repo = AsyncMock()
    repo.create = AsyncMock()
    repo.list = AsyncMock(return_value=[])
    return repo
