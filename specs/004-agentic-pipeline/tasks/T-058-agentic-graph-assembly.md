# Task: T-058 - agentic-graph-assembly

**Status**: Pending
**Created**: 2026-06-04 | **Completed**: N/A
**User Story**: US2 (multi-step planning), US5 (activity persistence), US6 (rollout)
**Requirement**: FR-026, FR-018 (partial), FR-021
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

- **Rollout flag (FR-026)**: `PIPELINE_AGENTIC_ENABLED` selects `_build_agentic_pipeline()` inside `build_pipeline()`; the v2 graph remains the rollback path. SANDBOX-FIRST: the sandbox endpoint honors the flag before general chat.
- **Constitution IV (Pipeline Safety)**: guardrail input/output nodes wrap the NEW graph UNCONDITIONALLY (cannot be bypassed); the reflector stays untouched and default-OFF.
- **Activity persistence (FR-018 partial / FR-021)**: the `done` event carries `activity_summary` (compact shape, data-model §3), built from `past_steps`/`plan`/tokens and persisted to `chat_messages.activity_summary`.

**`done` event extension — THREE code sites (plan.md C8, explicit):**
1. `DoneData` schema — add `activity_summary` field.
2. `ChatStreamEvent.done()` factory — accept/carry `activity_summary`.
3. `chat_stream_service.py` emission — build the compact summary and pass it.
(All in/around `backend/src/schemas/chat.py` + `backend/src/services/chat_stream_service.py`.)

**activity_summary compact shape (data-model §3, COPY for reference):**
```jsonc
{
  "step_count": 4, "source_count": 2, "had_replan": false, "had_failure": false,
  "budget_hit": false, "turn_tokens": {"input": 9120, "output": 1480},
  "cost_label": "medium",
  "plan": [ {"id": "s1", "label": "Read names from users.csv", "status": "done"} ],
  "superseded_plan": null, "revision_reason": null,
  "roles": [ {"role": "planner", "line": "…"}, {"role": "executor", "step": "s1", "line": "…"} ]
}
```
`roles[].line` and step labels capped at 200 chars (security rule 5).

### Graph topology (assembled here from T-052..T-057)

planner → (clarification-terminal? OR) executor → verify (OWNS conditional edge, R4b) → {next step | executor-retry | replan | synthesize}; budget_guard at loop edges (before step dispatch, before replan); synthesizer terminal. Guardrail input/output wrap the whole graph unconditionally.

### Gate Criteria

- [ ] `_build_agentic_pipeline()` assembled in `pipeline.py`, selected by `PIPELINE_AGENTIC_ENABLED` inside `build_pipeline()`; v2 remains rollback.
- [ ] Guardrail input/output wrap the new graph unconditionally (Constitution IV); reflector untouched/default-OFF.
- [ ] Sandbox endpoint honors the flag BEFORE general chat (sandbox-first).
- [ ] `done` event extended at ALL THREE sites (`DoneData`, `ChatStreamEvent.done()`, `chat_stream_service.py`) carrying `activity_summary`.
- [ ] `activity_summary` built from `past_steps`/`plan`/tokens (compact shape) and persisted to `chat_messages.activity_summary`.
- [ ] Graph-assembly test (flag on/off topologies) + integration smoke (1-step turn) asserting `done.activity_summary` present.

### Dependencies

- [T-052 planner-node](./T-052-planner-node.md), [T-053 executor-node](./T-053-executor-node.md), [T-054 verify-node-light](./T-054-verify-node-light.md), [T-055 verify-heavy-sql](./T-055-verify-heavy-sql.md), [T-056 replan-node](./T-056-replan-node.md), [T-057 budget-guard-diagnostics](./T-057-budget-guard-diagnostics.md) — assembles their exported nodes/edges into the graph.
- T-001 (config flags — `PIPELINE_AGENTIC_ENABLED`) and T-011 (migration 0037 — `chat_messages.activity_summary`).

---

## 🎯 Objective

Assemble the flag-selected agentic LangGraph from the nodes built in T-052..T-057, wrap it unconditionally with guardrails (Constitution IV), wire sandbox-first selection, and extend the `done` event across all three code sites to carry the persisted `activity_summary`.

## 🛠️ Implementation Details

### Files to Create

- `backend/tests/unit/agent/test_agentic_graph_assembly.py` — flag on/off topology assertions.
- `backend/tests/integration/test_agentic_done_summary.py` — 1-step streaming smoke asserting `done.activity_summary` present + persisted.

### Files to Update (REQUIRED)

- `backend/src/agent/pipeline.py` — add `_build_agentic_pipeline()`; select it in `build_pipeline()` on `PIPELINE_AGENTIC_ENABLED`; wrap with guardrail input/output unconditionally; keep v2 as rollback; reflector untouched.
- `backend/src/schemas/chat.py` — add `activity_summary` to `DoneData`; extend the `ChatStreamEvent.done()` factory to carry it.
- `backend/src/services/chat_stream_service.py` — build the compact `activity_summary` from `past_steps`/`plan`/tokens and pass it into the `done` emission; persist it to `chat_messages.activity_summary`.
- the sandbox chat endpoint/service — honor `PIPELINE_AGENTIC_ENABLED` before general chat (sandbox-first).

### Code/Logic Requirements

- Build the graph topology described above using the nodes/edges exported by T-052..T-057 (verify owns the R4b conditional edge; budget_guard at loop edges).
- `build_pipeline()` returns the agentic graph when the flag is on AND the request is in the sandbox path; otherwise the v2 graph (rollback).
- Guardrail input/output nodes must wrap the agentic graph with no bypass path (Constitution IV); confirm the reflector is not inserted.
- `activity_summary` is built per the compact shape (cost_label from budget fraction; roles one-liners ≤200 chars; superseded_plan/revision_reason present on replan).
- Acceptance Criteria:
  - Flag OFF → v2 topology; flag ON (sandbox) → agentic topology — both assertable in the assembly test.
  - A 1-step streamed turn emits `done` with a non-null `activity_summary` of the compact shape, and the row persists to `chat_messages.activity_summary`.

## 🔌 Wiring Checklist

### Web
- [x] **Backend route** → sandbox endpoint selects the agentic graph on the flag (sandbox-first)
- [x] **API endpoint** → `done` SSE event extended at all three sites; consumed by the frontend (Slice D)

### Shared (All Platforms)
- [x] **Database model** → `chat_messages.activity_summary` persisted (column from migration 0037, T-011)
- [x] **Environment var** → `PIPELINE_AGENTIC_ENABLED` (added in T-001) drives selection

## ✅ Verification

**Command**:
```bash
docker compose exec -T backend python -m pytest tests/unit/agent/test_agentic_graph_assembly.py --no-cov -q
docker compose exec -T backend python -m pytest tests/integration/test_agentic_done_summary.py --no-cov -q
```
**Success Criteria**: pytest reports all tests `passed` (flag on/off topologies; 1-step turn emits `done.activity_summary` of the compact shape, persisted).

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
