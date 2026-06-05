"""Unit tests for the headless eval runner (T-042) — fully offline.

The runner's orchestration core (:func:`evals.run.run_evals`) takes its heavy
collaborators (pipeline runner, judge, judge LLM) as INJECTED callables, so the
whole runner is exercised here with stubs — NO DB, NO network, NO real model.

Coverage (verification matrix from the task):

* **Partitioning (R8)**: ``--pipeline current`` skips every ``source_type ==
  "multi"`` case; ``--pipeline agentic`` runs all.
* **Token recording**: ``total_input_tokens`` / ``total_output_tokens`` from the
  result dict are recorded per case and summed in the aggregate.
* **Bounded termination (SC-004) → exit code**: a non-terminating stub
  (timeout / crash / loop-cap breach) marks the case ``terminated=False`` and
  forces a non-zero exit code; the offending case ids appear in
  ``non_terminating``.
* **Report emission**: :func:`evals.run.write_reports` writes a JSON sidecar +
  markdown report to the out dir.

All strings are synthetic.
"""
from __future__ import annotations

import asyncio
import json
from pathlib import Path
from typing import Any

import pytest

from evals.fixtures_loader import FixtureError
from evals.judge import JudgeError, JudgeLLM, JudgeVerdict
from evals.run import (
    AgenticPipelineUnavailableError,
    CaseResult,
    JudgeFn,
    PipelineRunner,
    main,
    partition_cases,
    run_evals,
    write_reports,
)
from evals.schema import EvalCase

# --------------------------------------------------------------------------- #
# Case factories (all synthetic)                                                #
# --------------------------------------------------------------------------- #


def _case(**overrides: Any) -> EvalCase:
    payload: dict[str, Any] = {
        "id": "case-01",
        "source_type": "file",
        "question": "What is the synthetic answer?",
        "expected_kind": "answer",
        "golden_answer": "The synthetic answer is 42.",
        "must_include": [],
        "must_not_fabricate": True,
        "fixtures": None,
        "data_source": "synthetic",
    }
    payload.update(overrides)
    return EvalCase.model_validate(payload)


# --------------------------------------------------------------------------- #
# Test doubles                                                                  #
# --------------------------------------------------------------------------- #


class _StubLLM:
    """Trivial judge-LLM stub; never actually consulted (judge is stubbed)."""

    async def complete(self, **_: Any) -> str:  # pragma: no cover - never called
        raise AssertionError("judge LLM must not be called when judge_fn is stubbed")


def _pipeline_runner(results_by_query: dict[str, dict[str, Any]]) -> PipelineRunner:
    """Build a stub ``run_pipeline`` that returns a canned result per question."""

    async def _runner(*, query: str, **_: Any) -> dict[str, Any]:
        return results_by_query[query]

    return _runner


def _judge(passed: bool, *, axis: str = "answer") -> JudgeFn:
    """Build a stub judge returning a fixed verdict, recording call count."""

    calls: list[str] = []

    async def _judge_fn(
        case: EvalCase, candidate_answer: str, *, llm: JudgeLLM, pipeline: Any
    ) -> JudgeVerdict:
        calls.append(case.id)
        return JudgeVerdict(
            passed=passed,
            axis=axis,  # type: ignore[arg-type]
            reason="stub",
            judge_model="stub-judge",
            prompt_version="v1",
        )

    _judge_fn.calls = calls  # type: ignore[attr-defined]
    return _judge_fn


async def _hanging_runner(*, query: str, **_: Any) -> dict[str, Any]:
    """A pipeline that never terminates — exercises the wall-clock deadline."""
    await asyncio.sleep(3600)
    return {}  # pragma: no cover - unreachable


# --------------------------------------------------------------------------- #
# Partitioning (R8)                                                             #
# --------------------------------------------------------------------------- #


def test_partition_current_skips_multi() -> None:
    cases = [
        _case(id="file-01", source_type="file"),
        _case(id="multi-01", source_type="multi", fixtures={"seed": "evals/fixtures/x.sql"}),
        _case(id="db-01", source_type="database"),
    ]
    selected, skipped = partition_cases(cases, "current")

    assert skipped == 1
    assert [c.id for c in selected] == ["file-01", "db-01"]


