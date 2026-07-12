# Task: T-042 - Eval Runner (Headless Pipeline + Bounded-Termination Gate)

**Status**: Pending
**Created**: 2026-06-04 | **Completed**: N/A
**Platform**: web | **Task Target**: backend
**User Story**: US6 (Operators can measure quality and bound cost)
**Requirement**: FR-023, FR-024, SC-004
**Dependencies**: [T-040](./T-040-eval-case-schema-and-cases.md), [T-041](./T-041-eval-fixtures-loader.md)

---

## 📋 Embedded Context (READ THIS FIRST)

<!--
  SELF-CONTAINED TASK (Constitution Directive 8):
  This section contains ALL context needed to implement this task.
  Do NOT read plan.md, spec.md, stations, or subagents.
-->

### Project Standards (from registry)

| Key | Value |
|-----|-------|
| `architecture.pattern` | modular_monolith |
| `architecture.layers` | clean |
| `code_patterns.data_access` | repository |
| `code_patterns.dependency_injection` | container |
| `code_patterns.error_handling` | exceptions |
| `code_patterns.validation_approach` | schema (Pydantic v2) |
| `database.tenancy_model` | single_tenant |
| `testing.unit_framework` | pytest |
| `conventions.files` | snake_case (Python modules) |
| `conventions.variables` | snake_case |
| `conventions.constants` | SCREAMING_SNAKE_CASE |

### Feature Summary

Feature 004 evolves the pipeline into a transparent plan-and-execute agent.
Story 6's eval harness scores each release against a frozen case set. This task
is the **runner**: `python -m evals.run --pipeline current|agentic`. It invokes
the pipeline HEADLESSLY (no HTTP/SSE), loops the frozen cases, records
per-case token cost, enforces bounded termination (SC-004), and writes a JSON
sidecar + markdown report to `backend/evals/runs/`.

### Headless invocation contract (load-bearing)

