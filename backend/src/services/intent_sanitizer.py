"""Intent prompt-hygiene sanitization (Security Rule 1, HIGH).

Source *intent* fields — ``purpose``, ``example_questions``,
``out_of_scope`` — are injected verbatim into downstream LLM prompts.
Some of that text is admin-authored (trusted) and some is AI-proposed
(model output); EITHER could carry an instruction-like leading string
("Ignore previous…", "System: …") that, once it lands inside a prompt,
could attempt to hijack the agent. This module is the single, pure
choke-point that detects those patterns and enforces the length caps.

It is deliberately I/O-free, DB-free and LLM-free: every function is a
deterministic transform over its arguments, exhaustively unit-tested,
and never mutates its inputs (immutability rule — new strings/lists are
always returned).

Two modes share one predicate and one set of caps:

* **strict mode** (PUT ``/intent`` schema validation, T-023): any
  violating field/item raises :class:`IntentSanitizationError`, which the
  API surfaces as ``422`` so the admin sees exactly what was rejected.
* **lenient mode** (AI proposal-task output validation, T-022): violating
  *items* are silently dropped and clean items kept, so a partially-bad
  AI draft still yields value. ``purpose`` is never AI-written, but for
  symmetry lenient ``sanitize_purpose`` drops a violating purpose to the
  empty string rather than raising.

Caps (single source of truth, imported by both T-022 and T-023):

* ``purpose`` ≤ :data:`PURPOSE_MAX_CHARS` (500) chars
* ``example_questions`` ≤ :data:`MAX_EXAMPLE_QUESTIONS` (5) items
* ``out_of_scope`` ≤ :data:`MAX_OUT_OF_SCOPE` (10) items
"""

from __future__ import annotations

import unicodedata
from collections.abc import Iterable, Sequence

# ---------------------------------------------------------------------------
# Constants — single source of truth (shared by PUT schema + proposal task)
# ---------------------------------------------------------------------------


PURPOSE_MAX_CHARS: int = 500
MAX_EXAMPLE_QUESTIONS: int = 5
MAX_OUT_OF_SCOPE: int = 10

#: Instruction-like leading patterns. Matched case-insensitively against the
#: trimmed text. Kept as a module constant so tests (and any future caller)
#: can assert against the exact set rather than a hard-coded literal.
INSTRUCTION_LIKE_PREFIXES: tuple[str, ...] = (
    "ignore",
    "you are",
    "system:",
    "assistant:",
)

#: Zero-width / invisible characters an attacker can prepend to dodge the
#: leading-prefix check (ZWSP, ZWNJ, ZWJ, BOM / ZWNBSP). Stripped from the
#: front of the text before the ``startswith`` match.
_INVISIBLE: str = "​‌‍﻿"


# ---------------------------------------------------------------------------
# Errors
# ---------------------------------------------------------------------------


class IntentSanitizationError(ValueError):
    """Raised in *strict* mode when a field/item fails sanitization.

    Subclasses :class:`ValueError` so it slots cleanly into Pydantic
    validators (T-023), where a raised ``ValueError`` becomes a ``422``.
    """


# ---------------------------------------------------------------------------
# Predicate
# ---------------------------------------------------------------------------


def is_instruction_like(text: str | None) -> bool:
    """Return ``True`` if *text* begins with an instruction-like pattern.

    The text is NFKC-normalized (folding unicode homoglyphs / compatibility
    forms onto their canonical ASCII), stripped of leading whitespace and
    leading zero-width / invisible characters, then casefolded before the
    comparison — so leading whitespace, mixed case, zero-width prefixes, and
    homoglyph tricks do not let a pattern slip through. ``None`` and
    blank/whitespace-only strings are NOT instruction-like (there is nothing
    to inject) and return ``False``.

    Examples:
        >>> is_instruction_like("  IGNORE previous")
        True
        >>> is_instruction_like("System: do X")
        True
        >>> is_instruction_like("This source holds architectural workspaces")
        False
        >>> is_instruction_like(None)
        False
    """
    if text is None:
        return False
    # NFKC folds compatibility/homoglyph forms; strip whitespace, then strip
    # leading invisible chars, then strip again (an invisible char can wrap
    # trailing whitespace), then casefold for a robust caseless match.
    normalized = (
        unicodedata.normalize("NFKC", text)
        .strip()
        .lstrip(_INVISIBLE)
        .strip()
        .casefold()
    )
    if not normalized:
        return False
    return any(normalized.startswith(prefix) for prefix in INSTRUCTION_LIKE_PREFIXES)