def test_partition_agentic_runs_all() -> None:
    cases = [
        _case(id="file-01", source_type="file"),
        _case(id="multi-01", source_type="multi", fixtures={"seed": "evals/fixtures/x.sql"}),
    ]
    selected, skipped = partition_cases(cases, "agentic")

    assert skipped == 0
    assert [c.id for c in selected] == ["file-01", "multi-01"]


# --------------------------------------------------------------------------- #
# Orchestration: tokens, partitioning end-to-end                                #
# --------------------------------------------------------------------------- #


@pytest.mark.asyncio
async def test_run_records_tokens_and_skips_multi_on_current() -> None:
    cases = [
        _case(id="file-01", source_type="file", question="q-file"),
        _case(
            id="multi-01",
            source_type="multi",
            question="q-multi",
            fixtures={"seed": "evals/fixtures/x.sql"},
        ),
    ]
    runner = _pipeline_runner(
        {
            "q-file": {
                "final_answer": "synthetic answer",
                "total_input_tokens": 11,
                "total_output_tokens": 7,
            }
        }
    )

    report = await run_evals(
        pipeline="current",
        cases=cases,
        compiled_graph=object(),
        session=None,
        pipeline_runner=runner,
        judge_fn=_judge(passed=True),
        judge_llm=_StubLLM(),
    )

    # Multi case skipped on the current pipeline (R8).
    assert report.skipped_multi == 1
    assert report.total_cases == 1
    assert [c.id for c in report.cases] == ["file-01"]

    # Tokens recorded from the result dict and summed in the aggregate.
    only = report.cases[0]
    assert only.input_tokens == 11
    assert only.output_tokens == 7
    assert report.total_input_tokens == 11
    assert report.total_output_tokens == 7

    # Every case terminated → exit 0.
    assert only.terminated is True
    assert only.passed is True
    assert report.non_terminating == []
    assert report.exit_code == 0


# --------------------------------------------------------------------------- #
# Bounded termination (SC-004) → non-zero exit                                  #
# --------------------------------------------------------------------------- #


@pytest.mark.asyncio
async def test_timeout_marks_non_terminating_and_forces_nonzero_exit() -> None:
    cases = [_case(id="hang-01", source_type="file", question="q-hang")]

    report = await run_evals(
        pipeline="current",
        cases=cases,
        compiled_graph=object(),
        session=None,
        pipeline_runner=_hanging_runner,
        judge_fn=_judge(passed=True),
        judge_llm=_StubLLM(),
        deadline_override=1,  # 1s wall-clock bound; the stub sleeps far longer
    )

    result = report.cases[0]
    assert result.terminated is False
    assert result.passed is False
    assert result.termination_reason is not None
    assert "timeout" in result.termination_reason
    assert report.non_terminating == ["hang-01"]
    assert report.exit_code == 1


@pytest.mark.asyncio
async def test_crashing_case_recorded_non_terminating_and_does_not_abort_run() -> None:
    cases = [
        _case(id="crash-01", source_type="file", question="q-crash"),
        _case(id="ok-01", source_type="file", question="q-ok"),
    ]

    async def _runner(*, query: str, **_: Any) -> dict[str, Any]:
        if query == "q-crash":
            raise RuntimeError("synthetic pipeline crash")
        return {"final_answer": "ok", "total_input_tokens": 3, "total_output_tokens": 2}

    report = await run_evals(
        pipeline="current",
        cases=cases,
        compiled_graph=object(),
        session=None,
        pipeline_runner=_runner,
        judge_fn=_judge(passed=True),
        judge_llm=_StubLLM(),
    )

    # The crashing case is caught and recorded; the run still completes the
    # second case and exits non-zero.
    assert report.total_cases == 2
    crashed = next(c for c in report.cases if c.id == "crash-01")
    assert crashed.terminated is False
    assert "RuntimeError" in (crashed.termination_reason or "")

    survivor = next(c for c in report.cases if c.id == "ok-01")
    assert survivor.terminated is True
    assert survivor.input_tokens == 3

    assert report.non_terminating == ["crash-01"]
    assert report.exit_code == 1


