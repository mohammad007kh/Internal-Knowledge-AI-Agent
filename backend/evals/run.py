"""Headless eval runner (T-042) — `python -m evals.run --pipeline current|agentic`.

Invokes the pipeline HEADLESSLY (no HTTP/SSE), loops the frozen JSON-golden
cases (T-040), provisions DB fixtures for ``multi``/``database`` cases (T-041),
records per-case token cost, ENFORCES bounded termination (SC-004), scores each
candidate with the judge (T-043), and writes a JSON sidecar + markdown report to
``backend/evals/runs/``.

Partitioning (R8 — load-bearing):

* ``--pipeline current`` SKIPS every case whose ``source_type == "multi"``. The
  baseline scores only the single-source + honesty subsets (SC-005 scope).
* ``--pipeline agentic`` runs ALL cases. The agentic graph does not exist until
  Slice C (T-058); until it lands this runner exits with a clear
  "agentic pipeline not available" error rather than crashing.

Exit-code contract (quickstart §7 — verbatim):

* exit ``0`` iff EVERY executed case ``terminated == True``;
* exit ``1`` if ANY case did not terminate within limits / crashed — the
  offending case id(s) are named on stderr.

Bounded termination (SC-004): each per-case pipeline invocation is wrapped in
``asyncio.wait_for`` with a wall-clock deadline (``AGENT_TURN_DEADLINE_SECS`` if
set, else a hard runner default). A timeout, an uncaught exception, or a result
that signals a loop-cap breach marks the case ``terminated=False`` with a
reason; the run still completes and exits non-zero.

Design seam: the orchestration core (:func:`run_evals`) takes its heavy
collaborators (graph builder, pipeline runner, judge, session factory, judge
LLM) as INJECTED callables so the unit test drives the whole runner fully
offline with mocks — no DB, no network, no real model. :func:`main` wires the
real implementations from the DI container.
"""
from __future__ import annotations

import argparse
import asyncio
import json
import logging
import sys
import uuid
from collections.abc import Sequence
from contextlib import AbstractAsyncContextManager
from dataclasses import asdict, dataclass, field
from datetime import UTC, datetime
from pathlib import Path
from typing import Any, Protocol

from evals.fixtures_loader import FixtureError, FixtureHandle, ephemeral_fixture
from evals.judge import JudgeError, JudgeLLM, JudgeVerdict, judge_case, resolve_judge_model
from evals.schema import EvalCase, load_all_cases

logger = logging.getLogger(__name__)

# --------------------------------------------------------------------------- #
# Constants                                                                     #
# --------------------------------------------------------------------------- #

PipelineName = str  # "current" | "agentic" — validated by argparse choices.

#: Wall-clock ceiling per case when ``AGENT_TURN_DEADLINE_SECS`` is unset. Keeps
#: a hung/non-terminating case from blocking the whole run indefinitely.
DEFAULT_TURN_DEADLINE_SECS: int = 120

#: Synthetic identity used for every headless eval invocation (no real user).
_EVAL_OWNER_ID = uuid.UUID("00000000-0000-0000-0000-0000000000e7")

_DEFAULT_CASES_DIR = "evals/cases"
_DEFAULT_OUT_DIR = "evals/runs"

#: Result-dict keys carrying per-turn token cost (set by the pipeline state).
_INPUT_TOKENS_KEY = "total_input_tokens"
_OUTPUT_TOKENS_KEY = "total_output_tokens"
_FINAL_ANSWER_KEY = "final_answer"
#: A truthy value under this key in the result dict signals a loop-cap breach
#: (the agentic graph sets it when it hits a hard cap without terminating).
_LOOP_CAP_KEY = "loop_cap_breached"


class AgenticPipelineUnavailableError(RuntimeError):
    """Raised when ``--pipeline agentic`` is requested before Slice C lands.

    Subclasses :class:`RuntimeError` (registry: error_handling = exceptions).
    Kept distinct so :func:`main` can map it to a clean non-zero exit with a
    human-readable message instead of a traceback.
    """


# --------------------------------------------------------------------------- #
# Injectable collaborator protocols                                             #
# --------------------------------------------------------------------------- #


