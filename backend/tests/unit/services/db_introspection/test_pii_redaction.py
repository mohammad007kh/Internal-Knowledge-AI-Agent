"""Unit tests for the studying-agent's PII redaction helpers.

Pure-Python: no DB, no LLM. Exercises :mod:`src.services.db_introspection.pii_redaction`.
"""

from __future__ import annotations

import pytest

from src.services.db_introspection.pii_redaction import (
    MAX_SAMPLE_VALUE_LEN,
    column_name_looks_pii,
    looks_pii,
    redact_value,
    value_looks_pii,
)


# ---------------------------------------------------------------------------
# redact_value
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    "raw, expected",
    [
        ("alice@example.com", "a***@example.com"),
        ("BOB.JONES@corp.co.uk", "B***@corp.co.uk"),
        ("123-45-6789", "***"),
        ("987654321", "***"),  # bare 9-digit run → SSN-ish
        ("4111 1111 1111 1111", "***"),  # credit card with spaces
        ("4111-1111-1111-1111", "***"),  # credit card with hyphens
        ("+1 (555) 123-4567", "***"),  # phone
        ("ghp_aBcD1234EFgh5678IJkl90MNop", "***"),  # long opaque token
        ("sk-proj-aB12Cd34Ef56Gh78", "***"),  # api-key-ish token
    ],
)
def test_redact_value_redacts_pii(raw: str, expected: str) -> None:
    assert redact_value(raw) == expected


@pytest.mark.parametrize(
    "raw",
    [
        "hello world",
        "Order #12345",
        "2024-01-31",
        "active",
        "a quick brown fox jumps",
        "42",
        "3.14159",
        "",
        "   ",
        "ENABLED",
        "lorem ipsum dolor sit amet consectetur",  # long but has whitespace
        "ThisIsAVeryLongCamelCaseWordWithNoDigitsAtAll",  # long, no digit
    ],
)
def test_redact_value_leaves_ordinary_text_untouched(raw: str) -> None:
    assert redact_value(raw) == raw


def test_redact_value_handles_non_string_inputs() -> None:
    assert redact_value(42) == "42"
    assert redact_value(3.5) == "3.5"
    assert redact_value(True) == "True"
    assert redact_value(None) == "None"


# ---------------------------------------------------------------------------
# redact_value — oversized value capping
# ---------------------------------------------------------------------------


def test_redact_value_truncates_oversized_value() -> None:
    huge = "x" * 10_000
    out = redact_value(huge)
    assert len(out) <= MAX_SAMPLE_VALUE_LEN + 1
    assert out.endswith("…")
    assert out == "x" * MAX_SAMPLE_VALUE_LEN + "…"


def test_redact_value_oversized_email_prefix_is_not_misclassified() -> None:
    # A 10k-char blob that *starts* email-shaped must be truncated/passed
    # through, NOT collapsed to "a***@…" (it's a blob, not an address).
    blob = "alice@example.com" + "z" * 10_000
    out = redact_value(blob)
    assert not out.startswith("a***@")
    assert out.endswith("…")
    assert len(out) <= MAX_SAMPLE_VALUE_LEN + 1
    assert out.startswith("alice@example.com")


def test_redact_value_normal_email_still_redacted() -> None:
    # A perfectly ordinary ~50-char email is well under the cap → masked.
    addr = "alice.j.doe@some-fairly-long-domain-name.example.com"
    assert len(addr) < MAX_SAMPLE_VALUE_LEN
    assert redact_value(addr) == "a***@some-fairly-long-domain-name.example.com"


def test_value_looks_pii_false_for_oversized_value() -> None:
    assert value_looks_pii("x" * 10_000) is False
    # Even an email-shaped megablob is not "PII" — it's a blob.
    assert value_looks_pii("alice@example.com" + "z" * 10_000) is False


# ---------------------------------------------------------------------------
# value_looks_pii / column_name_looks_pii / looks_pii
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    "raw, expected",
    [
        ("alice@example.com", True),
        ("123-45-6789", True),
        ("4111 1111 1111 1111", True),
        ("+1 (555) 123-4567", True),
        ("ghp_aBcD1234EFgh5678IJkl90MNop", True),
        ("hello world", False),
        ("2024-01-31", False),
        ("42", False),
        ("", False),
    ],
)
def test_value_looks_pii(raw: str, expected: bool) -> None:
    assert value_looks_pii(raw) is expected


@pytest.mark.parametrize(
    "name, expected",
    [
        ("email", True),
        ("user_email", True),
        ("ssn", True),
        ("phone_number", True),
        ("date_of_birth", True),  # contains 'birth'
        ("password_hash", True),
        ("api_key", True),
        ("credit_card_last4", True),
        ("full_name", False),
        ("amount_cents", False),
        ("created_at", False),
        ("status", False),
    ],
)
def test_column_name_looks_pii(name: str, expected: bool) -> None:
    assert column_name_looks_pii(name) is expected


def test_looks_pii_combines_name_and_values() -> None:
    # PII-ish name, ordinary values → True (name wins).
    assert looks_pii("email", ["redacted", "n/a"]) is True
    # Ordinary name, PII-ish value → True (value wins).
    assert looks_pii("contact", ["alice@example.com"]) is True
    # Ordinary name, ordinary values → False.
    assert looks_pii("city", ["Paris", "Berlin", "Tokyo"]) is False
