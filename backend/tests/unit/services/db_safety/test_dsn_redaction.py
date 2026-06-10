"""Unit tests for the canonical DSN / credential redactor (FR-020).

This is the single source of truth that ~8 modules now delegate to. The
headline test is the regression that motivated the consolidation: a password
containing ``@`` must be FULLY stripped — the old leaky URL regex
(``://[^@\\s]+@``) stopped at the FIRST ``@`` and leaked the tail.
"""

from __future__ import annotations

from src.services.db_safety import redact_dsn


class TestRedactDsnUrlCredentials:
    def test_password_containing_at_sign_is_fully_stripped(self) -> None:
        # REGRESSION: ``user:p@ss@host`` must not leak ``ss``. The greedy
        # ``://[^/\\s]*@`` collapses everything up to the LAST ``@``.
        out = redact_dsn(
            "auth failed for postgresql+asyncpg://user:p@ss@host:5432/db"
        )
        assert "p@ss" not in out
        assert "pass" not in out
        assert "ss@" not in out
        assert "://***@" in out

    def test_simple_url_credentials(self) -> None:
        out = redact_dsn("could not connect to postgresql://admin:secret@db/app")
        assert "admin" not in out
        assert "secret" not in out
        assert out == "could not connect to postgresql://***@db/app"

    def test_multiple_urls_in_one_message(self) -> None:
        out = redact_dsn(
            "connecting redis://user1:pw1@redis and postgresql://user2:pw2@pg/db"
        )
        assert "pw1" not in out
        assert "pw2" not in out
        assert "user1" not in out
        assert "user2" not in out

    def test_url_without_credentials_is_untouched(self) -> None:
        raw = "http://example.com/path/to/resource"
        assert redact_dsn(raw) == raw

    def test_ipv6_host_credentials_are_stripped(self) -> None:
        # IPv6-ish authority — the credential portion must still be redacted.
        out = redact_dsn("connect failed: postgresql://user:pass@[::1]:5432/db")
        assert "user:pass" not in out
        assert "://***@" in out
        # The bracketed IPv6 host survives (no bare host:port to collapse here).
        assert "[::1]" in out


class TestRedactDsnKeyValue:
    def test_dsn_keyword_fragments_redacted(self) -> None:
        out = redact_dsn(
            "connection failed: host=db port=5432 user=admin "
            "password=hunter2 dbname=app"
        )
        assert "hunter2" not in out
        assert "admin" not in out
        assert "password=<redacted>" in out
        assert "user=<redacted>" in out
        assert "host=<redacted>" in out
        assert "dbname=<redacted>" in out

    def test_quoted_values_redacted(self) -> None:
        out = redact_dsn("password='s3 cr3t' host=\"my db\"")
        assert "s3 cr3t" not in out
        assert "my db" not in out
        assert "password=<redacted>" in out
        assert "host=<redacted>" in out


class TestRedactDsnBareHostPort:
    def test_bare_host_port_collapsed(self) -> None:
        out = redact_dsn("timeout connecting to internal-db.example.com:5432")
        assert "internal-db.example.com:5432" not in out
        assert "<host>:<port>" in out

    def test_does_not_eat_oversized_colon_numbers(self) -> None:
        # The port group is ``\d{2,5}`` — a 6+ digit run after the colon is not
        # a valid port and must NOT be collapsed.
        assert redact_dsn("hash a1b2c3:123456") == "hash a1b2c3:123456"


class TestRedactDsnNoOverRedaction:
    def test_clean_text_is_untouched(self) -> None:
        msg = 'relation "documents" does not exist'
        assert redact_dsn(msg) == msg

    def test_empty_string(self) -> None:
        assert redact_dsn("") == ""

    def test_accepts_non_string_objects(self) -> None:
        # Callers pass exception instances directly.
        exc = ValueError("postgresql://u:p@host:5432/db unreachable")
        out = redact_dsn(exc)
        assert "u:p" not in out
        assert "://***@" in out


class TestRedactDsnIdempotence:
    def test_idempotent(self) -> None:
        raw = (
            "fail postgresql://user:p@ss@db.internal:5432/app "
            "host=other port=6543 password=secret"
        )
        once = redact_dsn(raw)
        twice = redact_dsn(once)
        assert once == twice
        assert "p@ss" not in once
        assert "secret" not in once
