"""SourceNamingService — turns a SourceProfile into a router-friendly name + description.

A single LLM call (resolver slot ``source_autoname``, Langfuse trace
``source_autoname``) reads the strict :class:`SourceProfile` produced by
the per-source-type profilers in :mod:`src.services.source_profiling`
and returns four discrete pieces (``summary``, ``topics``, ``intent``,
``scope``) plus a short ``name``. The SERVICE — not the LLM — assembles
the final ``description`` from those pieces using a deterministic
template the source-router prompt at
:mod:`src.prompts.source_router.v1.txt` already knows how to read:

    "<summary>. Covers: <topic1>, <topic2>, …. Useful for questions
     about <intent>. Does not contain <scope>."

Keeping the format machine-deterministic means the router behaves
predictably even as the LLM behind the scenes changes.

The service is stateless — calling it twice on the same profile produces
equivalent output (modulo LLM nondeterminism). It does NOT persist; the
admin must accept the proposal via a separate PATCH (F8 / F10).
"""

from __future__ import annotations

import json
import logging
from typing import TYPE_CHECKING, Any

from pydantic import BaseModel, ConfigDict, Field, ValidationError, field_validator

from src.prompts import load_prompt
from src.services.source_profiling.protocol import SourceProfile

if TYPE_CHECKING:
    from langfuse import Langfuse

    from src.services.ai_model_resolver import AIModelResolver

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------


_RESOLVER_STAGE: str = "source_autoname"
_LANGFUSE_TRACE_NAME: str = "source_autoname"

# Hard caps on the final accepted strings. The LLM is asked to stay well
# inside these but we re-validate after assembly so a chatty model never
# corrupts the persisted row.
_NAME_MIN_CHARS: int = 3
_NAME_MAX_CHARS: int = 60
_DESCRIPTION_MIN_CHARS: int = 50
_DESCRIPTION_MAX_CHARS: int = 400

# How many topics the LLM is allowed to surface, and how many we forward
# into the deterministic description template.
_MAX_TOPICS_IN_DESCRIPTION: int = 5

# Per-piece caps applied when truncating to fit the 400-char description.
# Order: scope → intent → summary — we shrink optional context first so
# the summary (most informative bit) survives the longest.
_TRUNCATE_ORDER: tuple[str, ...] = ("scope", "intent", "summary")


# ---------------------------------------------------------------------------
# DTOs
# ---------------------------------------------------------------------------


class _StrictModel(BaseModel):
    """Forbid unknown keys + freeze instances. Strict-mode Pydantic v2."""

    model_config = ConfigDict(extra="forbid", frozen=True)


class _LLMNamingPayload(_StrictModel):
    """Internal strict shape for the LLM's JSON response.

    The wire schema is locked via OpenAI structured-output (strict json_schema
    mode) so this validation is a belt-and-braces second line of defence
    that fails fast when the prompt drifts away from the contract.
    """

    name: str
    summary: str = ""
    topics: list[str] = Field(default_factory=list)
    intent: str = ""
    scope: str = ""


class AINaming(_StrictModel):
    """The final, human-presentable proposal returned by the service.

    Both fields are persistence-ready: ``name`` is short and slash-free,
    ``description`` is the assembled deterministic-template string the
    source-router prompt is designed to consume.
    """

    name: str = Field(..., min_length=_NAME_MIN_CHARS, max_length=_NAME_MAX_CHARS)
    description: str = Field(
        ...,
        min_length=_DESCRIPTION_MIN_CHARS,
        max_length=_DESCRIPTION_MAX_CHARS,
    )

    @field_validator("name")
    @classmethod
    def _validate_name(cls, value: str) -> str:
        if "/" in value or "\\" in value:
            raise ValueError("name must not contain slashes")
        return value


# ---------------------------------------------------------------------------
# Errors
# ---------------------------------------------------------------------------


class SourceNamingError(RuntimeError):
    """Raised when the LLM call fails or returns an unusable payload.

    The Celery wrapper around the auto-naming pipeline owns retry policy;
    raising a domain exception here keeps the service stateless and makes
    the failure mode unambiguous in logs / Langfuse traces.
    """


# ---------------------------------------------------------------------------
# OpenAI structured-output schema
# ---------------------------------------------------------------------------


_RESPONSE_FORMAT: dict[str, Any] = {
    "type": "json_schema",
    "json_schema": {
        "name": "source_autoname_payload",
        "strict": True,
        "schema": {
            "type": "object",
            "additionalProperties": False,
            "required": ["name", "summary", "topics", "intent", "scope"],
            "properties": {
                "name": {"type": "string"},
                "summary": {"type": "string"},
                "topics": {"type": "array", "items": {"type": "string"}},
                "intent": {"type": "string"},
                "scope": {"type": "string"},
            },
        },
    },
}


