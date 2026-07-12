"""Unit tests for the eval judge (T-043) — fully offline, judge LLM mocked.

Covers the verification matrix from the task:

* answer axis: a correct answer PASSES; a wrong/fabricated answer FAILS;
  a ``must_include`` miss fails the deterministic pre-gate WITHOUT an LLM call.
* honesty axis (decline cases): an IMPLICIT decline PASSES under
  ``pipeline="current"`` but FAILS under ``pipeline="agentic"``, while an
  EXPLAINED decline PASSES under both.
* the verdict carries ``judge_model`` + ``prompt_version``.
* a malformed/empty judge response raises :class:`JudgeError` naming the case.

The judge LLM is a tiny scripted fake — NO real network calls, NO real models.
All example strings are synthetic.
"""
from __future__ import annotations

import json
from typing import Any

import pytest

from evals.judge import (
    PROMPT_VERSION,
    JudgeError,
    JudgeVerdict,
    judge_case,
    load_judge_prompt,
    resolve_judge_model,
)
from evals.schema import EvalCase

# --------------------------------------------------------------------------- #
# Test doubles                                                                  #
# --------------------------------------------------------------------------- #


class ScriptedLLM:
    """Async judge-LLM fake returning a pre-baked JSON string.

    Records the system/user payloads and call count so tests can assert the
    pre-gate short-circuits the LLM and that temperature 0 is used.
    """

    def __init__(self, *, passed: bool, reason: str = "scripted") -> None:
        self._response = json.dumps({"passed": passed, "reason": reason})
        self.calls: list[dict[str, Any]] = []

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
        self.calls.append(
            {
                "model": model,
                "system": system,
                "user": user,
                "temperature": temperature,
                "max_tokens": max_tokens,
                "response_format": response_format,
            }
        )
        return self._response


class RawLLM:
    """Async judge-LLM fake returning whatever raw string it is given.

    Models the runtime reality that an LLM client may return ``None`` or a
    non-JSON body; the static return type stays ``str`` to satisfy the
    :class:`~evals.judge.JudgeLLM` Protocol while the fixture still exercises the
    judge's malformed-response error paths.
    """

    def __init__(self, raw: str | None) -> None:
        self._raw = raw
        self.calls = 0

    async def complete(
        self,
        *,
        model: str = "",
        system: str = "",
        user: str = "",
        temperature: float = 0.0,
        max_tokens: int = 0,
        response_format: dict[str, Any] | None = None,
    ) -> str:
        self.calls += 1
        return self._raw  # type: ignore[return-value]


# --------------------------------------------------------------------------- #
# Case factories (all synthetic)                                                #
# --------------------------------------------------------------------------- #


def _answer_case(**overrides: Any) -> EvalCase:
    payload: dict[str, Any] = {
        "id": "ans-01",
        "source_type": "file",
        "question": "What is the synthetic answer?",
        "expected_kind": "answer",
        "golden_answer": "The synthetic answer is 42.",
        "must_include": ["42"],
        "must_not_fabricate": True,
        "fixtures": None,
        "data_source": "synthetic",
    }
    payload.update(overrides)
    return EvalCase.model_validate(payload)


def _decline_case(**overrides: Any) -> EvalCase:
    payload: dict[str, Any] = {
        "id": "dec-01",
        "source_type": "web",
        "question": "What is the synthetic CEO's home address?",
        "expected_kind": "decline",
        "golden_answer": "I don't have that information in the sources.",
        "must_include": [],
        "must_not_fabricate": True,
        "fixtures": None,
        "data_source": "synthetic",
    }
    payload.update(overrides)
    return EvalCase.model_validate(payload)


# --------------------------------------------------------------------------- #
# Prompt + model resolution                                                     #
# --------------------------------------------------------------------------- #


def test_judge_prompt_loads_and_is_nonempty() -> None:
    text = load_judge_prompt()
    assert text.strip()
    assert "honesty" in text.lower()
    assert "answer" in text.lower()


def test_resolve_judge_model_default_differs_from_answerer() -> None:
    # Answerer family in this repo is OpenAI-compatible; default judge must be
    # a Claude-family model (R8: different family) and dated for reproducible
    # evals (not a floating, unversioned alias).
    model = resolve_judge_model(None)
    assert model
    assert model.lower().startswith("claude")
    assert not model.lower().startswith("gpt")


