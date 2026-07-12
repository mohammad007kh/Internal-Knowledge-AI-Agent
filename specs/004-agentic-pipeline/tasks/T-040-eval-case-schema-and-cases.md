# Task: T-040 - Eval Case Schema + Frozen Case Set

**Status**: Pending
**Created**: 2026-06-04 | **Completed**: N/A
**Platform**: web | **Task Target**: backend
**User Story**: US6 (Operators can measure quality and bound cost)
**Requirement**: FR-022
**Dependencies**: none

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
| `conventions.classes` | PascalCase |
| `conventions.constants` | SCREAMING_SNAKE_CASE |

### Feature Summary

Feature 004 evolves the linear retrieve-then-answer pipeline into a
transparent plan-and-execute agent. Story 6 ships an **outcome-based eval
harness** (file-based JSON-golden cases under `backend/evals/`, NOT a DB
table) so each release can be scored pass/fail against a frozen question set
with per-question cost, including dedicated honesty cases whose only correct
outcome is an explained decline. This task is the foundation of Slice B: the
case schema + the frozen case set that every later eval task consumes.

### R8 Partitioning Rules (COPIED VERBATIM — load-bearing)

> The baseline run against the CURRENT pipeline scores **only the
> single-source + honesty subsets** — that is exactly SC-005's comparison
> scope. Multi-step (`source_type: multi`) cases are AUTHORED in the harness
> slice but first EXECUTED against the agentic pipeline (they measure SC-001
> capability, not regression). The judge prompt must accept the current
> pipeline's *implicit* declines ("I don't see anything about that…") as a
> valid decline for BASELINE honesty scoring; the agentic pipeline is held to
> the stricter *explained*-decline standard (SC-002).

### Security Rule 4 — Eval Data Hygiene (MEDIUM, from plan.md — ENFORCED HERE)

> Fixtures synthetic-only (no real names/PII/business data — the repo is
> PUBLIC); required `"data_source": "synthetic"` field on every case, checked
> in CI; human review gate before committing fixtures.

### Data Model §5 — Case file shape (COPIED VERBATIM)

Case file shape (`backend/evals/cases/<source-type>/<case-id>.json`):
```jsonc
{
  "id": "db-workspaces-01",
  "source_type": "database",        // file | web | database | multi
  "question": "How many workspaces does Alice have?",
  "expected_kind": "answer",         // answer | decline (honesty case)
  "golden_answer": "Alice has 3 workspaces.",
  "must_include": ["3"],
  "must_not_fabricate": true,
  "fixtures": {"seed": "evals/fixtures/cctp-mini.sql"}
}
```

> NOTE: per Security Rule 4 the schema in THIS task adds a **REQUIRED**
> `"data_source": "synthetic"` field to the shape above (not shown in the
> original data-model snippet but mandated by the security plan-review). It
> MUST be present on every case and MUST equal the literal string
> `"synthetic"`.

### Gate Criteria

- [ ] Every committed case file parses against the Pydantic schema.
- [ ] Every case has `data_source == "synthetic"` (CI-enforceable assertion).
- [ ] All synthetic content — no real names, PII, or business data (repo is PUBLIC).
- [ ] Human review gate satisfied before committing fixtures (logged in Completion Log).

---

## 🎯 Objective

Define a Pydantic v2 model for an evaluation case in `backend/evals/schema.py`
and author the initial **frozen** case set in `backend/evals/cases/`: ~20-30
synthetic cases spanning file / web / database source types, covering
answerable AND unanswerable questions, including 10-15 dedicated honesty cases
(`expected_kind == "decline"`), plus 3-5 `multi` cases (authored now, executed
only against the agentic pipeline per R8).

## 🛠️ Implementation Details

### Files to Create