class PipelineRunner(Protocol):
    """Headless single-turn pipeline invocation (mirrors ``run_pipeline``)."""

    async def __call__(
        self,
        *,
        compiled_graph: Any,
        session_id: str,
        user_id: str,
        query: str,
        source_ids: list[str],
        trace_id: str,
    ) -> dict[str, Any]:
        ...


class JudgeFn(Protocol):
    """Binary pass/fail judge (mirrors :func:`evals.judge.judge_case`)."""

    async def __call__(
        self,
        case: EvalCase,
        candidate_answer: str,
        *,
        llm: JudgeLLM,
        pipeline: Any,
    ) -> JudgeVerdict:
        ...


# --------------------------------------------------------------------------- #
# Result records (immutable)                                                    #
# --------------------------------------------------------------------------- #


@dataclass(frozen=True)
class CaseResult:
    """Per-case outcome recorded in the JSON sidecar + markdown report."""

    id: str
    source_type: str
    expected_kind: str
    passed: bool
    terminated: bool
    termination_reason: str | None
    input_tokens: int
    output_tokens: int
    judge_model: str
    judge_prompt_version: str | None


@dataclass(frozen=True)
class RunReport:
    """Aggregate run outcome + the per-case records."""

    pipeline: str
    timestamp: str
    judge_model: str
    total_cases: int
    skipped_multi: int
    passed: int
    answer_passed: int
    answer_total: int
    honesty_passed: int
    honesty_total: int
    non_terminating: list[str]
    total_input_tokens: int
    total_output_tokens: int
    cases: list[CaseResult] = field(default_factory=list)

    @property
    def exit_code(self) -> int:
        """0 iff every executed case terminated within limits, else 1 (SC-004)."""
        return 0 if not self.non_terminating else 1


# --------------------------------------------------------------------------- #
# Partitioning (R8)                                                             #
# --------------------------------------------------------------------------- #


def partition_cases(cases: Sequence[EvalCase], pipeline: str) -> tuple[list[EvalCase], int]:
    """Select the cases this *pipeline* should execute.

    ``current`` runs only the single-source + honesty subsets — every
    ``source_type == "multi"`` case is skipped (it first executes against the
    agentic pipeline, measuring SC-001 capability, not regression). ``agentic``
    runs all cases.

    Returns ``(selected, skipped_multi_count)``. The skipped count is logged by
    the caller (no silent caps — coding-style).
    """
    if pipeline == "agentic":
        return list(cases), 0
    selected = [c for c in cases if c.source_type != "multi"]
    skipped = len(cases) - len(selected)
    return selected, skipped


def _turn_deadline_secs(deadline_override: int | None) -> int:
    """Resolve the per-case wall-clock deadline.

    Precedence: explicit *deadline_override* > ``AGENT_TURN_DEADLINE_SECS`` (via
    settings) > :data:`DEFAULT_TURN_DEADLINE_SECS`. A non-positive configured
    value falls back to the hard default so a misconfig can never disable the
    bound entirely.
    """
    if deadline_override is not None and deadline_override > 0:
        return deadline_override
    configured: int | None = None
    try:  # settings is optional in the offline test path
        from src.core.config import settings  # noqa: PLC0415

        configured = settings.AGENT_TURN_DEADLINE_SECS
    except Exception:  # pragma: no cover - defensive (settings unavailable)
        configured = None
    if configured is not None and configured > 0:
        return configured
    return DEFAULT_TURN_DEADLINE_SECS


# --------------------------------------------------------------------------- #
# Per-case execution                                                           #
# --------------------------------------------------------------------------- #


def _coerce_tokens(value: Any) -> int:
    """Best-effort coerce a token field to a non-negative int (0 on absence)."""
    try:
        tokens = int(value)
    except (TypeError, ValueError):
        return 0
    return max(tokens, 0)