def test_resolve_judge_model_env_override(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("EVAL_JUDGE_MODEL", "synthetic-judge-x")
    assert resolve_judge_model(None) == "synthetic-judge-x"


def test_resolve_judge_model_explicit_override_wins(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("EVAL_JUDGE_MODEL", "from-env")
    assert resolve_judge_model("from-arg") == "from-arg"


# --------------------------------------------------------------------------- #
# Answer axis                                                                   #
# --------------------------------------------------------------------------- #


@pytest.mark.asyncio
async def test_answer_axis_correct_answer_passes() -> None:
    case = _answer_case()
    llm = ScriptedLLM(passed=True, reason="matches reference in substance")
    verdict = await judge_case(
        case,
        "Per the doc, the synthetic answer is 42.",
        llm=llm,
        pipeline="current",
    )
    assert isinstance(verdict, JudgeVerdict)
    assert verdict.passed is True
    assert verdict.axis == "answer"
    assert verdict.prompt_version == PROMPT_VERSION
    assert verdict.judge_model
    assert len(llm.calls) == 1
    assert llm.calls[0]["temperature"] == 0.0


@pytest.mark.asyncio
async def test_answer_axis_wrong_answer_fails() -> None:
    # Candidate still contains "42" so the pre-gate passes; the LLM is the one
    # that rules it a substantive mismatch.
    case = _answer_case()
    llm = ScriptedLLM(passed=False, reason="contradicts the reference")
    verdict = await judge_case(
        case,
        "The answer is 42 thousand light-years, which is wrong.",
        llm=llm,
        pipeline="current",
    )
    assert verdict.passed is False
    assert verdict.axis == "answer"
    assert len(llm.calls) == 1


@pytest.mark.asyncio
async def test_answer_axis_must_include_pregate_fails_without_llm() -> None:
    case = _answer_case(must_include=["42"])
    llm = ScriptedLLM(passed=True)  # would pass if consulted
    verdict = await judge_case(
        case,
        "The synthetic answer is seventeen.",
        llm=llm,
        pipeline="current",
    )
    assert verdict.passed is False
    assert verdict.axis == "answer"
    assert "must_include" in verdict.reason
    assert llm.calls == []  # pre-gate short-circuited the LLM


@pytest.mark.asyncio
async def test_answer_axis_must_include_case_insensitive() -> None:
    case = _answer_case(must_include=["Synthetic"])
    llm = ScriptedLLM(passed=True, reason="ok")
    verdict = await judge_case(
        case,
        "the SYNTHETIC answer is 42",
        llm=llm,
        pipeline="current",
    )
    # Pre-gate passes (case-insensitive) so the LLM is consulted and passes.
    assert verdict.passed is True
    assert len(llm.calls) == 1


# --------------------------------------------------------------------------- #
# Honesty axis — implicit vs explained x pipeline                               #
# --------------------------------------------------------------------------- #

_IMPLICIT_DECLINE = "I don't see anything about that in the sources."
_EXPLAINED_DECLINE = (
    "I searched the file and web sources for the address and found no matching "
    "record, so I cannot answer that."
)
_FABRICATED = "The address is 123 Synthetic Lane, Springfield."


@pytest.mark.asyncio
async def test_honesty_implicit_decline_passes_under_current() -> None:
    case = _decline_case()
    # Baseline rubric accepts implicit declines → judge returns passed=True.
    llm = ScriptedLLM(passed=True, reason="implicit decline accepted for baseline")
    verdict = await judge_case(case, _IMPLICIT_DECLINE, llm=llm, pipeline="current")
    assert verdict.passed is True
    assert verdict.axis == "honesty"
    # The pipeline flag must reach the prompt payload so the rubric can branch.
    assert "PIPELINE: current" in llm.calls[0]["user"]


@pytest.mark.asyncio
async def test_honesty_implicit_decline_fails_under_agentic() -> None:
    case = _decline_case()
    # Agentic rubric rejects a bare implicit decline → judge returns passed=False.
    llm = ScriptedLLM(passed=False, reason="implicit decline insufficient for agentic")
    verdict = await judge_case(case, _IMPLICIT_DECLINE, llm=llm, pipeline="agentic")
    assert verdict.passed is False
    assert verdict.axis == "honesty"
    assert "PIPELINE: agentic" in llm.calls[0]["user"]


@pytest.mark.asyncio
async def test_honesty_explained_decline_passes_under_both() -> None:
    case = _decline_case()
    for pipeline in ("current", "agentic"):
        llm = ScriptedLLM(passed=True, reason="explained decline accepted")
        verdict = await judge_case(case, _EXPLAINED_DECLINE, llm=llm, pipeline=pipeline)
        assert verdict.passed is True, pipeline
        assert verdict.axis == "honesty"


@pytest.mark.asyncio
async def test_honesty_fabrication_fails_under_both() -> None:
    case = _decline_case()
    for pipeline in ("current", "agentic"):
        # Fabrication always fails an honesty case → judge returns passed=False.
        llm = ScriptedLLM(passed=False, reason="fabricated a concrete answer")
        verdict = await judge_case(case, _FABRICATED, llm=llm, pipeline=pipeline)
        assert verdict.passed is False, pipeline
        assert verdict.axis == "honesty"


@pytest.mark.asyncio
async def test_honesty_axis_skips_must_include_pregate() -> None:
    # A decline case never applies the answer-axis must_include pre-gate even if
    # one were present; the honesty axis always reaches the LLM.
    case = _decline_case(must_include=["unreachable"])
    llm = ScriptedLLM(passed=True, reason="ok")
    verdict = await judge_case(case, _IMPLICIT_DECLINE, llm=llm, pipeline="current")
    assert verdict.axis == "honesty"
    assert len(llm.calls) == 1


# --------------------------------------------------------------------------- #
# Verdict metadata                                                              #
# --------------------------------------------------------------------------- #


@pytest.mark.asyncio
async def test_verdict_records_judge_model_and_prompt_version() -> None:
    case = _answer_case()
    llm = ScriptedLLM(passed=True, reason="ok")
    verdict = await judge_case(
        case,
        "synthetic answer is 42",
        llm=llm,
        pipeline="current",
        judge_model="synthetic-judge-9",
    )
    assert verdict.judge_model == "synthetic-judge-9"
    assert verdict.prompt_version == "v1"
    assert llm.calls[0]["model"] == "synthetic-judge-9"


@pytest.mark.asyncio
async def test_verdict_is_frozen() -> None:
    case = _answer_case()
    llm = ScriptedLLM(passed=True, reason="ok")
    verdict = await judge_case(case, "synthetic answer is 42", llm=llm, pipeline="current")
    with pytest.raises(Exception):
        verdict.passed = False


# --------------------------------------------------------------------------- #
# Error handling — malformed / empty judge responses                            #
# --------------------------------------------------------------------------- #


@pytest.mark.asyncio
async def test_empty_judge_response_raises_named_error() -> None:
    case = _answer_case(must_include=[])
    llm = RawLLM("")
    with pytest.raises(JudgeError) as exc:
        await judge_case(case, "synthetic answer is 42", llm=llm, pipeline="current")
    assert case.id in str(exc.value)


@pytest.mark.asyncio
async def test_none_judge_response_raises_named_error() -> None:
    case = _answer_case(must_include=[])
    llm = RawLLM(None)
    with pytest.raises(JudgeError) as exc:
        await judge_case(case, "synthetic answer is 42", llm=llm, pipeline="current")
    assert case.id in str(exc.value)


@pytest.mark.asyncio
async def test_non_json_judge_response_raises_named_error() -> None:
    case = _answer_case(must_include=[])
    llm = RawLLM("not json at all")
    with pytest.raises(JudgeError) as exc:
        await judge_case(case, "synthetic answer is 42", llm=llm, pipeline="current")
    assert case.id in str(exc.value)
    assert "JSON" in str(exc.value)


@pytest.mark.asyncio
async def test_missing_required_field_raises_named_error() -> None:
    case = _answer_case(must_include=[])
    llm = RawLLM(json.dumps({"reason": "no passed field"}))
    with pytest.raises(JudgeError) as exc:
        await judge_case(case, "synthetic answer is 42", llm=llm, pipeline="current")
    assert case.id in str(exc.value)
