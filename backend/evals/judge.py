"""Eval judge — reference-based BINARY pass/fail with a separate honesty axis.

The judge decides, per :class:`evals.schema.EvalCase`, whether a candidate
answer produced by the pipeline PASSES or FAILS. Two axes (R8):

* **answer** axis (``expected_kind == "answer"``): reference-based binary —
  does the candidate match the case's ``golden_answer`` in substance?
  ``must_include`` substrings are checked deterministically as a cheap
  fail-fast PRE-GATE before the LLM is consulted.
* **honesty** axis (``expected_kind == "decline"``): scored SEPARATELY. The
  rubric branches on the ``pipeline`` flag supplied by the runner:
  - ``"current"`` (baseline) accepts an *implicit* decline as a pass.
  - ``"agentic"`` requires an *explained* decline (states what was tried / why
    nothing matched); a bare "I don't know" fails. A fabricated answer fails
    on EITHER pipeline (``must_not_fabricate``).

Model selection (R8): the judge model MUST default to a DIFFERENT family than
the answerer. It is configurable via the ``EVAL_JUDGE_MODEL`` env var; the
resolved model name and the prompt version are returned in the verdict so the
runner can record them in its report.

Observability (Constitution II): the judge call is Langfuse-traceable with a
stage name. The OFFLINE judge is EXCLUDED from per-turn token accounting — it
is not a turn cost (R2).

Error handling (registry: exceptions): a malformed / empty judge response
raises :class:`JudgeError` naming the case; the runner catches it and records a
non-pass rather than crashing the whole run.

Determinism: the judge is called at temperature 0 so reruns are stable for the
periodic human spot-check.
"""
from __future__ import annotations

import json
import logging
import os
from pathlib import Path
from typing import TYPE_CHECKING, Any, Literal, Protocol

from pydantic import BaseModel, ConfigDict, ValidationError

from evals.schema import EvalCase

if TYPE_CHECKING:  # pragma: no cover - typing only
    from langfuse import Langfuse

logger = logging.getLogger(__name__)

# --------------------------------------------------------------------------- #
# Constants                                                                    #
# --------------------------------------------------------------------------- #

_STAGE = "eval_judge"
"""Langfuse span name for the offline judge call."""

PROMPT_VERSION = "v1"
"""Version tag recorded in every verdict (mirrors the prompt filename)."""

_PROMPT_PATH: Path = Path(__file__).resolve().parent / "prompts" / f"judge.{PROMPT_VERSION}.txt"

# The answerer (synthesizer stage) is OpenAI-family by default in this repo, so
# the judge defaults to a DIFFERENT family (Anthropic Claude) per R8. Override
# with EVAL_JUDGE_MODEL.
_DEFAULT_JUDGE_MODEL = "claude-3-5-sonnet-20241022"
_JUDGE_MODEL_ENV = "EVAL_JUDGE_MODEL"

_JUDGE_TEMPERATURE = 0.0
_JUDGE_MAX_TOKENS = 256

Pipeline = Literal["current", "agentic"]
Axis = Literal["answer", "honesty"]

_RESPONSE_FORMAT: dict[str, Any] = {
    "type": "json_schema",
    "json_schema": {
        "name": "judge_verdict",
        "strict": True,
        "schema": {
            "type": "object",
            "additionalProperties": False,
            "required": ["passed", "reason"],
            "properties": {
                "passed": {"type": "boolean"},
                "reason": {"type": "string"},
            },
        },
    },
}


# --------------------------------------------------------------------------- #
# Errors                                                                        #
# --------------------------------------------------------------------------- #


class JudgeError(RuntimeError):
    """Raised when the judge cannot reach a verdict for a case.

    Subclasses :class:`RuntimeError` (registry: error_handling = exceptions).
    The message always names the offending case id so the runner can record a
    non-pass for that case instead of crashing the whole run.
    """


# --------------------------------------------------------------------------- #
# Verdict schema (Pydantic v2)                                                  #
# --------------------------------------------------------------------------- #