async def _resolve_source_ids(
    case: EvalCase,
    *,
    session: Any | None,
) -> tuple[list[str], AbstractAsyncContextManager[FixtureHandle] | None]:
    """Return ``(source_ids, fixture_cm)`` for *case*.

    When the case declares ``fixtures`` we MUST open an ephemeral fixture to get
    a temp ``source_id`` — the returned context manager is entered by the caller
    so teardown is guaranteed. Otherwise there is no fixture and the case runs
    against its declared (synthetic) source set, which for the headless harness
    is empty (the pipeline targets the seeded source or none).
    """
    if case.fixtures is None:
        return [], None
    if session is None:
        raise FixtureError(
            f"case {case.id!r} requires fixtures but no DB session was provided"
        )
    fixture_cm = ephemeral_fixture(case, session, owner_id=_EVAL_OWNER_ID)
    # The empty source_ids list is a placeholder only: in the fixture branch the
    # caller (_execute_case) enters fixture_cm and passes the temp source_id
    # produced once the context manager yields. This empty list is never handed
    # to the pipeline.
    return [], fixture_cm


async def _execute_case(
    case: EvalCase,
    *,
    pipeline: str,
    compiled_graph: Any,
    session: Any | None,
    pipeline_runner: PipelineRunner,
    judge_fn: JudgeFn,
    judge_llm: JudgeLLM,
    deadline_secs: int,
) -> CaseResult:
    """Run one case end-to-end: fixture → pipeline → bounded check → judge.

    A timeout, an uncaught exception, or a loop-cap breach yields
    ``terminated=False`` with a reason; the case never aborts the whole run.
    """
    judge_model = resolve_judge_model(None)
    source_ids: list[str] = []
    fixture_cm: AbstractAsyncContextManager[FixtureHandle] | None = None
    try:
        source_ids, fixture_cm = await _resolve_source_ids(case, session=session)
    except FixtureError as exc:
        logger.error("case %s: fixture provisioning failed: %s", case.id, exc)
        return CaseResult(
            id=case.id,
            source_type=case.source_type,
            expected_kind=case.expected_kind,
            passed=False,
            terminated=False,
            termination_reason=f"fixture error: {exc}",
            input_tokens=0,
            output_tokens=0,
            judge_model=judge_model,
            judge_prompt_version=None,
        )

    if fixture_cm is not None:
        async with fixture_cm as handle:
            return await _run_and_judge(
                case,
                pipeline=pipeline,
                compiled_graph=compiled_graph,
                source_ids=[str(handle.source_id)],
                pipeline_runner=pipeline_runner,
                judge_fn=judge_fn,
                judge_llm=judge_llm,
                deadline_secs=deadline_secs,
                judge_model=judge_model,
            )
    return await _run_and_judge(
        case,
        pipeline=pipeline,
        compiled_graph=compiled_graph,
        source_ids=source_ids,
        pipeline_runner=pipeline_runner,
        judge_fn=judge_fn,
        judge_llm=judge_llm,
        deadline_secs=deadline_secs,
        judge_model=judge_model,
    )