The pipeline already exposes `run_pipeline()` at
`backend/src/agent/pipeline.py:446`:
```python
async def run_pipeline(
    *,
    compiled_graph: CompiledStateGraph[Any, Any, Any, Any],
    session_id: str,
    user_id: str,
    query: str,
    source_ids: list[str],
    trace_id: str,
) -> dict[str, Any]:
    ...
    result = await compiled_graph.ainvoke(initial_state, config=config)
    return dict(result)
```
Build the compiled graph ONCE (via the pipeline's build/selector), then loop
cases calling `run_pipeline(...)` per case. The result dict carries
`final_answer`, `total_input_tokens`, `total_output_tokens`, and (agentic) plan
state. `--pipeline current|agentic` selects which graph to build (the
agentic graph lands in Slice C; until then `--pipeline agentic` may build the
flag-on graph — keep the selector behind the existing build function so this
runner does not hard-code topology).

### R8 Partitioning Rules (COPIED VERBATIM — load-bearing)

> The baseline run against the CURRENT pipeline scores **only the
> single-source + honesty subsets** — that is exactly SC-005's comparison
> scope. Multi-step (`source_type: multi`) cases are AUTHORED in the harness
> slice but first EXECUTED against the agentic pipeline (they measure SC-001
> capability, not regression). The judge prompt must accept the current
> pipeline's *implicit* declines ("I don't see anything about that…") as a
> valid decline for BASELINE honesty scoring; the agentic pipeline is held to
> the stricter *explained*-decline standard (SC-002).

**Concrete runner consequence**: `--pipeline current` SKIPS every case with
`source_type == "multi"`. `--pipeline agentic` runs ALL cases.

### Exit-code / threshold contract (quickstart §7 — COPIED VERBATIM)

> - `evals.run` exits 0 when every case executed and terminated within limits
>   (SC-004 check is built into the runner); non-zero on any unbounded/crashed
>   case. Results JSON + markdown report written to `evals/runs/`.
> - `evals.compare` exits 0 when ALL gates pass: honesty ≥ 90%
>   explained-decline on the agentic run (SC-002), agentic pass-rate ≥
>   baseline pass-rate on the single-source subset (SC-005); exits 1 with the
>   failing gate named in stdout otherwise. CI consumes the exit code.

### Data Model §5 — Run output (COPIED VERBATIM)

> **Run output** (`backend/evals/runs/<timestamp>-<pipeline-version>.md` + a
> JSON sidecar): per-case pass/fail, honesty axis scored separately, tokens
> per case, judge model + prompt version, aggregate vs prior run.

### Gate Criteria

- [ ] `--pipeline current` skips `source_type == "multi"` cases; `--pipeline agentic` runs all.
- [ ] Per-case token cost recorded (input + output) from the result dict.
- [ ] Bounded-termination enforced: any unbounded/crashed/non-terminating case → non-zero exit (SC-004).
- [ ] JSON sidecar + markdown report written to `backend/evals/runs/`.

---

## 🎯 Objective

Implement `backend/evals/run.py` runnable as `python -m evals.run --pipeline
current|agentic`. It builds the compiled graph once, loads the frozen cases via
T-040's loader, provisions DB fixtures via T-041's `ephemeral_fixture`, invokes
`run_pipeline()` per case, records per-case tokens, ENFORCES bounded
termination, scores via the judge (T-043, dependency-injected/imported), and
writes a JSON sidecar + markdown report to `backend/evals/runs/`.

## 🛠️ Implementation Details

### Files to Create

- `backend/evals/run.py` - the runner + `argparse` CLI + `__main__` entry (`python -m evals.run`).
- `backend/evals/runs/.gitkeep` - keep the runs dir present (artifacts themselves are git-ignored — confirm `.gitignore`).
- `backend/tests/unit/evals/test_runner.py` - runner tested with a 2-case STUB set + mocked LLM (no real model calls).

### Files to Update (REQUIRED)

- `backend/.gitignore` (or repo `.gitignore`) - ignore `backend/evals/runs/*` except `.gitkeep` (run artifacts are not committed; the committed summary lives in T-045's `BASELINE.md`).

### Code/Logic Requirements

- CLI: `--pipeline {current,agentic}` (required); optional `--cases-dir` (default `evals/cases`), `--out-dir` (default `evals/runs`), `--limit` (for stub/dev runs).
- Build the compiled graph ONCE before the loop (avoid rebuilding per case); select current vs agentic through the existing pipeline build function — do not duplicate topology.
- **Forward-compatibility note**: `--pipeline agentic` resolves through `build_pipeline()`/the graph selector; the agentic graph does not exist until T-058 (Slice C). Implement the selector pass-through generically and make `--pipeline agentic` exit with a clear "agentic pipeline not available" error until the flag+builder land — do NOT hard-code any topology here. Slice B only ever executes `--pipeline current` (T-045).
- Partitioning: when `--pipeline current`, filter out `source_type == "multi"` cases BEFORE the loop.
- For each case:
  - If `case.fixtures` present → enter `ephemeral_fixture(case, session)` (T-041) to get the temp `source_id`; otherwise use the case's declared source set.
  - Call `run_pipeline(compiled_graph=…, query=case.question, source_ids=[…], …)` with a synthetic eval `user_id`/`session_id`/`trace_id`.
  - Record `total_input_tokens` / `total_output_tokens` from the result.
  - **Bounded-termination check (SC-004)**: wrap the per-case invocation in `asyncio.wait_for(..., timeout=AGENT_TURN_DEADLINE_SECS or a hard runner default)`; a `TimeoutError`, an uncaught exception, or a result indicating a loop-cap breach marks the case `terminated=False`. Record the reason.
  - Pass `(question, golden_answer, candidate_answer, expected_kind, pipeline)` to the judge (T-043) for pass/fail; honesty cases scored on the SEPARATE axis (the judge handles axis selection by `expected_kind`).
- **Exit code (verbatim contract above)**: exit `0` iff EVERY executed case `terminated == True`; exit non-zero (e.g. `1`) if ANY case did not terminate within limits / crashed — name the offending case id(s) on stderr.
- Outputs to `evals/runs/<timestamp>-<pipeline>.{json,md}`:
  - JSON sidecar: per-case `{id, source_type, expected_kind, pass, terminated, termination_reason, input_tokens, output_tokens, judge_model, judge_prompt_version}` + aggregates.
  - Markdown report: per-case table, honesty axis scored separately, tokens per case, judge model + prompt version, aggregate vs prior run.
- Error handling = exceptions (registry): a crashing case is CAUGHT, recorded as `terminated=False` with the exception summary, and does NOT abort the whole run (the run still completes and exits non-zero).
- The unit test uses a 2-case stub set and monkeypatches the LLM / `run_pipeline` so no real model is hit; it asserts: partitioning (multi skipped on `current`), tokens recorded, a non-terminating stub forces non-zero exit, report files written.

## 🔌 Wiring Checklist

### Shared (All Platforms)
- [x] **Environment var** → reads `AGENT_TURN_DEADLINE_SECS` if set (wall-clock bound); otherwise a hard runner default.
- [x] **CLI entry** → `python -m evals.run` works from `backend/`.

## ✅ Verification

**Command**:
```bash
docker compose exec -T backend python -m pytest tests/unit/evals/test_runner.py --no-cov -q
```
**Success Criteria**: all runner unit tests pass with the 2-case stub set +
mocked LLM — partitioning, token recording, bounded-termination → exit code
mapping, and report-file emission are all asserted. No real LLM/network calls.

CLI smoke (help only, no model spend):
```bash
docker compose exec -T backend python -m evals.run --help
```
Success: prints usage including `--pipeline {current,agentic}` and exits 0.

Direct (no Docker) fallback:
```bash
cd backend && python -m pytest tests/unit/evals/test_runner.py --no-cov -q
```

## 📝 Completion Log

- [ ] `python -m evals.run --pipeline current|agentic` implemented
- [ ] Graph built once; cases looped via `run_pipeline()`
- [ ] `--pipeline current` skips `multi` cases (R8 partitioning)
- [ ] Per-case tokens recorded
- [ ] Bounded-termination enforced → exit-code contract honored (SC-004)
- [ ] JSON sidecar + markdown report written to `evals/runs/`
- [ ] Runner unit tests pass (2-case stub + mocked LLM)
- [ ] `evals/runs/*` git-ignored
- [ ] Linter passed (`ruff check evals/run.py`)
