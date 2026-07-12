# Task: T-056 - replan-node

**Status**: Done
**Created**: 2026-06-04 | **Completed**: 2026-06-10
**User Story**: US2 (multi-step planning), US3 (recovery)
**Requirement**: FR-007, FR-008
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

- **One revision cap (FR-007)**: a plan may be revised AT MOST ONCE per question (`plan_revision` 0→1). A second replan is impossible; the R4b state machine routes `retry_count==1 & plan_revision==1` to honest-failure, not here.
- **Announce + retain (FR-008)**: a revised plan MUST be announced with its reason; the superseded plan stays inspectable. Keep the superseded plan in state for the activity record.
- **Reason carried from the verifier**: the verifier's failure `reason` (T-054/T-055) is the input that informs the whole-plan revision.
- **SECURITY RULE 2 (plan.md)**: the SAME server-side permission assertion as the planner runs BEFORE the new `plan` event — every `steps[].source_id ⊆ permitted set`; a violation drops to honest-failure, never emits.
- **Constitution II**: the replan LLM call is Langfuse-traced under the `planner` stage and returns its token delta (T-050 contract).

### API Context (SSE — COPY shapes from contracts/sse-events.md)

`replan` event:
```jsonc
event: replan
data: {
  "reason": "CRM returned emails; switching to email match",
  "superseded_revision": 0
}
```
Always followed by a fresh `plan` event with `revision: 1`:
```jsonc
event: plan
data: { "revision": 1, "reason": "<carried reason>", "steps": [ ... ] }
```

### Gate Criteria

- [ ] Revises the WHOLE plan once; `plan_revision` 0→1 cap enforced (second replan impossible).
- [ ] Verifier `reason` carried into the revision and into the events.
- [ ] Emits `replan` event THEN a fresh `plan` event with `revision: 1` (exact shapes above).
- [ ] Superseded plan retained in state for the activity record.
- [ ] Same permission assertion as the planner BEFORE the new `plan` event; violation → honest-failure, never emit.
- [ ] `planner` Langfuse span; token delta returned.

### Dependencies

- [T-054 verify-node-light](./T-054-verify-node-light.md) — the verify R4b edge routes here on `unacceptable & retry==1 & revision<1`; the carried reason originates there.

---

## 🎯 Objective

Implement the replan node that performs the single allowed whole-plan revision — carrying the verifier's failure reason, retaining the superseded plan, enforcing the 0→1 revision cap and the pre-emission permission assertion, and emitting `replan` then a fresh `plan(revision:1)` event.

## 🛠️ Implementation Details

### Files to Create

- `backend/src/agent/nodes/replan.py` — the replan node.
- `backend/src/prompts/replan.v1.txt` — whole-plan revision prompt (takes raw_user_intent + permitted-source intent metadata + the carried failure reason + the superseded plan; emits a fresh ≤5-step plan).
- `backend/tests/unit/agent/test_replan_node.py` — cap enforcement (second replan impossible), event sequence (`replan` then `plan(revision:1)`), reason propagation, permission assertion.

### Files to Update (REQUIRED)

- `backend/src/agent/nodes/__init__.py` — export the replan node for the T-058 graph builder.

### Code/Logic Requirements

- Guard: only run when `plan_revision < 1`; on entry set `plan_revision = 1` and stash the current plan as `superseded_plan` in state.
- Call the revision LLM (`planner` stage) with the carried verifier reason; produce a fresh ≤5-step plan (reuse the planner's cap + structured-output logic).
- Run the planner permission assertion BEFORE emitting the new `plan` event; on violation drop to honest-failure (no event).
- Emit `replan` (with `reason`, `superseded_revision: 0`) then `plan` (with `revision: 1`, carried `reason`, fresh steps).
- Wrap the LLM call in a `planner` Langfuse span; return the token delta.
- Acceptance Criteria (mocked):
  - With `plan_revision == 1`, the node is never entered (routing covered by T-054's edge); attempting a second revision is impossible.
  - Event order is `replan` then `plan(revision:1)`; the reason is identical across both and matches the verifier reason.
  - An out-of-set `source_id` in the revised plan trips the assertion → honest-failure, no `plan` event.

## 🔌 Wiring Checklist

### Web
- [ ] Backend route → graph wiring deferred to T-058 (node built + exported here)
- [ ] API endpoint → N/A (SSE via stream service, wired in T-058)

### Shared (All Platforms)
- [ ] Database model → N/A

## ✅ Verification

**Command**:
```bash
docker compose exec -T backend python -m pytest tests/unit/agent/test_replan_node.py --no-cov -q
docker compose exec -T backend ruff check src/agent/nodes/replan.py
```
**Success Criteria**: pytest reports all tests `passed` (cap enforcement, `replan`→`plan(revision:1)` sequence, reason propagation, permission assertion); ruff prints `All checks passed!`.

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