async def _run_and_judge(
    case: EvalCase,
    *,
    pipeline: str,
    compiled_graph: Any,
    source_ids: list[str],
    pipeline_runner: PipelineRunner,
    judge_fn: JudgeFn,
    judge_llm: JudgeLLM,
    deadline_secs: int,
    judge_model: str,
) -> CaseResult:
    """Invoke the pipeline under a wall-clock bound, then judge the candidate."""
    eval_id = uuid.uuid4()
    input_tokens = 0
    output_tokens = 0
    judge_prompt_version: str | None = None
    try:
        result = await asyncio.wait_for(
            pipeline_runner(
                compiled_graph=compiled_graph,
                session_id=str(eval_id),
                user_id=str(_EVAL_OWNER_ID),
                query=case.question,
                source_ids=source_ids,
                trace_id=f"eval-trace-{eval_id.hex}",
            ),
            timeout=deadline_secs,
        )
    except TimeoutError:
        logger.error("case %s: exceeded %ss wall-clock deadline (SC-004)", case.id, deadline_secs)
        return CaseResult(
            id=case.id,
            source_type=case.source_type,
            expected_kind=case.expected_kind,
            passed=False,
            terminated=False,
            termination_reason=f"timeout after {deadline_secs}s",
            input_tokens=0,
            output_tokens=0,
            judge_model=judge_model,
            judge_prompt_version=None,
        )
    except Exception as exc:  # noqa: BLE001 - a crashing case must not abort the run
        logger.error("case %s: pipeline raised %s: %s", case.id, type(exc).__name__, exc)
        return CaseResult(
            id=case.id,
            source_type=case.source_type,
            expected_kind=case.expected_kind,
            passed=False,
            terminated=False,
            termination_reason=f"{type(exc).__name__}: {exc}",
            input_tokens=0,
            output_tokens=0,
            judge_model=judge_model,
            judge_prompt_version=None,
        )

    input_tokens = _coerce_tokens(result.get(_INPUT_TOKENS_KEY))
    output_tokens = _coerce_tokens(result.get(_OUTPUT_TOKENS_KEY))

    if result.get(_LOOP_CAP_KEY):
        logger.error("case %s: loop-cap breached without terminating (SC-004)", case.id)
        return CaseResult(
            id=case.id,
            source_type=case.source_type,
            expected_kind=case.expected_kind,
            passed=False,
            terminated=False,
            termination_reason="loop-cap breached without termination",
            input_tokens=input_tokens,
            output_tokens=output_tokens,
            judge_model=judge_model,
            judge_prompt_version=None,
        )

    candidate = result.get(_FINAL_ANSWER_KEY) or ""

    passed = False
    try:
        verdict = await judge_fn(case, candidate, llm=judge_llm, pipeline=pipeline)
        passed = verdict.passed
        judge_model = verdict.judge_model
        judge_prompt_version = verdict.prompt_version
    except JudgeError as exc:
        # A judge failure is recorded as a non-pass (the case still TERMINATED).
        logger.error("case %s: judge error → recorded as non-pass: %s", case.id, exc)
        passed = False

    return CaseResult(
        id=case.id,
        source_type=case.source_type,
        expected_kind=case.expected_kind,
        passed=passed,
        terminated=True,
        termination_reason=None,
        input_tokens=input_tokens,
        output_tokens=output_tokens,
        judge_model=judge_model,
        judge_prompt_version=judge_prompt_version,
    )


# --------------------------------------------------------------------------- #
# Orchestration core (fully injectable — the unit test drives this offline)     #
# --------------------------------------------------------------------------- #


async def run_evals(
    *,
    pipeline: str,
    cases: Sequence[EvalCase],
    compiled_graph: Any,
    session: Any | None,
    pipeline_runner: PipelineRunner,
    judge_fn: JudgeFn,
    judge_llm: JudgeLLM,
    deadline_override: int | None = None,
    limit: int | None = None,
) -> RunReport:
    """Partition, loop the cases, and assemble a :class:`RunReport`.

    The compiled graph is built ONCE by the caller and reused for every case.
    Cases are executed sequentially (the ephemeral fixtures share one DB session
    and per-case schema isolation already prevents collisions).
    """
    selected, skipped_multi = partition_cases(cases, pipeline)
    if skipped_multi:
        logger.info(
            "pipeline=%s: skipping %d multi-source case(s) (R8 partitioning)",
            pipeline,
            skipped_multi,
        )
    if limit is not None and limit >= 0 and limit < len(selected):
        dropped = len(selected) - limit
        logger.info("--limit=%d set: running %d of %d case(s) (dropping %d)",
                    limit, limit, len(selected), dropped)
        selected = selected[:limit]

    deadline_secs = _turn_deadline_secs(deadline_override)
    judge_model = resolve_judge_model(None)

    results: list[CaseResult] = []
    for case in selected:
        result = await _execute_case(
            case,
            pipeline=pipeline,
            compiled_graph=compiled_graph,
            session=session,
            pipeline_runner=pipeline_runner,
            judge_fn=judge_fn,
            judge_llm=judge_llm,
            deadline_secs=deadline_secs,
        )
        results.append(result)

    return _aggregate(
        pipeline=pipeline,
        judge_model=judge_model,
        skipped_multi=skipped_multi,
        results=results,
    )


