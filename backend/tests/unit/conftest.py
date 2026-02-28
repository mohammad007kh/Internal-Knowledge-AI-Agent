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
