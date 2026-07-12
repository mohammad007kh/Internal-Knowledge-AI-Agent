"""Unit tests for sync_source task helpers (T-064).

These tests are pure-unit and do NOT require a running database, broker, or
any external service — they exercise only the ``_sanitise`` utility function
which is the only stable, side-effect-free function in the module.

``_sanitise`` now delegates to the canonical hardened redactor
(:func:`src.services.db_safety.redact_dsn`). The hardened redactor is a
*superset* of the old leaky behavior: in addition to stripping URL
credentials it also collapses a bare ``host:port`` to ``<host>:<port>`` (DB
topology is sensitive too), so the expected output for credentialled URLs now
masks the trailing ``host:port`` as well.

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
        assert result == "postgresql+asyncpg://***@<host>:<port>/appdb"
        assert "s3cr3t" not in result
        assert "db.internal:5432" not in result

    def test_strips_password_from_redis_url(self) -> None:
        raw = "redis://default:mysecretpassword@cache:6379/0"
        result = _sanitise(raw)
        assert result == "redis://***@<host>:<port>/0"
        assert "mysecretpassword" not in result

    def test_strips_password_from_plain_http_url(self) -> None:
        raw = "http://user:hunter2@example.com/path"
        result = _sanitise(raw)
        # No ``host:port`` here, so only the credentials are masked.
        assert result == "http://***@example.com/path"
        assert "hunter2" not in result

    def test_strips_password_containing_at_sign(self) -> None:
        # REGRESSION: the old leaky regex stopped at the FIRST ``@`` and leaked
        # the password tail. The hardened redactor is greedy to the last ``@``.
        raw = "postgresql+asyncpg://admin:p@ss@db.internal/appdb"
        result = _sanitise(raw)
        assert "p@ss" not in result
        assert "ss@" not in result
        assert result == "postgresql+asyncpg://***@db.internal/appdb"

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
        """No ``@`` and no ``host:port`` → nothing to redact."""
        raw = "ftp://nopassword.example.com/file"
        assert _sanitise(raw) == raw

    def test_result_contains_scheme_prefix(self) -> None:
        raw = "postgresql://user:pw@host:5432/db"
        result = _sanitise(raw)
        assert result.startswith("postgresql://***@")

    def test_masks_host_and_port_after_at(self) -> None:
        # Hardened behavior: bare ``host:port`` is collapsed (topology is
        # sensitive). The path component still survives.
        raw = "amqp://guest:guest@rabbitmq:5672/vhost"
        result = _sanitise(raw)
        assert "rabbitmq:5672" not in result
        assert result == "amqp://***@<host>:<port>/vhost"