def _aggregate(
    *,
    pipeline: str,
    judge_model: str,
    skipped_multi: int,
    results: list[CaseResult],
) -> RunReport:
    """Fold per-case results into the aggregate :class:`RunReport`."""
    answer_results = [r for r in results if r.expected_kind == "answer"]
    honesty_results = [r for r in results if r.expected_kind == "decline"]
    non_terminating = [r.id for r in results if not r.terminated]

    return RunReport(
        pipeline=pipeline,
        timestamp=datetime.now(UTC).strftime("%Y%m%dT%H%M%SZ"),
        judge_model=judge_model,
        total_cases=len(results),
        skipped_multi=skipped_multi,
        passed=sum(1 for r in results if r.passed),
        answer_passed=sum(1 for r in answer_results if r.passed),
        answer_total=len(answer_results),
        honesty_passed=sum(1 for r in honesty_results if r.passed),
        honesty_total=len(honesty_results),
        non_terminating=non_terminating,
        total_input_tokens=sum(r.input_tokens for r in results),
        total_output_tokens=sum(r.output_tokens for r in results),
        cases=results,
    )


# --------------------------------------------------------------------------- #
# Report writers                                                               #
# --------------------------------------------------------------------------- #


def _load_prior_report(
    out_dir: Path, pipeline: str, current_stamp: str
) -> dict[str, Any] | None:
    """Return the most recent PRIOR run's JSON payload for the same pipeline, if any."""
    # Sorting works because the filename stamp uses the zero-padded
    # %Y%m%dT%H%M%SZ format (see RunReport.timestamp), which is lexicographically
    # ordered identically to chronological order — so candidates[-1] is the most
    # recent prior run.
    candidates = sorted(out_dir.glob(f"*-{pipeline}.json"))
    candidates = [p for p in candidates if not p.name.startswith(current_stamp)]
    if not candidates:
        return None
    try:
        payload = json.loads(candidates[-1].read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):  # pragma: no cover - best-effort
        return None
    if not isinstance(payload, dict):  # pragma: no cover - defensive
        return None
    return payload


def write_reports(report: RunReport, out_dir: str | Path) -> tuple[Path, Path]:
    """Write the JSON sidecar + markdown report; return their paths.

    Filenames: ``<timestamp>-<pipeline>.json`` / ``.md`` (data-model §5).
    """
    out_path = Path(out_dir)
    out_path.mkdir(parents=True, exist_ok=True)

    prior = _load_prior_report(out_path, report.pipeline, report.timestamp)

    base = f"{report.timestamp}-{report.pipeline}"
    json_path = out_path / f"{base}.json"
    md_path = out_path / f"{base}.md"

    json_path.write_text(_render_json(report), encoding="utf-8")
    md_path.write_text(_render_markdown(report, prior), encoding="utf-8")
    return json_path, md_path


def _render_json(report: RunReport) -> str:
    payload = asdict(report)
    payload["exit_code"] = report.exit_code
    return json.dumps(payload, indent=2, sort_keys=True)


def _pct(num: int, denom: int) -> str:
    if denom == 0:
        return "n/a"
    return f"{(num / denom) * 100:.1f}%"