@pytest.mark.asyncio
async def test_loop_cap_breach_marks_non_terminating() -> None:
    cases = [_case(id="loop-01", source_type="file", question="q-loop")]
    runner = _pipeline_runner(
        {
            "q-loop": {
                "final_answer": "ran out of budget",
                "total_input_tokens": 99,
                "total_output_tokens": 5,
                "loop_cap_breached": True,
            }
        }
    )

    report = await run_evals(
        pipeline="current",
        cases=cases,
        compiled_graph=object(),
        session=None,
        pipeline_runner=runner,
        judge_fn=_judge(passed=True),
        judge_llm=_StubLLM(),
    )

    result = report.cases[0]
    assert result.terminated is False
    assert "loop-cap" in (result.termination_reason or "")
    # Tokens consumed up to the breach are still recorded.
    assert result.input_tokens == 99
    assert report.exit_code == 1


# --------------------------------------------------------------------------- #
# Honesty axis scored separately                                               #
# --------------------------------------------------------------------------- #


@pytest.mark.asyncio
async def test_honesty_axis_aggregated_separately() -> None:
    cases = [
        _case(id="ans-01", source_type="file", expected_kind="answer", question="q-ans"),
        _case(
            id="dec-01",
            source_type="file",
            expected_kind="decline",
            question="q-dec",
            golden_answer="I don't see anything about that in the sources.",
        ),
    ]
    runner = _pipeline_runner(
        {
            "q-ans": {"final_answer": "a", "total_input_tokens": 1, "total_output_tokens": 1},
            "q-dec": {"final_answer": "d", "total_input_tokens": 1, "total_output_tokens": 1},
        }
    )

    report = await run_evals(
        pipeline="current",
        cases=cases,
        compiled_graph=object(),
        session=None,
        pipeline_runner=runner,
        judge_fn=_judge(passed=True),
        judge_llm=_StubLLM(),
    )

    assert report.answer_total == 1
    assert report.answer_passed == 1
    assert report.honesty_total == 1
    assert report.honesty_passed == 1


# --------------------------------------------------------------------------- #
# Limit (no silent caps — dropped cases logged by run_evals)                    #
# --------------------------------------------------------------------------- #


@pytest.mark.asyncio
async def test_limit_truncates_selected_cases() -> None:
    cases = [
        _case(id="c-01", source_type="file", question="q1"),
        _case(id="c-02", source_type="file", question="q2"),
        _case(id="c-03", source_type="file", question="q3"),
    ]
    runner = _pipeline_runner(
        {q: {"final_answer": "x", "total_input_tokens": 0, "total_output_tokens": 0}
         for q in ("q1", "q2", "q3")}
    )

    report = await run_evals(
        pipeline="current",
        cases=cases,
        compiled_graph=object(),
        session=None,
        pipeline_runner=runner,
        judge_fn=_judge(passed=True),
        judge_llm=_StubLLM(),
        limit=2,
    )

    assert report.total_cases == 2
    assert [c.id for c in report.cases] == ["c-01", "c-02"]


# --------------------------------------------------------------------------- #
# Report emission                                                              #
# --------------------------------------------------------------------------- #


def _result(**overrides: Any) -> CaseResult:
    payload: dict[str, Any] = {
        "id": "case-01",
        "source_type": "file",
        "expected_kind": "answer",
        "passed": True,
        "terminated": True,
        "termination_reason": None,
        "input_tokens": 10,
        "output_tokens": 5,
        "judge_model": "stub-judge",
        "judge_prompt_version": "v1",
    }
    payload.update(overrides)
    return CaseResult(**payload)


