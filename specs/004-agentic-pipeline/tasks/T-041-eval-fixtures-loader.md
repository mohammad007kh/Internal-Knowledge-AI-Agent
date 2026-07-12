# Task: T-041 - Eval Fixtures Loader (Ephemeral Schema + Temp Source)

**Status**: Pending
**Created**: 2026-06-04 | **Completed**: N/A
**Platform**: web | **Task Target**: backend
**User Story**: US6 (Operators can measure quality and bound cost)
**Requirement**: FR-022
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
| `database.type` | postgresql 16 + pgvector |
| `database.tenancy_model` | single_tenant |
| `testing.unit_framework` | pytest |
| `testing.integration_framework` | httpx |
| `conventions.files` | snake_case (Python modules) |
| `conventions.variables` | snake_case |

### Feature Summary

Feature 004 evolves the pipeline into a transparent plan-and-execute agent.
Story 6's eval harness needs database-type cases to run against a real,
queryable database. This task builds the **fixtures loader** that applies a
case's `fixtures.seed` SQL into an EPHEMERAL schema inside the existing
Postgres service, registers a temporary source against it so the pipeline can
target it, and tears everything down afterward. The CI compose stack already
runs Postgres, so no new infrastructure is required.

### R8 Fixtures Provisioning (COPIED VERBATIM — load-bearing)

> DB-type eval cases need a queryable database — the harness includes a
> fixtures loader that applies `fixtures.seed` SQL into an ephemeral
> schema/database in the existing Postgres service and registers a temp source
> against it (CI compose stack already runs Postgres). Fixture data MUST be
> synthetic-only (see security rules in plan.md).

### R8 Partitioning Rules (COPIED VERBATIM — context for which cases need fixtures)

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

### Gate Criteria

- [ ] Seed SQL files in `backend/evals/fixtures/` contain ONLY synthetic data.
- [ ] Ephemeral schema is fully torn down after use (no leaked schemas/sources).
- [ ] Temp source registration honors the existing repository pattern + request-session binding (FX41 lesson — no naked queries).
- [ ] Human review gate satisfied before committing any new seed file.

---

## 🎯 Objective

Implement `backend/evals/fixtures.py`: a context-managed loader that, given an
`EvalCase` with `fixtures.seed`, creates an ephemeral Postgres schema, applies
the seed SQL into it, registers a temporary source pointing at that schema so
the pipeline can query it, yields the temp source id(s), and tears down the
schema + temp source on exit (including on error). Author the synthetic seed
SQL files in `backend/evals/fixtures/`.

## 🛠️ Implementation Details

### Files to Create

- `backend/evals/fixtures.py` - `ephemeral_fixture(case, session)` async context manager + helpers.
- `backend/evals/fixtures/cctp-mini.sql` - synthetic seed for the database/multi cases (e.g. `users`, `workspaces` tables with invented names like Alice/Bob/Carlos and made-up counts).
- `backend/evals/fixtures/*.sql` - any additional synthetic seeds referenced by T-040 cases.
- `backend/tests/integration/evals/test_fixtures_loader.py` - integration test: create → query → tear down an ephemeral fixture.

### Files to Update (REQUIRED)

- None for wiring (consumed by T-042's runner). The loader reuses the existing source repository / DB session; document the exact import path during implementation (e.g. `src.repositories.source_repository`).

### Code/Logic Requirements

- `ephemeral_fixture` is an `async with` context manager that:
  1. Generates a unique ephemeral schema name (e.g. `eval_<uuid4hex>`); `CREATE SCHEMA`.
  2. Applies the case's `fixtures.seed` SQL into that schema (set `search_path` to the ephemeral schema before executing, so unqualified table names land there).
  3. Registers a TEMPORARY database source against the ephemeral schema via the existing source repository/service (so `run_pipeline()` can target it by id); returns the temp `source_id`.
  4. On exit (success OR exception) deletes the temp source row and `DROP SCHEMA … CASCADE`. Use try/finally — teardown MUST run on error (exceptions = registry error strategy).
- Use the request-session-bound repository pattern (FX41 lesson): all DB access through the session passed in, no module-global engine, no naked queries outside the seed-application path.
- Seed SQL is trusted-but-synthetic (authored in-repo); still scope its execution to the ephemeral schema so a runaway seed cannot touch real tables.
- Idempotency / isolation: each case gets a fresh schema name so parallel/sequential cases never collide.
- Synthetic-only invariant (security rule 4): seeds use invented names/values; the human review gate in the Completion Log covers this before commit.

## 🔌 Wiring Checklist

### Shared (All Platforms)
- [x] **Environment var** → none new (uses existing Postgres connection / `DATABASE_URL`).
- [ ] **Database model** → N/A (ephemeral schema created/dropped at runtime, not an Alembic migration).

## ✅ Verification

**Command**:
```bash
docker compose exec -T backend python -m pytest tests/integration/evals/test_fixtures_loader.py --no-cov -q
```
**Success Criteria**: the integration test enters `ephemeral_fixture` for a
database case, asserts the seeded rows are queryable inside the ephemeral
schema AND the temp source is registered, exits the context, then asserts the
schema is gone (`information_schema.schemata` no longer lists it) and the temp
source row is deleted. A second test forces an exception inside the context and
asserts teardown still ran (no leaked schema/source).

Direct (no Docker) fallback:
```bash
cd backend && python -m pytest tests/integration/evals/test_fixtures_loader.py --no-cov -q
```

## 📝 Completion Log

- [ ] `ephemeral_fixture` context manager implemented (create → seed → register → teardown)
- [ ] Synthetic seed SQL authored in `backend/evals/fixtures/`
- [ ] Teardown verified on both success and exception paths
- [ ] Integration test passes
- [ ] HUMAN REVIEW GATE: a human confirmed seed SQL contains NO real names/PII/business data before commit (repo is PUBLIC)
- [ ] Linter passed (`ruff check evals/fixtures.py`)
