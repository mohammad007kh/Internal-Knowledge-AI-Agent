"""PII redaction for sampled column values.

The studying-agent samples up to 3 distinct values per column and stores
them verbatim in :class:`~src.services.db_introspection.schema_doc.ColumnDoc.sample_values`
— but only *after* running them through :func:`redact_value` here. The
persisted ``schema_document_json`` (and everything downstream: the U7
schema viewer, the DESCRIBING phase's LLM prompts) must never carry raw
emails, SSNs, card numbers, phone numbers, or opaque secret-looking
tokens.

Redaction rules (applied in priority order):

* email ``alice@example.com``      → ``a***@example.com``
* SSN ``123-45-6789``              → ``***``
* credit card ``4111 1111 1111 1111`` (13-19 digits, optional
  separators)                       → ``***``
* phone ``+1 (555) 123-4567``       → ``***``
* long opaque token (≥20 chars,
  no whitespace, looks random)      → ``***``
* anything else                     → returned unchanged
* …but any value longer than :data:`MAX_SAMPLE_VALUE_LEN` is truncated
  (with a trailing ``"…"``) *before* it lands in ``sample_values`` — a
  10 MB ``TEXT`` cell must not bloat the persisted ``schema_document_json``.
  Values that long are also never regex-scanned (they're blobs, not PII).

:func:`looks_pii` answers the companion question — "does this column /
value look PII-ish?" — and feeds ``ColumnDoc.is_pii_candidate``.
"""

from __future__ import annotations

import re
from typing import Final

# ---------------------------------------------------------------------------
# Patterns
# ---------------------------------------------------------------------------

# A pragmatic email matcher — good enough for "is this an address" detection.
_EMAIL_RE: Final[re.Pattern[str]] = re.compile(
    r"^([^@\s]+)@([^@\s]+\.[^@\s]+)$"
)

# US-style SSN: 3-2-4 digits, hyphen-separated. (We also catch the 9-digit
# run-together form via the credit-card / digit-run rules below.)
_SSN_RE: Final[re.Pattern[str]] = re.compile(r"^\d{3}-\d{2}-\d{4}$")

# Credit-card-ish: 13-19 digits, optionally grouped by spaces or hyphens.
_CARD_RE: Final[re.Pattern[str]] = re.compile(
    r"^(?:\d[ -]?){12,18}\d$"
)

# Phone-ish: optional +, then 7-15 digits with the usual separators / parens.
_PHONE_RE: Final[re.Pattern[str]] = re.compile(
    r"^\+?[\d][\d\s().-]{6,17}\d$"
)

# ISO-ish dates / datetimes — explicitly NOT PII. Without this guard a value
# like "2024-01-31" (8 digits, hyphen-separated) matches _PHONE_RE and gets
# nuked. Covers "YYYY-MM-DD"[ T"HH:MM[:SS[.ffffff]]"[Z|±HH:MM]] and the common
# "D/M/Y" / "M-D-Y" short forms.
_DATE_LIKE_RE: Final[re.Pattern[str]] = re.compile(
    r"^\d{4}[-/]\d{1,2}[-/]\d{1,2}"
    r"(?:[ T]\d{1,2}:\d{2}(?::\d{2}(?:\.\d+)?)?(?:Z|[+-]\d{2}:?\d{2})?)?$"
    r"|^\d{1,2}[-/]\d{1,2}[-/]\d{2,4}$"
)

# A long opaque token: ≥20 chars, no whitespace, made of url-safe-base64 /
# hex-ish characters, AND containing a digit (so it's not just a long word).
_TOKEN_RE: Final[re.Pattern[str]] = re.compile(
    r"^[A-Za-z0-9_\-.+/=]{20,}$"
)

# Column-name fragments that strongly suggest the column holds PII.
_PII_NAME_FRAGMENTS: Final[tuple[str, ...]] = (
    "email",
    "e_mail",
    "ssn",
    "social_security",
    "phone",
    "mobile",
    "telephone",
    "dob",
    "birth",
    "password",
    "passwd",
    "secret",
    "token",
    "api_key",
    "apikey",
    "credit",
    "card",
    "cardnum",
    "iban",
    "passport",
)

_REDACTED: Final[str] = "***"

#: Cap on the length of a stored sample value. 256 chars is plenty for an
#: admin-facing "is this column an email?" preview; anything longer is a
#: blob / JSON dump and gets truncated (with a trailing ellipsis) before it
#: ever reaches ``ColumnDoc.sample_values`` / the persisted schema JSON.
MAX_SAMPLE_VALUE_LEN: Final[int] = 256