def _render_markdown(report: RunReport, prior: dict[str, Any] | None) -> str:
    lines: list[str] = []
    lines.append(f"# Eval run — `{report.pipeline}` — {report.timestamp}")
    lines.append("")
    lines.append(f"- Judge model: `{report.judge_model}`")
    lines.append(f"- Cases executed: {report.total_cases} "
                 f"(skipped multi: {report.skipped_multi})")
    lines.append(f"- Pass rate: {report.passed}/{report.total_cases} "
                 f"({_pct(report.passed, report.total_cases)})")
    lines.append(f"- Answer axis: {report.answer_passed}/{report.answer_total} "
                 f"({_pct(report.answer_passed, report.answer_total)})")
    lines.append(f"- Honesty axis: {report.honesty_passed}/{report.honesty_total} "
                 f"({_pct(report.honesty_passed, report.honesty_total)})")
    lines.append(f"- Tokens: in={report.total_input_tokens} "
                 f"out={report.total_output_tokens}")
    lines.append(f"- Bounded termination (SC-004): "
                 f"{'PASS' if not report.non_terminating else 'FAIL'} "
                 f"(non-terminating: {report.non_terminating or 'none'})")

    if prior is not None:
        prior_passed = prior.get("passed", 0)
        prior_total = prior.get("total_cases", 0)
        lines.append(f"- Prior run pass rate: {prior_passed}/{prior_total} "
                     f"({_pct(prior_passed, prior_total)})")
    lines.append("")

    lines.append("| case | source | kind | pass | terminated | reason | "
                 "in_tok | out_tok | judge_model | prompt_v |")
    lines.append("|---|---|---|---|---|---|---|---|---|---|")
    for c in report.cases:
        lines.append(
            f"| {c.id} | {c.source_type} | {c.expected_kind} | "
            f"{'PASS' if c.passed else 'FAIL'} | "
            f"{'yes' if c.terminated else 'NO'} | "
            f"{c.termination_reason or '-'} | "
            f"{c.input_tokens} | {c.output_tokens} | "
            f"{c.judge_model} | {c.judge_prompt_version or '-'} |"
        )
    lines.append("")
    return "\n".join(lines)


# --------------------------------------------------------------------------- #
# Real-wiring entry point                                                      #
# --------------------------------------------------------------------------- #


async def _ensure_eval_session(session_id: uuid.UUID, owner_id: uuid.UUID) -> None:
    """Idempotent: ensure a chat_sessions row exists so guardrail_events FK is satisfied.

    The production pipeline inserts guardrail_event rows that reference a
    chat_sessions.id.  The headless eval runner bypasses the HTTP layer so no
    session row is pre-created; we insert one here and commit immediately.
    Uses check-before-add so a retry or concurrent caller doesn't raise.
    """
    from sqlalchemy.exc import IntegrityError  # noqa: PLC0415

    from src.core.database import AsyncSessionLocal  # noqa: PLC0415
    from src.models.chat import ChatSession  # noqa: PLC0415

    async with AsyncSessionLocal() as seed_session:
        existing = await seed_session.get(ChatSession, session_id)
        if existing is None:
            seed_session.add(ChatSession(id=session_id, user_id=owner_id))
        try:
            await seed_session.commit()
        except IntegrityError:
            await seed_session.rollback()


async def _ensure_eval_owner(owner_id: uuid.UUID) -> None:
    """Upsert the synthetic eval-harness user so the sources FK is satisfiable.

    ``_EVAL_OWNER_ID`` is used as ``owner_id`` for every ephemeral temp-source
    row. The ``sources.owner_id`` FK must point at an existing ``users`` row.
    Runs in its own short-lived session and commits immediately so the row is
    durable — later per-case session rollbacks cannot undo it.
    Uses check-before-add + IntegrityError catch to be safe under concurrent
    first-run inserts (e.g., matrix CI).
    """
    from sqlalchemy.exc import IntegrityError  # noqa: PLC0415

    from src.core.database import AsyncSessionLocal  # noqa: PLC0415
    from src.models.user import User, UserRole  # noqa: PLC0415

    async with AsyncSessionLocal() as seed_session:
        existing = await seed_session.get(User, owner_id)
        if existing is None:
            seed_session.add(
                User(
                    id=owner_id,
                    email="eval-harness@eval.internal",
                    hashed_password="*",
                    full_name="Eval Harness",
                    role=UserRole.admin,
                    is_active=True,
                )
            )
        try:
            await seed_session.commit()
        except IntegrityError:
            await seed_session.rollback()


