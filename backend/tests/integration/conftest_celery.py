"""Isolated Celery fixtures for worker crash/retry tests — FR-033 / T-095.

Uses in-memory broker and backend so these tests never touch a real broker.
The fixtures are session-scoped; pytest-celery (or celery.contrib.pytest)
picks them up automatically when the conftest is imported by the test module.
"""
import pytest

CELERY_TEST_CONFIG: dict[str, object] = {
    "broker_url": "memory://",
    "result_backend": "cache+memory://",
    "task_always_eager": False,
    "task_eager_propagates": True,
}


@pytest.fixture(scope="session")
def celery_config() -> dict[str, object]:
    """Override Celery configuration for the test session."""
    return CELERY_TEST_CONFIG


@pytest.fixture(scope="session")
def celery_parameters() -> dict[str, object]:
    """Additional Celery app parameters for the test session."""
    return {"strict_typing": False}