@pytest.mark.asyncio
async def test_write_reports_emits_json_and_markdown(tmp_path: Path) -> None:
    cases = [_case(id="rep-01", source_type="file", question="q-rep")]
    runner = _pipeline_runner(
        {"q-rep": {"final_answer": "a", "total_input_tokens": 4, "total_output_tokens": 2}}
    )

    report = await run_evals(
        pipeline="current",
        cases=cases,
        compiled_graph=object(),
        session=None,
        pipeline_runner=runner,
        judge_fn=_judge(passed=True),
        judge_llm=_StubLLM(),
    )

    json_path, md_path = write_reports(report, tmp_path)

    assert json_path.exists()
    assert md_path.exists()
    assert json_path.suffix == ".json"
    assert md_path.suffix == ".md"
    assert json_path.name.endswith("-current.json")

    payload = json.loads(json_path.read_text(encoding="utf-8"))
    assert payload["pipeline"] == "current"
    assert payload["exit_code"] == 0
    assert payload["total_cases"] == 1
    assert payload["cases"][0]["id"] == "rep-01"
    assert payload["cases"][0]["input_tokens"] == 4

    md = md_path.read_text(encoding="utf-8")
    assert "Eval run" in md
    assert "rep-01" in md
    assert "Honesty axis" in md


def test_write_reports_nonzero_exit_renders_fail(tmp_path: Path) -> None:
    from evals.run import RunReport

    report = RunReport(
        pipeline="current",
        timestamp="20260604T000000Z",
        judge_model="stub-judge",
        total_cases=1,
        skipped_multi=0,
        passed=0,
        answer_passed=0,
        answer_total=1,
        honesty_passed=0,
        honesty_total=0,
        non_terminating=["bad-01"],
        total_input_tokens=0,
        total_output_tokens=0,
        cases=[_result(id="bad-01", passed=False, terminated=False, termination_reason="timeout")],
    )

    assert report.exit_code == 1
    _json_path, md_path = write_reports(report, tmp_path)
    md = md_path.read_text(encoding="utf-8")
    assert "FAIL" in md
    assert "bad-01" in md


def test_write_reports_pass_cell_is_plain_text(tmp_path: Path) -> None:
    """FIX 1: the markdown pass column renders PASS/FAIL text, never emoji
    (CI log parsers choke on non-ASCII table cells)."""
    from evals.run import RunReport

    report = RunReport(
        pipeline="current",
        timestamp="20260604T010000Z",
        judge_model="stub-judge",
        total_cases=2,
        skipped_multi=0,
        passed=1,
        answer_passed=1,
        answer_total=2,
        honesty_passed=0,
        honesty_total=0,
        non_terminating=[],
        total_input_tokens=0,
        total_output_tokens=0,
        cases=[
            _result(id="pass-01", passed=True),
            _result(id="fail-01", passed=False),
        ],
    )

    _json_path, md_path = write_reports(report, tmp_path)
    md = md_path.read_text(encoding="utf-8")

    assert "| PASS |" in md
    assert "| FAIL |" in md
    assert "✅" not in md
    assert "❌" not in md


# --------------------------------------------------------------------------- #
# FIX 4(a): --pipeline agentic before Slice C → exit code 2                      #
# --------------------------------------------------------------------------- #


def test_main_agentic_unavailable_exits_2(monkeypatch: pytest.MonkeyPatch) -> None:
    """main(['--pipeline','agentic']) maps AgenticPipelineUnavailableError to
    a clean exit code 2 (distinct from the 0/1 termination contract)."""

    async def _boom(_args: Any) -> Any:
        raise AgenticPipelineUnavailableError("agentic pipeline not available")

    monkeypatch.setattr("evals.run._run_with_real_wiring", _boom)

    rc = main(["--pipeline", "agentic"])

    assert rc == 2


# --------------------------------------------------------------------------- #
# FIX 4(b): FixtureError path — case fails, subsequent case still completes      #
# --------------------------------------------------------------------------- #