# ---------------------------------------------------------------------------
# Service
# ---------------------------------------------------------------------------


class SourceNamingService:
    """Naming step shared by every source type.

    Reads a strict :class:`SourceProfile`, calls one LLM, and returns an
    :class:`AINaming` ready to display to the admin (or to persist via
    F8's accept flow). Never persists, never mutates input.
    """

    def __init__(
        self,
        ai_model_resolver: AIModelResolver,
        langfuse: Langfuse,
    ) -> None:
        self._ai_model_resolver = ai_model_resolver
        self._langfuse = langfuse

    async def name_from_profile(self, profile: SourceProfile) -> AINaming:
        """Return an :class:`AINaming` proposal for *profile*.

        Raises:
            SourceNamingError: when the LLM call fails, returns malformed
                JSON, returns a name outside the 3-60 char window, or
                returns an empty / unfit description even after truncation.
        """
        client = await self._ai_model_resolver.resolve(_RESOLVER_STAGE)
        prompt = load_prompt(_RESOLVER_STAGE, custom=client.custom_prompt)
        user_payload = self._build_user_payload(profile)

        span = self._langfuse.span(  # type: ignore[attr-defined]
            name=_LANGFUSE_TRACE_NAME,
            input={
                "source_id": profile.source_id,
                "source_type": profile.source_type.value,
                "topic_count": len(profile.topics),
                "sample_count": profile.sample_count,
            },
        )
        try:
            try:
                response = await client.http_client.chat.completions.create(
                    model=client.model_id,
                    messages=[
                        {"role": "system", "content": prompt},
                        {"role": "user", "content": user_payload},
                    ],
                    temperature=client.temperature,
                    max_tokens=client.max_tokens,
                    response_format=_RESPONSE_FORMAT,  # type: ignore[arg-type]
                )
            except Exception as exc:  # noqa: BLE001 - wrapped into domain error
                logger.warning(
                    "SourceNamingService: LLM call failed",
                    extra={"source_id": profile.source_id},
                    exc_info=True,
                )
                raise SourceNamingError(
                    f"source_autoname LLM call failed: {exc}"
                ) from exc

            raw = self._extract_content(response, source_id=profile.source_id)
            payload = self._parse_payload(raw, source_id=profile.source_id)
            naming = self._assemble(payload, source_id=profile.source_id)
            span.update(  # type: ignore[attr-defined]
                output={
                    "name_length": len(naming.name),
                    "description_length": len(naming.description),
                }
            )
            return naming
        finally:
            span.end()  # type: ignore[attr-defined]

    # ------------------------------------------------------------------ #
    # Helpers — payload assembly                                          #
    # ------------------------------------------------------------------ #

    @staticmethod
    def _build_user_payload(profile: SourceProfile) -> str:
        """Serialise the profile fields the LLM needs into a JSON string.

        The LLM SHOULD see exactly the topics list as it stands in the
        profile — empty list stays empty, no synthetic filler. The naming
        prompt is responsible for handling the empty-topics case.
        """
        return json.dumps(
            {
                "source_type": profile.source_type.value,
                "topics": list(profile.topics),
                "entities": list(profile.entities),
                "content_types": list(profile.content_types),
                "coverage_summary": profile.coverage_summary,
                "scope_exclusions": profile.scope_exclusions,
                "sample_count": profile.sample_count,
            },
            ensure_ascii=False,
        )

    @staticmethod
    def _extract_content(response: Any, *, source_id: str) -> str:
        try:
            return response.choices[0].message.content or ""
        except (AttributeError, IndexError, TypeError) as exc:
            logger.warning(
                "SourceNamingService: LLM response missing content",
                extra={"source_id": source_id},
            )
            raise SourceNamingError(
                f"source_autoname: LLM response missing content field: {exc}"
            ) from exc

    @staticmethod
    def _parse_payload(raw: str, *, source_id: str) -> _LLMNamingPayload:
        if not raw or not raw.strip():
            raise SourceNamingError("source_autoname: LLM returned empty content")
        try:
            data = json.loads(raw)
        except json.JSONDecodeError as exc:
            logger.warning(
                "SourceNamingService: LLM returned non-JSON content",
                extra={"source_id": source_id},
            )
            raise SourceNamingError(
                f"source_autoname: LLM returned non-JSON content: {exc}"
            ) from exc
        try:
            return _LLMNamingPayload.model_validate(data)
        except ValidationError as exc:
            logger.warning(
                "SourceNamingService: LLM payload failed strict validation",
                extra={"source_id": source_id},
            )
            raise SourceNamingError(
                f"source_autoname: malformed payload: {exc}"
            ) from exc

    # ------------------------------------------------------------------ #
    # Helpers — description assembly                                      #
    # ------------------------------------------------------------------ #

    @classmethod
    def _assemble(
        cls,
        payload: _LLMNamingPayload,
        *,
        source_id: str,
    ) -> AINaming:
        """Validate the LLM pieces and render the deterministic description.

        Length policy: when the rendered description exceeds
        :data:`_DESCRIPTION_MAX_CHARS`, we truncate the optional pieces
        (scope → intent → summary) before re-rendering. If even the
        smallest possible render is still over budget, that is a hard
        failure — the LLM ignored its char limits past a recoverable
        point and we want the Celery wrapper to retry rather than
        persist a half-readable description.
        """
        name = cls._validate_name(payload.name, source_id=source_id)

        summary = payload.summary.strip()
        intent = payload.intent.strip()
        scope = payload.scope.strip()
        topics = cls._normalise_topics(payload.topics)

        if not summary:
            raise SourceNamingError(
                "source_autoname: LLM returned empty summary — refusing to "
                "build description"
            )

        description = cls._render_description(
            summary=summary,
            topics=topics,
            intent=intent,
            scope=scope,
        )

        # Fast path — already inside the cap.
        if len(description) <= _DESCRIPTION_MAX_CHARS:
            return cls._final(name=name, description=description)

        # Truncate optional pieces in priority order until we fit.
        pieces = {"summary": summary, "intent": intent, "scope": scope}
        for field in _TRUNCATE_ORDER:
            for max_len in (80, 60, 40, 20, 0):
                pieces[field] = cls._truncate(pieces[field], max_len)
                description = cls._render_description(
                    summary=pieces["summary"],
                    topics=topics,
                    intent=pieces["intent"],
                    scope=pieces["scope"],
                )
                if len(description) <= _DESCRIPTION_MAX_CHARS:
                    logger.info(
                        "SourceNamingService: truncated %s to %d chars to fit "
                        "description budget",
                        field,
                        max_len,
                        extra={"source_id": source_id},
                    )
                    return cls._final(name=name, description=description)

        raise SourceNamingError(
            "source_autoname: LLM produced an unusably long description "
            f"({len(description)} chars) and could not be truncated to fit "
            f"{_DESCRIPTION_MAX_CHARS} chars"
        )

    @staticmethod
    def _validate_name(raw: str, *, source_id: str) -> str:
        name = (raw or "").strip().strip('"').strip("'")
        if len(name) < _NAME_MIN_CHARS or len(name) > _NAME_MAX_CHARS:
            logger.warning(
                "SourceNamingService: LLM produced out-of-range name "
                "(%d chars)",
                len(name),
                extra={"source_id": source_id},
            )
            raise SourceNamingError(
                f"source_autoname: LLM returned name of {len(name)} chars; "
                f"expected {_NAME_MIN_CHARS}-{_NAME_MAX_CHARS}"
            )
        if "/" in name or "\\" in name:
            raise SourceNamingError(
                "source_autoname: LLM returned a name containing a slash"
            )
        return name

    @staticmethod
    def _normalise_topics(topics: list[str]) -> list[str]:
        cleaned: list[str] = []
        seen: set[str] = set()
        for t in topics:
            stripped = t.strip()
            if not stripped:
                continue
            key = stripped.lower()
            if key in seen:
                continue
            seen.add(key)
            cleaned.append(stripped)
            if len(cleaned) >= _MAX_TOPICS_IN_DESCRIPTION:
                break
        return cleaned

    @staticmethod
    def _truncate(value: str, max_len: int) -> str:
        """Truncate *value* to *max_len* chars without trailing punctuation.

        ``max_len == 0`` empties the field — used as the last-ditch step
        before we declare the LLM's output unusable.
        """
        if max_len <= 0:
            return ""
        if len(value) <= max_len:
            return value
        cut = value[:max_len].rstrip(" ,.;:—-")
        return cut

    @staticmethod
    def _render_description(
        *,
        summary: str,
        topics: list[str],
        intent: str,
        scope: str,
    ) -> str:
        """Assemble the deterministic-template description string."""
        parts: list[str] = []
        if summary:
            parts.append(summary.rstrip(".") + ".")
        if topics:
            parts.append("Covers: " + ", ".join(topics) + ".")
        if intent:
            parts.append("Useful for questions about " + intent.rstrip(".") + ".")
        if scope:
            parts.append("Does not contain " + scope.rstrip(".") + ".")
        return " ".join(parts).strip()

    @staticmethod
    def _final(*, name: str, description: str) -> AINaming:
        """Final defensive validation — frozen DTO ensures immutability."""
        try:
            return AINaming(name=name, description=description)
        except ValidationError as exc:
            raise SourceNamingError(
                f"source_autoname: assembled output failed validation: {exc}"
            ) from exc
