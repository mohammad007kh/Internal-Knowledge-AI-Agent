"""Unit tests for environment-aware warnings in src.core.config.Settings.

Focus: the FX42 MINIO_SECURE production guard. The validator must WARN
(not refuse boot) when ENVIRONMENT=production and MINIO_SECURE is False,
and must stay silent in development.
"""

import logging

import pytest

from src.core.config import Settings

# Minimal set of required (no-default) fields so Settings() can be built
# in isolation without a live .env. Values are throwaway test fixtures.
_REQUIRED_FIELDS = {
    "DATABASE_URL": "postgresql+asyncpg://u:p@db:5432/test",
    "JWT_SECRET_KEY": "test-secret",
    "JWT_REFRESH_SECRET_KEY": "test-refresh-secret",
    "MINIO_ACCESS_KEY": "test-access",
    "MINIO_SECRET_KEY": "test-secret-key",
    "ENCRYPTION_KEY": "test-encryption-key",
}

_WARNING_FRAGMENT = "MINIO_SECURE is False in production"


def _build_settings(**overrides: object) -> Settings:
    return Settings(**{**_REQUIRED_FIELDS, **overrides})  # type: ignore[arg-type]


def test_minio_secure_warns_in_production(caplog: pytest.LogCaptureFixture) -> None:
    """ENVIRONMENT=production + MINIO_SECURE=False → loud warning."""
    with caplog.at_level(logging.WARNING, logger="src.core.config"):
        _build_settings(ENVIRONMENT="production", MINIO_SECURE=False)

    warnings = [
        r.getMessage()
        for r in caplog.records
        if r.levelno == logging.WARNING and _WARNING_FRAGMENT in r.getMessage()
    ]
    assert len(warnings) == 1
    message = warnings[0]
    # The warning must name the variable and the remediation, and must NOT
    # leak the MinIO endpoint or credentials.
    assert "MINIO_SECURE=true" in message
    assert "object-storage traffic" in message
    assert "untrusted network" in message
    assert _REQUIRED_FIELDS["MINIO_ACCESS_KEY"] not in message
    assert _REQUIRED_FIELDS["MINIO_SECRET_KEY"] not in message
    assert "minio:9000" not in message


def test_minio_secure_silent_in_development(caplog: pytest.LogCaptureFixture) -> None:
    """ENVIRONMENT=development + MINIO_SECURE=False → no warning."""
    with caplog.at_level(logging.WARNING, logger="src.core.config"):
        _build_settings(ENVIRONMENT="development", MINIO_SECURE=False)

    warnings = [
        r.getMessage()
        for r in caplog.records
        if _WARNING_FRAGMENT in r.getMessage()
    ]
    assert warnings == []


def test_minio_secure_silent_in_production_when_secure(
    caplog: pytest.LogCaptureFixture,
) -> None:
    """ENVIRONMENT=production + MINIO_SECURE=True → no warning."""
    with caplog.at_level(logging.WARNING, logger="src.core.config"):
        _build_settings(ENVIRONMENT="production", MINIO_SECURE=True)

    warnings = [
        r.getMessage()
        for r in caplog.records
        if _WARNING_FRAGMENT in r.getMessage()
    ]
    assert warnings == []