# ---------------------------------------------------------------------------
# Field sanitizers
# ---------------------------------------------------------------------------


def sanitize_purpose(value: str | None, *, strict: bool = True) -> str:
    """Sanitize the single ``purpose`` string.

    Trims the value, enforces :data:`PURPOSE_MAX_CHARS`, and rejects
    instruction-like leading patterns.

    Args:
        value: The raw purpose, or ``None`` (treated as empty).
        strict: When ``True`` (PUT path), an over-length or
            instruction-like value raises :class:`IntentSanitizationError`.
            When ``False`` (proposal-task path), a violating value yields
            the empty string and a clean value is returned trimmed.

    Returns:
        The trimmed, validated purpose (``""`` for an empty/dropped value).

    Raises:
        IntentSanitizationError: in strict mode when the value exceeds the
            length cap or matches an instruction-like leading pattern.
    """
    trimmed = (value or "").strip()

    if not trimmed:
        return ""

    if len(trimmed) > PURPOSE_MAX_CHARS:
        if strict:
            raise IntentSanitizationError(
                f"purpose exceeds {PURPOSE_MAX_CHARS} characters "
                f"(got {len(trimmed)})"
            )
        return ""

    if is_instruction_like(trimmed):
        if strict:
            raise IntentSanitizationError(
                "purpose starts with an instruction-like pattern and was rejected"
            )
        return ""

    return trimmed


def sanitize_question_list(
    items: Iterable[str] | None,
    *,
    strict: bool = True,
) -> list[str]:
    """Sanitize the ``example_questions`` list (cap :data:`MAX_EXAMPLE_QUESTIONS`)."""
    return _sanitize_item_list(
        items,
        max_items=MAX_EXAMPLE_QUESTIONS,
        field_name="example_questions",
        strict=strict,
    )


def sanitize_out_of_scope(
    items: Iterable[str] | None,
    *,
    strict: bool = True,
) -> list[str]:
    """Sanitize the ``out_of_scope`` list (cap :data:`MAX_OUT_OF_SCOPE`)."""
    return _sanitize_item_list(
        items,
        max_items=MAX_OUT_OF_SCOPE,
        field_name="out_of_scope",
        strict=strict,
    )


# ---------------------------------------------------------------------------
# Shared list sanitizer
# ---------------------------------------------------------------------------


def _sanitize_item_list(
    items: Iterable[str] | None,
    *,
    max_items: int,
    field_name: str,
    strict: bool,
) -> list[str]:
    """Sanitize a list of intent items under a shared policy.

    Each item is trimmed; blank items are dropped in both modes (they carry
    no signal and never trip the predicate). Item count is checked against
    *max_items* and each surviving item against :func:`is_instruction_like`.

    Strict mode raises :class:`IntentSanitizationError` on the first
    violation (count overflow or instruction-like item). Lenient mode drops
    instruction-like items and, after cleaning, truncates to *max_items*.

    The input is never mutated; a brand-new list is always returned.
    """
    materialized: Sequence[str] = list(items or [])

    # Strict mode validates the raw count first so the admin's 422 names the
    # real problem ("too many items") rather than a side effect of dropping.
    if strict and len(materialized) > max_items:
        raise IntentSanitizationError(
            f"{field_name} has {len(materialized)} items; max is {max_items}"
        )

    cleaned: list[str] = []
    for item in materialized:
        trimmed = (item or "").strip()
        if not trimmed:
            # Blank/whitespace-only entries are noise in either mode.
            continue
        if is_instruction_like(trimmed):
            if strict:
                raise IntentSanitizationError(
                    f"{field_name} item starts with an instruction-like "
                    f"pattern and was rejected: {trimmed!r}"
                )
            # Lenient: drop the offending item, keep the rest.
            continue
        cleaned.append(trimmed)

    # Lenient mode may still hold more than the cap once blanks are removed;
    # truncate to the cap. Strict mode already validated the count above.
    if not strict and len(cleaned) > max_items:
        cleaned = cleaned[:max_items]

    return cleaned
