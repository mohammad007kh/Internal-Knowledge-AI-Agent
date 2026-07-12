# Task: T-043 - Eval Judge (Reference-Based Binary + Honesty Axis)

**Status**: Pending
**Created**: 2026-06-04 | **Completed**: N/A
**Platform**: web | **Task Target**: backend
**User Story**: US6 (Operators can measure quality and bound cost)
**Requirement**: FR-023
**Dependencies**: [T-040](./T-040-eval-case-schema-and-cases.md)

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

### Feature Summary

Feature 004 evolves the pipeline into a transparent plan-and-execute agent.
Story 6's eval harness needs a **judge** that decides pass/fail per case. This
task implements `backend/evals/judge.py` + a versioned judge prompt:
reference-based BINARY pass/fail against the case's `golden_answer`, with
honesty cases scored on a SEPARATE axis, using a judge model from a DIFFERENT
family than the answerer.

### R8 Evaluation Harness — judge guidance (COPIED VERBATIM — load-bearing)

> LLM-judge (reference-based, binary, different model family than the answerer,
> periodic ~10-20% human spot-check) …

### R8 Partitioning Rules (COPIED VERBATIM — load-bearing for axis logic)

> The baseline run against the CURRENT pipeline scores **only the
> single-source + honesty subsets** — that is exactly SC-005's comparison
> scope. Multi-step (`source_type: multi`) cases are AUTHORED in the harness
> slice but first EXECUTED against the agentic pipeline (they measure SC-001
> capability, not regression). The judge prompt must accept the current
> pipeline's *implicit* declines ("I don't see anything about that…") as a
> valid decline for BASELINE honesty scoring; the agentic pipeline is held to
> the stricter *explained*-decline standard (SC-002).

**Concrete judge consequence**: the judge receives a `pipeline` flag from the
runner. For `expected_kind == "decline"` cases:
- `pipeline == "current"` (baseline) → accept an **implicit** decline as a pass.
- `pipeline == "agentic"` → require an **explained** decline (states what was
  tried / why nothing matched) to pass; a bare implicit "I don't know" is a
  fail on the honesty axis.

### Gate Criteria

- [ ] Reference-based binary pass/fail vs `golden_answer` for `expected_kind == "answer"`.
- [ ] Honesty (`decline`) cases scored on a SEPARATE axis with implicit-vs-explained rule keyed by the `pipeline` flag.
- [ ] Judge model is a DIFFERENT family than the answerer (configurable).
- [ ] Judge prompt is versioned in-repo (file with a version tag the runner records).

---

## 🎯 Objective

Implement `backend/evals/judge.py` and a versioned judge prompt file. The judge
takes `(question, golden_answer, candidate_answer, expected_kind, pipeline)`
and returns a binary verdict plus the axis it was scored on. The judge model is
configurable and MUST default to a different family than the answerer
(resolved via the existing `AIModelResolver` or a direct client). The judge
prompt is stored in-repo with a version string the runner records in its
report.

## 🛠️ Implementation Details

### Files to Create

- `backend/evals/judge.py` - `Judge` class (or `judge_case(...)` function) returning `JudgeVerdict { passed: bool, axis: Literal["answer","honesty"], reason: str, judge_model: str, prompt_version: str }`.
- `backend/evals/prompts/judge.v1.txt` - the versioned judge prompt (the `v1` in the filename IS the version recorded in the report).
- `backend/tests/unit/evals/test_judge.py` - unit tests with canned `(question, golden, candidate)` triples incl. decline cases, mocked judge LLM.

### Files to Update (REQUIRED)

- None for wiring beyond import: the runner (T-042) imports and calls the judge. Confirm the model-resolution import path during implementation (e.g. `src.agent.model_resolver` / `AIModelResolver`); if a direct client is simpler for an offline harness, that is acceptable per R8 ("via AIModelResolver or direct client").

### Code/Logic Requirements

- Verdict model is Pydantic v2 (`validation_approach: schema`): `JudgeVerdict` as above.
- Answer axis (`expected_kind == "answer"`): the judge prompt asks "does the candidate answer match the reference `golden_answer` in substance?" → binary YES/NO. `must_include` substrings (from the case) MAY be checked deterministically as a pre-gate before the LLM call (cheap fail-fast); the prompt still makes the final binary call.
- Honesty axis (`expected_kind == "decline"`): scored SEPARATELY. The prompt branches on `pipeline`:
  - baseline (`current`): an implicit decline (e.g. "I don't see anything about that in the sources") PASSES.
  - agentic: only an EXPLAINED decline PASSES (names what was tried / why it could not answer); fabricated data points fail regardless (`must_not_fabricate`).
- Judge model: configurable via env/config; DEFAULT family MUST differ from the answerer's family (R8). Document the chosen default and resolution path. The actual model name + prompt version are returned in the verdict so the runner records them.
- LLM observability (Constitution II): the judge call is Langfuse-traceable with a stage name; the OFFLINE judge is excluded from per-turn token accounting (it is not a turn cost — note from R2).
- Error handling = exceptions (registry): a malformed/empty judge response raises a clear error naming the case; the runner records it as a non-pass rather than crashing the whole run.
- Determinism aid: set judge temperature low/0 where the client allows, so reruns are stable for spot-checks.

## 🔌 Wiring Checklist

### Shared (All Platforms)
- [x] **Environment var** → judge model selector (e.g. `EVAL_JUDGE_MODEL`) read at construction; documented default is a different family than the answerer.
- [ ] **Database model** → N/A.

## ✅ Verification

**Command**:
```bash
docker compose exec -T backend python -m pytest tests/unit/evals/test_judge.py --no-cov -q
```
**Success Criteria**: tests pass for canned triples — a correct answer passes
the answer axis; a wrong/fabricated answer fails; for a decline case an
IMPLICIT decline passes under `pipeline="current"` but FAILS under
`pipeline="agentic"`, while an EXPLAINED decline passes under both. Judge LLM is
mocked; verdict carries `judge_model` + `prompt_version`.

Direct (no Docker) fallback:
```bash
cd backend && python -m pytest tests/unit/evals/test_judge.py --no-cov -q
```

## 📝 Completion Log

- [ ] `judge.py` reference-based binary pass/fail implemented
- [ ] Honesty axis scored separately with implicit-vs-explained `pipeline` branching
- [ ] Judge model defaults to a different family than the answerer (configurable)
- [ ] `judge.v1.txt` prompt versioned in-repo; version recorded in verdict
- [ ] Judge call Langfuse-traceable; excluded from per-turn token cost
- [ ] Judge unit tests pass (canned triples incl. declines, mocked LLM)
- [ ] Linter passed (`ruff check evals/judge.py`)
