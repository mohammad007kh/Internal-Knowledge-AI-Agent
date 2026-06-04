# Task: T-052 - planner-node

**Status**: Pending
**Created**: 2026-06-04 | **Completed**: N/A
**User Story**: US2 (multi-step planning), US4 (clarify trigger)
**Requirement**: FR-006, FR-007, FR-008, FR-009, FR-014 (trigger)
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

- **Plan caps (FR-006/FR-007)**: ≤5 steps; each step targets one source; steps may declare `depends_on`. Every question goes through planning.
- **Permission honouring (FR-009)**: inaccessible sources are never planned, queried, or named with inaccessible detail. The planner is given ONLY the user's permitted sources.
- **Clarify trigger (FR-014)**: when the planner cannot confidently choose between real alternatives, it emits `needs_clarification` with 2-4 options BEFORE executing; all option sources must come from the permitted set.
- **Constitution II**: the planner LLM call is Langfuse-traced under the `planner` stage.
- **Intent prompt hygiene (plan.md security rule 1)**: per-source intent metadata (purpose/examples/out_of_scope) renders inside unambiguous delimiters and is treated as data, never instructions.

**SECURITY RULE 2 — server-side permission assertion (plan.md, embedded verbatim):**

> Server asserts `plan.steps[].source_id ⊆ requesting user's permitted set` BEFORE emitting the `plan` event (LLM hallucination guard). Violations → replan or honest-failure path, never emission. Clarification options are generated only from the permitted set.

This assertion runs in this node BEFORE the `plan` SSE event is emitted: every `steps[].source_id` MUST be within the requesting user's permitted source set. A violation (planner hallucinated an out-of-set id) MUST drop to the honest-failure path — never emit the event.

### API Context (SSE — `plan` event, COPY shape from contracts/sse-events.md)

```jsonc
event: plan
data: {
  "revision": 0,                       // 0 = initial, 1 = revised
  "reason": null,                      // present when revision == 1
  "steps": [
    {
      "id": "s1",
      "label": "Read names from users.csv",   // user-facing, plain language
      "source_id": "…uuid…",
      "source_name": "users.csv",
      "depends_on": []
    }
  ]
}
```
UI rule (FR-008): plan card renders only when `steps.length >= 2` or `revision >= 1` or a clarification occurred; 1-step plans surface via the status line only. (Server emits regardless; UI gates.)

### Gate Criteria

- [ ] `planner.py` emits a ≤5-step plan via structured output from `raw_user_intent` + per-source intent metadata for PERMITTED sources only.
- [ ] May emit `needs_clarification` with 2-4 options, all sourced from the permitted set.
- [ ] SERVER-SIDE permission assertion runs BEFORE the `plan` event; out-of-set `source_id` → honest-failure path, never emitted.
- [ ] `plan` event payload matches the contract shape above.
- [ ] Intent metadata rendered as delimited data, never instructions.
- [ ] `planner` Langfuse span present; node returns its token-usage delta (T-050 contract).

### Dependencies

- [T-051 agent-state-plan-types](./T-051-agent-state-plan-types.md) — consumes `PlanStep` and the plan state fields.
- [T-050 token-accumulation](./T-050-token-accumulation.md) — returns its usage delta into the reducers.
- Reads intent from T-024's wiring (mock-able for this task's unit tests).

---

## 🎯 Objective

Implement the planner node that decomposes the user's question into a bounded (≤5-step), permission-clipped, structured plan — or a clarify-with-options request — and enforces a server-side `source_id ⊆ permitted` assertion before any `plan` SSE event is emitted.

## 🛠️ Implementation Details

### Files to Create

- `backend/src/agent/nodes/planner.py` — the planner node.
- `backend/src/prompts/planner.v1.txt` — planner prompt (renders raw_user_intent + per-source intent metadata in `<source_purpose>…</source_purpose>`-style delimiters; instructs structured ≤5-step output with `depends_on` and `{{sN.output}}` references; instructs `needs_clarification` with 2-4 options when genuinely stuck).
- `backend/tests/unit/agent/test_planner_node.py` — mocked-LLM tests: cap enforcement, permission assertion trip, event shape, clarify-with-options.

### Files to Update (REQUIRED)

- `backend/src/agent/stage_defaults.py` — add the `planner` stage default (per data-model §7; `STAGE_DEFAULTS` dict).
- `backend/src/agent/nodes/__init__.py` — export the new node so the pipeline builder (T-058) can import it.
- `backend/src/schemas/chat.py` — add ALL FOUR new members to `StreamEventType` (`PLAN = "plan"`, `STEP = "step"`, `REPLAN = "replan"`, `BUDGET = "budget"`) plus their `ChatStreamEvent` factory classmethods, in THIS task (first emitter owns the enum). Note: T-053/T-056/T-057 emit via these members — they do NOT re-add them.

### Code/Logic Requirements

- Input: `raw_user_intent` + the requesting user's permitted sources with their intent metadata (purpose/examples/out_of_scope rendered delimiter-wrapped).
- Output: a `list[PlanStep]` (≤5; cap enforced in code, not just prompt) OR a clarification payload `{question, options:[2-4], allow_free_text:true}` with all option sources ∈ permitted set.
- BEFORE emitting the `plan` event, assert `{step.source_id for step in plan} ⊆ permitted_set`. On violation: do NOT emit; route to honest-failure (no `plan` event, no source names leaked).
- Emit the `plan` event payload exactly per the contract shape.
- Wrap the LLM call in a `planner` Langfuse span; return the usage delta (`total_input_tokens`/`total_output_tokens`) per the T-050 reducer contract.
- Acceptance Criteria (mocked LLM):
  - 6-step model output is capped/rejected to ≤5.
  - A plan containing an out-of-permitted-set `source_id` trips the assertion and yields the honest-failure route with NO `plan` event.
  - A confident question yields a plan; an ambiguous one yields `needs_clarification` with 2-4 permitted-set options.
  - A schema test asserts the four new `StreamEventType` members (`PLAN`/`STEP`/`REPLAN`/`BUDGET`) exist with their `"plan"`/`"step"`/`"replan"`/`"budget"` values.

## 🔌 Wiring Checklist

### Web
- [ ] Backend route → graph wiring deferred to T-058 (this node is built + exported here)
- [ ] API endpoint → N/A (SSE event via stream service, wired in T-058)

### Shared (All Platforms)
- [ ] Database model → N/A

## ✅ Verification

**Command**:
```bash
docker compose exec -T backend python -m pytest tests/unit/agent/test_planner_node.py --no-cov -q
docker compose exec -T backend ruff check src/agent/nodes/planner.py
```
**Success Criteria**: pytest reports all tests `passed` (cap enforced, permission assertion trips on out-of-set id with no event emitted, event shape matches, clarify options all permitted, and the schema test asserting the four new `StreamEventType` members `PLAN`/`STEP`/`REPLAN`/`BUDGET` exist); ruff prints `All checks passed!`.

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