#: Above this length we don't even bother running the (anchored) PII regexes:
#: real emails / SSNs / cards / phones / tokens are all comfortably shorter,
#: so a value this long is structurally not PII — it's a blob we'll truncate.
#: Skipping the scan also caps CPU on pathological multi-megabyte cells.
_PII_SCAN_MAX_LEN: Final[int] = 4096


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------


def _looks_random_token(value: str) -> bool:
    """Heuristic: ≥20 chars, no whitespace, base64/hex alphabet, has a digit."""
    if not _TOKEN_RE.fullmatch(value):
        return False
    return any(ch.isdigit() for ch in value)


def _matches_pii_pattern(stripped: str) -> bool:
    """True iff *stripped* matches any redact-worthy PII shape.

    Caller is responsible for the length pre-check (:func:`redact_value` and
    :func:`value_looks_pii` skip absurdly long values entirely); the anchored
    regexes here are cheap on anything short enough to plausibly be PII.
    """
    if _EMAIL_RE.match(stripped):
        return True
    if _SSN_RE.match(stripped):
        return True
    # A date / datetime is never PII — bail before the phone/card matchers,
    # which would otherwise eat "2024-01-31".
    if _DATE_LIKE_RE.match(stripped):
        return False
    # Credit-card / phone tests look at the digit-bearing forms; guard with a
    # quick "mostly digits" check so ordinary text like "Order #12345" isn't
    # nuked.
    digit_count = sum(ch.isdigit() for ch in stripped)
    if digit_count >= 7:
        if _CARD_RE.match(stripped):
            return True
        if _PHONE_RE.match(stripped):
            return True
        # A bare 9-digit run is treated as an SSN.
        if re.fullmatch(r"\d{9}", stripped):
            return True
    return _looks_random_token(stripped)


def redact_value(value: object) -> str:
    """Return a PII-safe, length-capped string for *value*.

    Non-string inputs are stringified first (ints, floats, dates, bools,
    Decimals all pass through untouched once stringified). The return is
    always a ``str`` so it slots straight into ``ColumnDoc.sample_values``.

    Order of operations:

    1. Stringify + ``strip()``.
    2. If the stripped value is short enough to plausibly be PII
       (``<= _PII_SCAN_MAX_LEN``) and matches a PII pattern → ``"***"``
       (emails keep their domain → ``a***@example.com``).
    3. Otherwise, if it's longer than :data:`MAX_SAMPLE_VALUE_LEN`, return
       the first ``MAX_SAMPLE_VALUE_LEN`` chars with a trailing ``"…"``.
    4. Otherwise return the original text unchanged.

    This guarantees we never regex-scan (nor persist) a multi-megabyte cell,
    and a truncated blob is never mistaken for an email/token (anchored
    regexes won't match a cut-off string anyway, but step 2 only sees the
    full value when it's short).
    """
    text = value if isinstance(value, str) else str(value)
    stripped = text.strip()
    if not stripped:
        return text

    if len(stripped) <= _PII_SCAN_MAX_LEN and _matches_pii_pattern(stripped):
        # Emails keep the domain; everything else collapses to "***".
        email_match = _EMAIL_RE.match(stripped)
        if email_match is not None:
            local, domain = email_match.group(1), email_match.group(2)
            first = local[0] if local else ""
            return f"{first}***@{domain}"
        return _REDACTED

    if len(stripped) > MAX_SAMPLE_VALUE_LEN:
        return stripped[:MAX_SAMPLE_VALUE_LEN] + "…"

    return text


def value_looks_pii(value: object) -> bool:
    """True iff *value* (after stringify) matches a PII pattern.

    Absurdly long values are treated as blobs/JSON, not PII → ``False``
    (and never regex-scanned).
    """
    text = value if isinstance(value, str) else str(value)
    stripped = text.strip()
    if not stripped or len(stripped) > _PII_SCAN_MAX_LEN:
        return False
    return _matches_pii_pattern(stripped)


def column_name_looks_pii(column_name: str) -> bool:
    """True iff *column_name* contains a known PII-bearing fragment."""
    lowered = column_name.lower()
    return any(fragment in lowered for fragment in _PII_NAME_FRAGMENTS)


def looks_pii(column_name: str, sample_values: list[str]) -> bool:
    """True iff the column name OR any sampled value looks PII-ish."""
    if column_name_looks_pii(column_name):
        return True
    return any(value_looks_pii(v) for v in sample_values)