@pytest.mark.asyncio
async def test_fixture_error_marks_case_and_run_continues(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    cases = [
        _case(
            id="fix-01",
            source_type="database",
            question="q-fix",
            fixtures={"seed": "evals/fixtures/x.sql"},
        ),
        _case(id="ok-02", source_type="file", question="q-ok"),
    ]

    def _explode(*_a: Any, **_k: Any) -> Any:
        raise FixtureError("case 'fix-01' fixture seed failed")

    # ephemeral_fixture is resolved inside _resolve_source_ids; patch it there.
    monkeypatch.setattr("evals.run.ephemeral_fixture", _explode)

    runner = _pipeline_runner(
        {"q-ok": {"final_answer": "ok", "total_input_tokens": 2, "total_output_tokens": 1}}
    )

    report = await run_evals(
        pipeline="current",
        cases=cases,
        compiled_graph=object(),
        session=object(),  # non-None so the fixture branch is taken
        pipeline_runner=runner,
        judge_fn=_judge(passed=True),
        judge_llm=_StubLLM(),
    )

    failed = next(c for c in report.cases if c.id == "fix-01")
    assert failed.terminated is False
    assert failed.passed is False
    assert "fixture error" in (failed.termination_reason or "")

    survivor = next(c for c in report.cases if c.id == "ok-02")
    assert survivor.terminated is True
    assert survivor.passed is True

    assert report.non_terminating == ["fix-01"]
    assert report.exit_code == 1


# --------------------------------------------------------------------------- #
# FIX 4(c): JudgeError path — terminated, not a pass, exit code still 0          #
# --------------------------------------------------------------------------- #


@pytest.mark.asyncio
async def test_judge_error_terminates_without_pass_and_exit_zero() -> None:
    cases = [_case(id="judge-01", source_type="file", question="q-judge")]
    runner = _pipeline_runner(
        {"q-judge": {"final_answer": "a", "total_input_tokens": 1, "total_output_tokens": 1}}
    )

    async def _failing_judge(
        case: EvalCase, candidate_answer: str, *, llm: JudgeLLM, pipeline: Any
    ) -> JudgeVerdict:
        raise JudgeError(f"case {case.id!r}: judge could not reach a verdict")

    report = await run_evals(
        pipeline="current",
        cases=cases,
        compiled_graph=object(),
        session=None,
        pipeline_runner=runner,
        judge_fn=_failing_judge,
        judge_llm=_StubLLM(),
    )

    result = report.cases[0]
    # Judge failure is NOT a termination failure: the case terminated, just
    # didn't pass, so the run exit code stays 0.
    assert result.terminated is True
    assert result.passed is False
    assert report.non_terminating == []
    assert report.exit_code == 0


# --------------------------------------------------------------------------- #
# FIX 4(d): prior-run delta rendered in the second markdown report               #
# --------------------------------------------------------------------------- #


def test_second_report_renders_prior_run_comparison(tmp_path: Path) -> None:
    from evals.run import RunReport

    def _make(stamp: str, passed: int) -> RunReport:
        return RunReport(
            pipeline="current",
            timestamp=stamp,
            judge_model="stub-judge",
            total_cases=2,
            skipped_multi=0,
            passed=passed,
            answer_passed=passed,
            answer_total=2,
            honesty_passed=0,
            honesty_total=0,
            non_terminating=[],
            total_input_tokens=0,
            total_output_tokens=0,
            cases=[_result(id="a-01"), _result(id="b-01")],
        )

    # First (prior) run, then a chronologically later run into the same dir.
    write_reports(_make("20260604T000000Z", passed=1), tmp_path)
    _json_path, md_path = write_reports(_make("20260604T010000Z", passed=2), tmp_path)

    md = md_path.read_text(encoding="utf-8")
    assert "Prior run pass rate" in md
    assert "1/2" in md  # the prior run's pass rate is surfaced


# --------------------------------------------------------------------------- #
# FIX 4(e): _coerce_tokens unit coverage                                         #
# --------------------------------------------------------------------------- #


@pytest.mark.parametrize(
    ("value", "expected"),
    [
        (None, 0),
        ("abc", 0),
        (-1, 0),
        (0, 0),
        (5, 5),
    ],
)
def test_coerce_tokens(value: Any, expected: int) -> None:
    from evals.run import _coerce_tokens

    assert _coerce_tokens(value) == expected
