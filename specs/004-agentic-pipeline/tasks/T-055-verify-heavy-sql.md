# Task: T-055 - verify-heavy-sql

**Status**: Done
**Created**: 2026-06-04 | **Completed**: 2026-06-07
**User Story**: US3 (verification & honesty)
**Requirement**: FR-011
**Platform**: web | **Subagents Enabled**: yes

---

## 📋 Embedded Context (READ THIS FIRST)

<!-- SELF-CONTAINED TASK (Constitution Directive 8): all context needed is here. Do NOT read plan.md/spec.md/stations. -->

### Project Standards (from registry)

| Key | Value |
|-----|-------|
| `architecture.pattern` | modular_monolith |
| `architecture.layers` | clean |
| `code_patterns.data_access` | repository |
| `code_patterns.dependency_injection` | container |
| `code_patterns.error_handling` | exceptions |
| `code_patterns.validation_approach` | schema (Pydantic) |
| `database.tenancy_model` | single_tenant |
| `conventions.files` | snake_case (Python modules) |
| `conventions.variables` | snake_case |
| `conventions.constants` | SCREAMING_SNAKE_CASE |
| `testing.unit_framework` | pytest |

### Feature Summary

Evolve the linear retrieve-then-answer pipeline into a transparent plan-and-execute agent. Six prioritized stories: P1 source intent metadata (hybrid authoring, capability-ramp authority), P2 multi-step planning with dependent steps, P3 per-step self-verification with honest failure, P4 clarify-with-options, P5 two-layer thinking UX, P6 eval harness + hard cost ceiling. LangGraph plan-and-execute with hard caps (5 steps / 1 replan / 1 retry / token ceiling enforced at loop edges), all behind `PIPELINE_AGENTIC_ENABLED` with sandbox-first rollout. Zero new runtime dependencies.

### Domain Rules

