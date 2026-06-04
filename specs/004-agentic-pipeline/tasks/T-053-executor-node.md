# Task: T-053 - executor-node

**Status**: Pending
**Created**: 2026-06-04 | **Completed**: N/A
**User Story**: US2 (multi-step planning), US3 (per-step execution & narration)
**Requirement**: FR-006, FR-009, FR-016
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

- **Permission re-check at execution (FR-009 / FX41 lesson)**: each step targets a SINGLE `source_id`; re-clip the permission at execution time (like `source_router` does) — never trust the plan-time check alone.
- **Step-scoped scratch (data-model §2)**: the executor sets per-step scratch (one `source_id`, the step `sub_query`, that source's schema chunk) and writes results into `StepResult.output_chunks` — NOT into the turn-wide `retrieved_chunks`.
- **Retrieval primitives as functions (R1)**: the v2 `text_to_query → retrieve_context` FIXED edge does NOT carry over; the executor calls the retrieval primitives AS FUNCTIONS for the single step source.
- **Step-scoped schema chunk**: obtain via `load_schema_context_chunks(source_ids=[step.source_id])`.
- **Always-narrate (FR-016)**: emit `step` SSE events on start AND finish/fail/retry, with ≤200-char generated NARRATION (first-3-items + count) — never raw row slices (security rule 5).
- **Constitution II**: any LLM call (e.g. SQL generation invoked as a function) is Langfuse-traced and returns its token delta (T-050 contract).

**STEP-INPUT BINDING — R1b interpolation rules (COPY VERBATIM from data-model §2b):**

> **Step-input binding (R1b):** executor deterministically interpolates `{{sN.output}}` references in `sub_query` before dispatch; list outputs render comma-joined capped at 50 items (`bound_inputs.truncated=true` on overflow); the verifier judges the RESOLVED sub_query.

The interpolation runs BEFORE dispatch. `StepResult.bound_inputs = {refs: dict[str,str], truncated: bool}` records exactly what was substituted. The verifier (T-054/T-055) judges the RESOLVED `sub_query`, not the template.

### API Context (SSE — `step` event, COPY shape from contracts/sse-events.md)

```jsonc
event: step
data: {
  "step_id": "s1",
  "role": "executor",                  // planner|executor|verifier|synthesizer
  "state": "started",                  // started | finished | failed | retrying
  "label": "Reading users.csv…",       // present-tense for started, past for finished
  "summary": null,                     // short partial result on finished: "Got 7 names: Alice, Bob, Carlos (+4)"
  "progress": {"current": 1, "total": 4}
}
```
`summary` ≤ 200 chars; application-generated narration (first-3 + count), never a raw slice of result rows.

### Gate Criteria

- [ ] Per-step scratch: single `source_id`, resolved `sub_query`, step-scoped schema chunk via `load_schema_context_chunks(source_ids=[step.source_id])`.
- [ ] Permission re-checked at execution for the step's `source_id`.
- [ ] R1b `{{sN.output}}` interpolation runs before dispatch; list outputs comma-joined capped at 50 items; `bound_inputs.truncated` set on overflow.
- [ ] Retrieval primitives called AS FUNCTIONS (no fixed v2 edge).
- [ ] Results written to `StepResult.output_chunks`, NOT `retrieved_chunks`.
- [ ] `step` events emitted on start AND finish/fail/retry; `summary` ≤200 chars, first-3+count narration, no raw rows.

### Dependencies

- [T-051 agent-state-plan-types](./T-051-agent-state-plan-types.md) — consumes `PlanStep`/`StepResult`/`bound_inputs`.
- [T-052 planner-node](./T-052-planner-node.md) — executes the steps the planner emits (incl. `{{sN.output}}` references).

---

## 🎯 Objective

Implement the executor node that runs ONE plan step in isolation — re-clipping permission, deterministically resolving `{{sN.output}}` references into the step's `sub_query`, loading only that source's schema chunk, calling retrieval primitives as functions, and emitting narrated `step` events while writing a step-scoped `StepResult`.

## 🛠️ Implementation Details

### Files to Create

- `backend/src/agent/nodes/executor.py` — the executor node.
- `backend/tests/unit/agent/test_executor_node.py` — interpolation cases (incl. >50-item truncation), permission re-check, step event emissions, narration format.

### Files to Update (REQUIRED)

- `backend/src/agent/nodes/__init__.py` — export the executor node for the T-058 graph builder.

### Code/Logic Requirements

- Read `current_step` from state; re-clip its `source_id` against the requesting user's permitted set (reuse the `source_router` re-clip pattern). If inaccessible → fail the step honestly (no inaccessible detail named).
- Resolve `{{sN.output}}` references from `past_steps` per R1b: list outputs comma-joined, capped at 50 items, `bound_inputs.truncated=true` on overflow; populate `bound_inputs.refs` with exactly what was substituted.
- Build per-step scratch: `{source_id: step.source_id, query: resolved_sub_query, schema_chunk: load_schema_context_chunks(source_ids=[step.source_id])}`.
- Call retrieval primitives as functions (not via the old fixed edge). Any LLM sub-call (e.g. SQL generation) is Langfuse-traced and returns a token delta.
- Write `output_chunks` and `generated_sql` (if any) into the step's `StepResult`; do NOT touch `retrieved_chunks`.
- Emit `step` events: `started` (present tense) on dispatch; `finished`/`failed`/`retrying` after, with a ≤200-char first-3+count `summary`.
- Acceptance Criteria (mocked):
  - `{{s1.output}}` with a 60-item list interpolates 50 items comma-joined and sets `truncated=true`.
  - An inaccessible step `source_id` fails the step without naming inaccessible detail.
  - `started` and `finished` events emitted with the contract shape; `summary` is narration, not raw rows.

## 🔌 Wiring Checklist

### Web
- [ ] Backend route → graph wiring deferred to T-058 (node built + exported here)
- [ ] API endpoint → N/A (SSE via stream service, wired in T-058)

### Shared (All Platforms)
- [ ] Database model → N/A

## ✅ Verification

**Command**:
```bash
docker compose exec -T backend python -m pytest tests/unit/agent/test_executor_node.py --no-cov -q
docker compose exec -T backend ruff check src/agent/nodes/executor.py
```
**Success Criteria**: pytest reports all tests `passed` (interpolation incl. 50-item truncation, permission re-check, step event emissions, narration format); ruff prints `All checks passed!`.

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