async def _run_with_real_wiring(args: argparse.Namespace) -> RunReport:
    """Wire the real collaborators (DB session, graph, judge LLM) and run.

    Gated so ``--pipeline agentic`` raises :class:`AgenticPipelineUnavailableError`
    until the agentic graph + flag land in Slice C (T-058). Slice B only ever
    executes ``--pipeline current``.
    """
    if args.pipeline == "agentic":
        # Forward-compat: the agentic graph does not exist yet. Resolve it
        # through the existing builder if/when the flag is on; otherwise fail
        # clean. We do NOT hard-code topology here.
        try:
            from src.core.config import settings  # noqa: PLC0415

            agentic_on = bool(getattr(settings, "PIPELINE_AGENTIC_ENABLED", False))
        except Exception:  # pragma: no cover - defensive
            agentic_on = False
        if not agentic_on:
            raise AgenticPipelineUnavailableError(
                "agentic pipeline not available — the agentic graph lands in "
                "Slice C (T-058); enable PIPELINE_AGENTIC_ENABLED once built. "
                "Slice B baseline runs use --pipeline current."
            )

    from openai import AsyncOpenAI  # noqa: PLC0415

    from src.agent.pipeline import run_pipeline  # noqa: PLC0415
    from src.core.config import settings  # noqa: PLC0415
    from src.core.container import container  # noqa: PLC0415
    from src.core.database import AsyncSessionLocal  # noqa: PLC0415

    cases = load_all_cases(args.cases_dir)

    judge_client = _RealJudgeLLM(AsyncOpenAI(api_key=settings.OPENAI_API_KEY))

    await _ensure_eval_owner(_EVAL_OWNER_ID)

    async with AsyncSessionLocal() as session:
        compiled_graph = container.pipeline()

        async def _pipeline_with_session(**kwargs: Any) -> dict[str, Any]:
            """Wrap run_pipeline to pre-create the chat_session FK row."""
            eval_session_id = uuid.UUID(kwargs["session_id"])
            await _ensure_eval_session(eval_session_id, _EVAL_OWNER_ID)
            return await run_pipeline(**kwargs)

        report = await run_evals(
            pipeline=args.pipeline,
            cases=cases,
            compiled_graph=compiled_graph,
            session=session,
            pipeline_runner=_pipeline_with_session,
            judge_fn=judge_case,
            judge_llm=judge_client,
            limit=args.limit,
        )
    return report


class _RealJudgeLLM:
    """Adapt an ``AsyncOpenAI`` client to the :class:`JudgeLLM` protocol."""

    def __init__(self, client: Any) -> None:
        self._client = client

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
        resp = await self._client.chat.completions.create(
            model=model,
            messages=[
                {"role": "system", "content": system},
                {"role": "user", "content": user},
            ],
            temperature=temperature,
            max_tokens=max_tokens,
            response_format=response_format,
        )
        return resp.choices[0].message.content or ""


# --------------------------------------------------------------------------- #
# CLI                                                                          #
# --------------------------------------------------------------------------- #


def build_arg_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="evals.run",
        description="Headless eval runner — scores a pipeline against the frozen case set.",
    )
    parser.add_argument(
        "--pipeline",
        required=True,
        choices=["current", "agentic"],
        help="Which pipeline to score. 'current' skips multi-source cases (R8).",
    )
    parser.add_argument(
        "--cases-dir",
        default=_DEFAULT_CASES_DIR,
        help=f"Directory of JSON-golden cases (default: {_DEFAULT_CASES_DIR}).",
    )
    parser.add_argument(
        "--out-dir",
        default=_DEFAULT_OUT_DIR,
        help=f"Directory for run artifacts (default: {_DEFAULT_OUT_DIR}).",
    )
    parser.add_argument(
        "--limit",
        type=int,
        default=None,
        help="Run at most N cases (dev/stub runs). Dropped cases are logged.",
    )
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    """CLI entry: run the eval, write reports, return the deterministic exit code."""
    logging.basicConfig(level=logging.INFO, format="%(levelname)s %(name)s: %(message)s")
    args = build_arg_parser().parse_args(argv)

    try:
        report = asyncio.run(_run_with_real_wiring(args))
    except AgenticPipelineUnavailableError as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 2

    json_path, md_path = write_reports(report, args.out_dir)
    print(f"wrote {json_path}")
    print(f"wrote {md_path}")

    if report.non_terminating:
        print(
            "non-terminating/crashed case(s): " + ", ".join(report.non_terminating),
            file=sys.stderr,
        )
    return report.exit_code


if __name__ == "__main__":  # pragma: no cover - module entry
    raise SystemExit(main())