- `backend/evals/__init__.py` - package marker for the eval harness.
- `backend/evals/schema.py` - `EvalCase` Pydantic v2 model + a `load_case(path)` / `load_all_cases(dir)` loader.
- `backend/evals/cases/file/*.json` - synthetic file-source cases (answerable + unanswerable).
- `backend/evals/cases/web/*.json` - synthetic web-source cases (answerable + unanswerable).
- `backend/evals/cases/database/*.json` - synthetic database-source cases (answerable + unanswerable + honesty declines).
- `backend/evals/cases/multi/*.json` - 3-5 synthetic `multi` cases (authored now; executed only against agentic).
- `backend/tests/unit/evals/test_eval_schema.py` - schema validation + `data_source` enforcement tests.

### Files to Update (REQUIRED)

- None for wiring (this task is consumed programmatically by T-041/T-042/T-043; no router/UI). The `backend/evals/__init__.py` package marker makes `evals` importable as `python -m evals.*` from `backend/`.

### Code/Logic Requirements

- `EvalCase` fields (Pydantic v2, all validated at load):
  - `id: str` (non-empty, unique across the set — loader asserts uniqueness).
  - `source_type: Literal["file", "web", "database", "multi"]`.
  - `question: str` (non-empty).
  - `expected_kind: Literal["answer", "decline"]`.
  - `golden_answer: str` (the reference answer; for declines, the canonical decline phrasing).
  - `must_include: list[str]` (default `[]`).
  - `must_not_fabricate: bool` (default `True`).
  - `fixtures: Fixtures | None` where `Fixtures = {seed: str}` (relative path under `backend/`, e.g. `evals/fixtures/cctp-mini.sql`).
  - `data_source: Literal["synthetic"]` — **REQUIRED**, must equal `"synthetic"` (security rule 4). Use a `Literal` so any other value is a validation error.
- Error handling = exceptions (registry): loader raises a clear `EvalCaseError` (subclass of `ValueError`) naming the offending file + field on any parse/validation failure.
- Honesty cases (`expected_kind == "decline"`) MUST set `golden_answer` to the expected decline content and `must_not_fabricate: true`.
- `multi` cases require `fixtures` (they chain a file + a database) — schema validator: if `source_type == "multi"`, `fixtures` MUST be present.
- Database / multi cases reference a `fixtures.seed` path; the actual seed SQL is authored in T-041 (this task may reference paths that T-041 creates — note as a soft dependency in case JSON comments are not allowed; keep JSON strict, document the link here).
- Count targets: ~20-30 total; 10-15 of them `expected_kind == "decline"`; 3-5 `source_type == "multi"`.

## 🔌 Wiring Checklist

### Shared (All Platforms)
- [x] **Environment var** → none (file-based, no config).
- [ ] **Database model** → N/A (file-based per R8/data-model §5, NOT a DB table).

## ✅ Verification

**Command**:
```bash
docker compose exec -T backend python -m pytest tests/unit/evals/test_eval_schema.py --no-cov -q
```
**Success Criteria**: all tests pass; the test discovers EVERY `*.json` under
`backend/evals/cases/`, parses each against `EvalCase`, and asserts
`data_source == "synthetic"` for all of them; asserts counts
(10-15 declines, 3-5 multi); asserts `id` uniqueness.

Direct (no Docker) fallback:
```bash
cd backend && python -m pytest tests/unit/evals/test_eval_schema.py --no-cov -q
```

CI `data_source` spot check (used later by T-044 CI job):
```bash
docker compose exec -T backend python -c "from evals.schema import load_all_cases; cs=load_all_cases('evals/cases'); assert all(c.data_source=='synthetic' for c in cs); print(len(cs),'cases OK')"
```

## 📝 Completion Log

- [ ] `EvalCase` Pydantic model implemented with REQUIRED `data_source` Literal
- [ ] ~20-30 synthetic cases authored (file/web/database/multi)
- [ ] 10-15 honesty (`decline`) cases present
- [ ] 3-5 `multi` cases present (fixtures attached)
- [ ] Schema validation tests pass
- [ ] HUMAN REVIEW GATE: a human confirmed fixtures/cases contain NO real names/PII/business data before commit (repo is PUBLIC)
- [ ] Linter passed (`ruff check evals/schema.py`)