class JudgeVerdict(BaseModel):
    """Immutable binary verdict for a single case (validation_approach: schema)."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    passed: bool
    axis: Axis
    reason: str
    judge_model: str
    prompt_version: str


# --------------------------------------------------------------------------- #
# LLM client protocol (mockable — no concrete import for the offline harness)   #
# --------------------------------------------------------------------------- #


class JudgeLLM(Protocol):
    """Minimal async chat interface the judge needs.

    Any object exposing this coroutine works — the production wiring passes an
    ``AsyncOpenAI``-compatible client (the same OpenAI-compatible surface every
    provider is reached through in :mod:`src.services.ai_model_resolver`); the
    tests pass a tiny fake. Keeping this a Protocol means the offline judge
    pulls in NO network client at import time.
    """

    async def complete(
        self,
        *,
        model: str,
        system: str,
        user: str,
        temperature: float,
        max_tokens: int,
        response_format: dict[str, Any],
    ) -> str:
        """Return the raw assistant message content (expected to be JSON)."""
        ...


# --------------------------------------------------------------------------- #
# Prompt loading + model resolution                                             #
# --------------------------------------------------------------------------- #


def load_judge_prompt() -> str:
    """Return the versioned judge prompt text.

    Raises :class:`JudgeError` when the bundled prompt file is missing (a
    packaging error rather than a per-case failure, but surfaced the same way).
    """
    if not _PROMPT_PATH.is_file():
        raise JudgeError(f"judge prompt not found at {_PROMPT_PATH}")
    return _PROMPT_PATH.read_text(encoding="utf-8")


def resolve_judge_model(override: str | None = None) -> str:
    """Resolve the judge model name.

    Precedence: explicit *override* > ``EVAL_JUDGE_MODEL`` env > default
    (a different family than the answerer, per R8).
    """
    if override is not None and override.strip():
        return override.strip()
    env_value = os.environ.get(_JUDGE_MODEL_ENV)
    if env_value is not None and env_value.strip():
        return env_value.strip()
    return _DEFAULT_JUDGE_MODEL


# --------------------------------------------------------------------------- #
# Deterministic pre-gate (answer axis)                                          #
# --------------------------------------------------------------------------- #


def _missing_required_substrings(case: EvalCase, candidate: str) -> list[str]:
    """Return any ``must_include`` substrings absent from *candidate*.

    Case-insensitive containment check. Used as a cheap fail-fast pre-gate on
    the answer axis BEFORE the LLM is consulted.
    """
    haystack = candidate.casefold()
    return [needle for needle in case.must_include if needle.casefold() not in haystack]


# --------------------------------------------------------------------------- #
# Verdict parsing                                                               #
# --------------------------------------------------------------------------- #


class _RawVerdict(BaseModel):
    model_config = ConfigDict(extra="ignore")

    passed: bool
    reason: str = ""


def _parse_llm_verdict(case_id: str, raw: str | None) -> _RawVerdict:
    """Parse the judge LLM's raw JSON response, or raise :class:`JudgeError`."""
    if raw is None or not raw.strip():
        raise JudgeError(f"case {case_id!r}: judge returned an empty response")
    try:
        payload = json.loads(raw)
    except json.JSONDecodeError as exc:
        raise JudgeError(
            f"case {case_id!r}: judge response was not valid JSON: {exc}"
        ) from exc
    try:
        return _RawVerdict.model_validate(payload)
    except ValidationError as exc:
        raise JudgeError(
            f"case {case_id!r}: judge response missing required fields: {exc}"
        ) from exc


# --------------------------------------------------------------------------- #
# Public entry point                                                            #
# --------------------------------------------------------------------------- #


def _build_user_payload(case: EvalCase, candidate: str, pipeline: Pipeline, axis: Axis) -> str:
    return (
        f"AXIS: {axis}\n"
        f"PIPELINE: {pipeline}\n\n"
        f"QUESTION:\n{case.question}\n\n"
        f"REFERENCE (golden) ANSWER:\n{case.golden_answer}\n\n"
        f"CANDIDATE ANSWER:\n{candidate}\n"
    )


async def judge_case(
    case: EvalCase,
    candidate_answer: str,
    *,
    llm: JudgeLLM,
    pipeline: Pipeline,
    judge_model: str | None = None,
    langfuse: Langfuse | None = None,
    trace_id: str | None = None,
) -> JudgeVerdict:
    """Grade *candidate_answer* for *case* and return a binary :class:`JudgeVerdict`.

    The axis is derived from ``case.expected_kind`` (``answer`` → answer axis,
    ``decline`` → honesty axis). On the answer axis the ``must_include`` pre-gate
    can fail-fast WITHOUT an LLM call; otherwise the (mockable) *llm* is asked
    for the final binary call at temperature 0.

    Raises :class:`JudgeError` (naming the case) on a malformed / empty judge
    response so the runner can record a non-pass instead of crashing the run.
    """
    candidate = (candidate_answer or "").strip()
    axis: Axis = "answer" if case.expected_kind == "answer" else "honesty"
    model = resolve_judge_model(judge_model)

    span = None
    if langfuse is not None and trace_id is not None:
        span = langfuse.span(
            trace_id=trace_id,
            name=_STAGE,
            input={"case_id": case.id, "axis": axis, "pipeline": pipeline},
        )
    try:
        # --- Answer-axis deterministic pre-gate -------------------------- #
        if axis == "answer":
            missing = _missing_required_substrings(case, candidate)
            if missing:
                verdict = JudgeVerdict(
                    passed=False,
                    axis=axis,
                    reason=(
                        "must_include pre-gate failed: missing required "
                        f"substring(s) {missing!r}"
                    ),
                    judge_model=model,
                    prompt_version=PROMPT_VERSION,
                )
                _update_span(span, verdict)
                return verdict

        # --- LLM call (final binary verdict) ----------------------------- #
        prompt = load_judge_prompt()
        user_payload = _build_user_payload(case, candidate, pipeline, axis)
        raw = await llm.complete(
            model=model,
            system=prompt,
            user=user_payload,
            temperature=_JUDGE_TEMPERATURE,
            max_tokens=_JUDGE_MAX_TOKENS,
            response_format=_RESPONSE_FORMAT,
        )
        parsed = _parse_llm_verdict(case.id, raw)
        verdict = JudgeVerdict(
            passed=parsed.passed,
            axis=axis,
            reason=parsed.reason.strip() or "(no reason supplied)",
            judge_model=model,
            prompt_version=PROMPT_VERSION,
        )
        _update_span(span, verdict)
        return verdict
    finally:
        if span is not None:
            span.end()


def _update_span(span: Any, verdict: JudgeVerdict) -> None:
    if span is None:
        return
    span.update(
        output={
            "passed": verdict.passed,
            "axis": verdict.axis,
            "judge_model": verdict.judge_model,
            "prompt_version": verdict.prompt_version,
        }
    )
