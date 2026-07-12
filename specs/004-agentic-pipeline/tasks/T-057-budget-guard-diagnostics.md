# Task: T-057 - budget-guard-diagnostics

**Status**: Done
**Created**: 2026-06-04 | **Completed**: 2026-06-10
**User Story**: US3 (honest failure), US6 (bounded cost & graceful stop)
**Requirement**: FR-013, FR-019, FR-020
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

- **Hard bounds (FR-019)**: every question runs under max steps / max retries / max revisions / token ceiling / deadline. The guard is DETERMINISTIC (no LLM) and runs at loop edges: BEFORE each step dispatch and BEFORE replan, against the `budget` snapshot in state.
- **Graceful wrap-up (FR-020)**: hitting the ceiling jumps to the synthesizer with budget context; the user gets the best partial answer + a calm note naming what was not completed. "Keep going" is a suggested reply that starts a NEW turn with a fresh budget — the per-turn cap is NEVER raised mid-turn.
- **Honest failure (FR-013)**: when no trustworthy answer is achievable, the response LEADS with an honest statement, offers an expandable "what I tried", and proposes next actions; FABRICATION IS PROHIBITED.
- **Guard placement precision (R2)**: the guard runs before each step dispatch and before replan. A single step may overshoot by at most one step's spend (SQL-gen + heavy-judge within a step have no intra-step check) — deliberate and bounded by `max_steps × worst-case-step-spend + synthesizer max_tokens`.
- **Synthesizer estimate (R2)**: synthesizer output is budget-ESTIMATED pre-call (prompt size + max_tokens); pre-synthesis spend is hard-guarded; the synthesizer call is bounded by its own max_tokens.
- **Stream/persistence hygiene (security rule 5)**: diagnostics narration is generated (first-3 + count), never raw row slices.

### API Context (SSE — `budget` event, COPY shape from contracts/sse-events.md)

```jsonc
event: budget
data: {
  "ceiling_hit": true,
  "not_completed": ["Verify rows match the names", "Write the full answer"],
  "offer_continue": true               // UI may render the "Keep going" quick-reply
}
```
`not_completed` labels are derived from the pending (unexecuted) plan steps.

### Diagnostics injector (FR-013 / R4)

A deterministic injector writes a `<RETRIEVAL_DIAGNOSTICS>` block into the synthesizer prompt for the honest-failure path: sources queried, SQL run, rows returned, verification reasons — so "queried X, got 0 rows, because…" is grounded, not guessed. The synthesizer prompt branch text (honest-failure framing: lead with honest statement; expandable what-I-tried; no fabrication) is part of THIS task.

### Gate Criteria

- [ ] `budget_guard.py` deterministic (no LLM) check at loop edges (before each step dispatch, before replan) against `budget` snapshot (steps/retries/revisions/token ceiling/deadline).
- [ ] Trip → jump to synthesizer with budget context + emit `budget` SSE event (shape above; `not_completed` from pending plan steps; `offer_continue: true`).
- [ ] Diagnostics injector writes a `<RETRIEVAL_DIAGNOSTICS>` block (sources queried, SQL run, rows returned, verification reasons) into the synthesizer prompt — generated narration, no raw rows.
- [ ] Honest-failure synthesizer branch leads with honest statement + expandable what-I-tried; fabrication prohibited.
- [ ] Graceful budget wrap-up message uses the spec's decided copy.
- [ ] Overshoot-by-one-step behavior documented in code + test.

### Dependencies

- [T-051 agent-state-plan-types](./T-051-agent-state-plan-types.md) — reads the `budget` snapshot + `past_steps`/`plan` for diagnostics.

---

## 🎯 Objective

Implement the deterministic budget guard (loop-edge cap check → graceful synthesizer jump + `budget` event) and the diagnostics injector that grounds the honest-failure synthesizer branch with a `<RETRIEVAL_DIAGNOSTICS>` block — guaranteeing bounded termination and fabrication-free failure.

## 🛠️ Implementation Details

### Files to Create

- `backend/src/agent/budget_guard.py` — deterministic guard (edge function) + diagnostics injector.
- `backend/tests/unit/agent/test_budget_guard.py` — guard trips at each cap; overshoot-by-one-step documented behavior; diagnostics block content; `budget` event shape.

### Files to Update (REQUIRED)

- `backend/src/agent/nodes/__init__.py` — export the guard edge function + injector for the T-058 graph builder.
- the synthesizer prompt (honest-failure branch) — add the branch text + `<RETRIEVAL_DIAGNOSTICS>` placeholder. (Use the existing synthesizer/generate prompt asset; do NOT create a duplicate generator.)

### Code/Logic Requirements

- Guard runs BEFORE each step dispatch and BEFORE replan; compares accumulated state (steps used, retries, revisions, `total_input_tokens`/`total_output_tokens` + synthesizer pre-call estimate, wall-clock vs deadline) to the `budget` snapshot.
- On any cap breach: route to the synthesizer with `budget_hit=True` + budget context; emit the `budget` event with `not_completed` derived from pending plan-step labels and `offer_continue: true`.
- Diagnostics injector: build `<RETRIEVAL_DIAGNOSTICS>` from `past_steps` (sources queried, generated_sql, row counts, verification reasons) as generated narration (first-3 + count), inject into the synthesizer prompt for both budget-hit and honest-failure paths.
- "Keep going" carries NO special endpoint — it is an ordinary next-turn user message; the cap is never raised mid-turn (assert this is documented, not implemented as a raise).
- Acceptance Criteria:
  - Guard trips independently at each of: step cap, retry cap, revision cap, token ceiling, deadline.
  - Overshoot-by-one-step is asserted as the documented bounded behavior.
  - `<RETRIEVAL_DIAGNOSTICS>` contains sources/SQL/rows/reasons with no raw row slices.
  - `budget` event matches the contract shape with `not_completed` from pending steps.

## 🔌 Wiring Checklist

### Web
- [ ] Backend route → graph wiring (edge guard) deferred to T-058 (function built + exported here)

### Shared (All Platforms)
- [ ] Database model → N/A

## ✅ Verification

**Command**:
```bash
docker compose exec -T backend python -m pytest tests/unit/agent/test_budget_guard.py --no-cov -q
docker compose exec -T backend ruff check src/agent/budget_guard.py
```
**Success Criteria**: pytest reports all tests `passed` (guard trips at each cap, overshoot documented, diagnostics block content, budget event shape); ruff prints `All checks passed!`.

**Expected output (pytest tail)**:
```
... passed
```

## 📝 Completion Log

- [ ] Code implemented
- [ ] Tests passed
- [ ] Linter passed
- [ ] Wiring checklist verified
- [ ] Integration verification passed