- **Heavy verification for DB steps (FR-011)**: database lookup steps receive ADDITIONAL verification capable of catching plausible-but-wrong results (empty results, truncated results, structurally suspect queries, results that don't answer the question). This extends the light grader (T-054) for steps that produced SQL.
- **`generated_sql` becomes verifier input**: today `generated_sql` is trace-only in state; here it feeds the deterministic gate and the judge call.
- **`retrieval_grader` slot reused** for the heavy judge call (data-model §7); no separate slot.
- **Constitution II**: the heavy judge LLM call is Langfuse-traced under `retrieval_grader` and returns its token delta (T-050 contract).

**HEAVY DB VERIFICATION SPEC (R3 — COPY VERBATIM from data-model §2b):**

> **Heavy DB verification spec (R3)** — for steps that produced SQL:
> 1. Deterministic gate (no LLM, reuses `db_safety`/sqlglot): 0 rows when the sub_query implies results? row count == the injected LIMIT (100 — silent truncation)? every referenced table/column exists in the schema sketch? filter/JOIN present when the sub_query implies one?
> 2. ONE cheap-tier LLM judge call over `{resolved sub_query, generated_sql, first ~3 rows}` → "do these rows answer the sub_query? YES/PARTIAL/NO + reason" — on the `retrieval_grader` slot.
> No self-consistency voting. No confirmatory second query in v1.

### API Context

Not applicable — extends the verify node's verdict logic; verdicts flow into the R4b edge (owned by T-054).

### Gate Criteria

- [ ] Heavy path triggers ONLY for steps whose `StepResult.generated_sql` is non-null.
- [ ] Deterministic gate (no LLM, reuses `db_safety`/sqlglot) checks: 0-rows-when-implied, row-count==injected-LIMIT-100 (silent truncation), referenced tables/columns exist in the schema sketch, filter/JOIN present when implied.
- [ ] ONE cheap-tier judge call over `{resolved sub_query, generated_sql, first ~3 rows}` on the `retrieval_grader` slot.
- [ ] NO self-consistency voting; NO confirmatory second query.
- [ ] Judge result folds into the same `StepResult.verification` verdict consumed by the R4b edge (T-054).
- [ ] `retrieval_grader` Langfuse span; token delta returned.

### Dependencies

- [T-054 verify-node-light](./T-054-verify-node-light.md) — extends the same verify node; feeds the R4b edge it owns.

---

## 🎯 Objective

Extend the verify node so steps that produced SQL get heavy verification: a free deterministic gate (reusing `db_safety`/sqlglot) for the four structural checks, then exactly one cheap-tier judge call over the resolved sub_query + SQL + first ~3 rows — feeding a single verdict into the R4b edge.

## 🛠️ Implementation Details

### Files to Create

- `backend/tests/unit/agent/test_verify_heavy_sql.py` — deterministic-gate cases (one per check) + judge-call invocation with mocked LLM.

### Files to Update (REQUIRED)

- `backend/src/agent/nodes/verify.py` — add the SQL-step branch (deterministic gate + single judge call); fold the result into the existing `StepResult.verification` verdict consumed by the R4b edge.
- `backend/src/prompts/retrieval_grader.v1.txt` — extend/parameterize so the same slot serves the heavy judge ("do these rows answer the sub_query? YES/PARTIAL/NO + reason") over `{resolved sub_query, generated_sql, first ~3 rows}`.

### Code/Logic Requirements

- Branch on `StepResult.generated_sql is not None`.
- Deterministic gate (reuse the existing `db_safety`/sqlglot utilities — locate them; do NOT reimplement):
  1. 0 rows when the sub_query implies results.
  2. row count == the injected LIMIT (100) → flag silent truncation.
  3. every referenced table/column exists in the schema sketch.
  4. filter/JOIN present when the sub_query implies one.
  Record each check outcome into `verification.checks`.
- Then ONE judge call over `{resolved sub_query, generated_sql, first ~3 rows}` → YES/PARTIAL/NO + reason; map to `acceptable|partial|unacceptable`. NO voting, NO second query.
- Combine deterministic-gate failures with the judge verdict into the final `verification.verdict` (a deterministic-gate failure can force `unacceptable` regardless of the judge).
- Acceptance Criteria (mocked):
  - Each deterministic check independently produces the expected gate flag.
  - The judge call is invoked exactly once over the resolved sub_query + SQL + first ~3 rows.
  - A clean gate + judge YES → `acceptable`; a tripped gate → `unacceptable` into the R4b edge.

## 🔌 Wiring Checklist

### Web
- [ ] Backend route → conditional edge owned by T-054 (this task only feeds its verdict)

### Shared (All Platforms)
- [ ] Database model → N/A

## ✅ Verification

**Command**:
```bash
docker compose exec -T backend python -m pytest tests/unit/agent/test_verify_heavy_sql.py --no-cov -q
docker compose exec -T backend ruff check src/agent/nodes/verify.py
```
**Success Criteria**: pytest reports all tests `passed` (each deterministic-gate check + single judge-call invocation, with mocked LLM); ruff prints `All checks passed!`.

**Expected output (pytest tail)**:
```
... passed
```

## 📝 Completion Log

- [x] Code implemented
- [x] Tests passed — 77 unit tests in `test_verify_heavy_sql.py` + 21 light-path (`test_verify_node.py`); full `tests/unit/agent/` suite 295 passed
- [x] Linter passed — `ruff check src/agent/nodes/verify.py` + both test files clean
- [x] Wiring checklist verified — verdict feeds the R4b edge owned by T-054 (graph wiring deferred to T-058)
- [x] Integration verification passed — heavy path exercised by synthetic fixtures (see forward-contract note)

## 🧾 Completion Notes (deviations + forward contracts)

Reviewed by code-reviewer + 2 independent security experts (security-auditor, backend-security-coder) + an architect supervisor adjudication. All CRITICAL/HIGH findings fixed; LOW items deferred (see below).

**Deviations from the R3 spec (recorded in `specs/_defaults/changelog.md` deviation log):**
1. **`missing_filter` demoted to warning-only.** R3 listed "filter/JOIN present when implied" as a gate check. The heuristic (`_query_implies_filter` AND no WHERE/JOIN) is noisy (false positives on `GROUP BY`/`ORDER BY`/"data for report"), and a false positive forces a wasted retry. Per supervisor ruling §3 it is still computed and recorded in `verification.checks`, but the gate-fail set is now **`zero_rows_when_expected OR schema_mismatch`** only. Ambiguous-filter cases route to the judge instead of being pre-rejected.
2. **`schema_mismatch` approximated.** R3 check #3 says "every referenced table/column exists in the **schema sketch**." The verify node has no schema sketch in `StepResult` (no structured column metadata), so it is implemented as "SELECT-list columns ⊆ columns recovered from the rendered result rows," skipping the check (route-to-judge) for `SELECT *` / aggregates / undeterminable projections rather than false-failing.

**Forward contracts (heavy path is currently dormant):**
- The executor (T-053) always sets `generated_sql=None`, so the heavy path is exercised only by synthetic fixtures today. A future SQL-execution producer MUST emit each result row as identifier-prefixed `col: value\n...` text for `_extract_result_columns` to recover the column set (documented in the `verify.py` module docstring).

**Deferred (non-blocking) follow-ups:** `possible_truncation` `==`→`>=` + shared LIMIT constant (M2); drop weak word "how" from result-imply set (L3); narrow `except Exception`→sqlglot error types + richer fallback logging (SEC-6 remainder); collapse `_build_verify_delta` dual hint-keys param (LOW-1); optional `secrets`-seeded fence nonce + `str()`-coerce `sub_query` before neutralize (security LOW).

**Security posture:** judge prompt uses per-call nonce data fences with unconditional close-tag neutralization (breakout does not depend on nonce secrecy); model `reason` is never echoed into the retried `sub_query` (canned hints only); all LLM-derived strings `_safe_log`-sanitized before logging; non-dict JSON / non-dict chunks / oversized SQL all fail closed. Security verdict: CLEAR-TO-COMMIT.
