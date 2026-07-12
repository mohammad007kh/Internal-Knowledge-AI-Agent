"""Pydantic schemas for the Source Intent API (T-023).

Mirrors ``contracts/intent-api.yaml``. Two models:

* :class:`SourceIntent` — the read/response shape returned by GET and PUT.
* :class:`SourceIntentUpdate` — the PUT request body. All fields optional;
  provided fields replace the stored value.

The PUT body's field validators reuse the STRICT-mode intent sanitizer
(T-021), so an instruction-like leading pattern ("You are…", "Ignore…",
"System:", "Assistant:") or a cap violation raises
:class:`IntentSanitizationError` — a :class:`ValueError` subclass — which
FastAPI surfaces as a ``422`` naming the offending field. The 422 body
names the field and carries a clean message; it never echoes the raw
instruction-like payload verbatim.
"""

from __future__ import annotations

from datetime import datetime
from typing import Any, Literal
from uuid import UUID

from pydantic import BaseModel, ConfigDict, field_validator

from src.services.intent_sanitizer import (
    sanitize_out_of_scope,
    sanitize_purpose,
    sanitize_question_list,
)


class CrossSourceHint(BaseModel):
    """A single ``cross_source_hints`` entry: a topic mapped to another source.

    Admin-authored in v1 (never AI-written). ``extra='forbid'`` so a typo'd
    key surfaces as a 422 at the boundary rather than silently dropping.
    """

    model_config = ConfigDict(extra="forbid")

    topic: str
    source_id: UUID


class SourceIntent(BaseModel):
    """Response shape for GET / PUT ``/sources/{source_id}/intent``.

    Built from :meth:`SourceRepository.get_intent`'s dict (the six intent
    columns). Only ``intent_status`` is required; every other field is
    nullable, matching the contract and the DB's expand-only columns.
    """

    model_config = ConfigDict(extra="forbid")

    purpose: str | None = None
    example_questions: list[str] | None = None
    out_of_scope: list[str] | None = None
    cross_source_hints: list[CrossSourceHint] | None = None
    intent_status: Literal["user_set", "pending_ai", "ai_set"]
    intent_updated_at: datetime | None = None


class SourceIntentUpdate(BaseModel):
    """PUT request body — admin review/edit of a source's intent.

    All fields optional: a provided field replaces the stored value; an
    omitted field is left untouched. ``purpose`` / ``example_questions`` /
    ``out_of_scope`` pass through the STRICT sanitizer in their validators so
    instruction-like text or a cap violation raises → 422. The sanitizer also
    enforces the caps (purpose ≤ 500 chars, example_questions ≤ 5,
    out_of_scope ≤ 10), so they are the single source of truth — no duplicate
    ``max_length`` / ``max_items`` here.

    ``extra='forbid'`` rejects unknown keys so a client typo fails loudly.
    """

    model_config = ConfigDict(extra="forbid")

    purpose: str | None = None
    example_questions: list[str] | None = None
    out_of_scope: list[str] | None = None
    cross_source_hints: list[CrossSourceHint] | None = None

    @field_validator("purpose")
    @classmethod
    def _sanitize_purpose(cls, value: str | None) -> str | None:
        """STRICT sanitize ``purpose``; pass ``None`` through untouched.

        ``None`` means "field not provided" (the repo leaves it alone), so we
        must not coerce it to ``""``. A provided value is trimmed/validated;
        an instruction-like or over-cap value raises (→ 422).
        """
        if value is None:
            return None
        return sanitize_purpose(value, strict=True)

    @field_validator("example_questions")
    @classmethod
    def _sanitize_example_questions(
        cls, value: list[str] | None
    ) -> list[str] | None:
        if value is None:
            return None
        return sanitize_question_list(value, strict=True)

    @field_validator("out_of_scope")
    @classmethod
    def _sanitize_out_of_scope(cls, value: list[str] | None) -> list[str] | None:
        if value is None:
            return None
        return sanitize_out_of_scope(value, strict=True)

    def to_update_kwargs(self) -> dict[str, Any]:
        """Project only the explicitly-provided fields into repo kwargs.

        Uses ``exclude_unset`` so an omitted field never lands in the UPDATE
        (the repo's keyword-only signature treats absence as "leave alone").
        ``cross_source_hints`` is flattened back to plain dicts so the JSONB
        column stores the wire shape rather than Pydantic models.
        """
        provided = self.model_dump(exclude_unset=True)
        if "cross_source_hints" in provided and provided["cross_source_hints"] is not None:
            provided["cross_source_hints"] = [
                {"topic": h.topic, "source_id": str(h.source_id)}
                for h in (self.cross_source_hints or [])
            ]
        return provided
