"""Unit tests for sync_source task helpers (T-064).

These tests are pure-unit and do NOT require a running database, broker, or
any external service — they exercise only the ``_sanitise`` utility function
which is the only stable, side-effect-free function in the module.

The full pipeline (``_sync_source_async``) is integration-tested separately
(``RUN_INTEGRATION_TESTS=1``).
"""
from __future__ import annotations

from src.tasks.sync_source import _sanitise


class TestSanitise:
    """Credential-scrubbing helper tests."""

    def test_strips_password_from_postgres_url(self) -> None:
        raw = "postgresql+asyncpg://admin:s3cr3t@db.internal:5432/appdb"
        result = _sanitise(raw)
        assert result == "postgresql+asyncpg://***@db.internal:5432/appdb"
        assert "s3cr3t" not in result

    def test_strips_password_from_redis_url(self) -> None:
        raw = "redis://default:mysecretpassword@cache:6379/0"
        result = _sanitise(raw)
        assert result == "redis://***@cache:6379/0"
        assert "mysecretpassword" not in result

    def test_strips_password_from_plain_http_url(self) -> None:
        raw = "http://user:hunter2@example.com/path"
        result = _sanitise(raw)
        assert result == "http://***@example.com/path"
        assert "hunter2" not in result

    def test_multiple_credential_urls_in_one_string(self) -> None:
        raw = (
            "connecting redis://user1:pw1@redis:6379 "
            "and postgresql://user2:pw2@pg:5432/db"
        )
        result = _sanitise(raw)
        assert "pw1" not in result
        assert "pw2" not in result
        assert "user1" not in result
        assert "user2" not in result

    def test_url_without_credentials_is_unchanged(self) -> None:
        raw = "http://example.com/path/to/resource"
        assert _sanitise(raw) == raw

    def test_plain_text_message_is_unchanged(self) -> None:
        raw = "Something went wrong while processing the request"
        assert _sanitise(raw) == raw

    def test_empty_string(self) -> None:
        assert _sanitise("") == ""

    def test_url_with_username_only_no_password(self) -> None:
        """If there is no '@' the regex should not match and nothing is changed."""
        raw = "ftp://nopassword.example.com/file"
        assert _sanitise(raw) == raw

    def test_result_contains_scheme_prefix(self) -> None:
        raw = "postgresql://user:pw@host:5432/db"
        result = _sanitise(raw)
        assert result.startswith("postgresql://***@")

    def test_preserves_host_and_port_after_at(self) -> None:
        raw = "amqp://guest:guest@rabbitmq:5672/vhost"
        result = _sanitise(raw)
        assert "rabbitmq:5672/vhost" in result
