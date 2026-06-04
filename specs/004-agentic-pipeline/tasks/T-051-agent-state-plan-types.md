# Task: T-051 - agent-state-plan-types

**Status**: Pending
**Created**: 2026-06-04 | **Completed**: N/A
**User Story**: US2 (multi-step planning), US3 (verification & honesty)
**Requirement**: FR-006, FR-007
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

- **Plan decomposition (FR-006)**: a question is decomposed into an ordered plan; a step may target one source and may depend on earlier step outputs. Every question goes through planning (uniform architecture).
- **Bounded plans (FR-007)**: ≤5 steps, ≤1 plan revision per question.
- **Immutable intent (data-model §2)**: `raw_user_intent` is the original utterance and is NEVER mutated. NOTE: today `query` is rewritten by `query_analyzer` / history loading — those mutate `query`; `raw_user_intent` must be a separate, never-mutated field.
- **No `clarification_pending` field (data-model §2)**: clarification is a TERMINAL SSE event; the reply arrives as the next turn via history. A cross-turn pending field would be vestigial — do NOT add one.

**PlanStep typed dict (COPY VERBATIM from data-model §2):**

> **PlanStep** (typed dict): `{id: str, description: str, source_id: UUID, sub_query: str, depends_on: list[str], status: pending|active|done|failed, retry_count: int}` — single source per step (R1). `sub_query` may contain named references (`{{s1.output}}`) that the executor resolves deterministically before dispatch (R1b).

**StepResult typed dict (COPY VERBATIM from data-model §2):**

> **StepResult**: `{step_id, output_chunks: list[dict], generated_sql: str|None, bound_inputs: {refs: dict[str, str], truncated: bool} | None, verification: {verdict: acceptable|partial|unacceptable, reason: str, checks: dict}, narration: str}` — `bound_inputs` records exactly what was interpolated (R1b); the verifier judges the RESOLVED sub_query. `output_chunks` are step-scoped (the executor sets per-step scratch — one source_id, step sub_query, that source's schema chunk — and writes results here, NOT into the turn-wide `retrieved_chunks`).

**State fields to add (data-model §2):** `raw_user_intent: str` (never mutated) · `plan: list[PlanStep]` · `past_steps: list[StepResult]` · `current_step: PlanStep | None` · `plan_revision: int` (0 or 1) · `budget: {max_steps, max_retries_per_step, max_revisions, token_ceiling, deadline}` (read-only config snapshot). `narration` ≤ 200 chars.

### API Context

Not applicable — LangGraph state types only.

### Gate Criteria

- [ ] `PlanStep` matches the field set/shape above EXACTLY.
- [ ] `StepResult` matches the field set/shape above EXACTLY (incl. `bound_inputs`, `verification`, `narration`).
- [ ] `raw_user_intent` added and documented as never-mutated (note `query`'s current mutation by query_analyzer/load_history).
- [ ] `plan` / `past_steps` / `current_step` / `plan_revision` / `budget` added.
- [ ] NO `clarification_pending` field.
- [ ] mypy clean.

### Dependencies

- [T-050 token-accumulation](./T-050-token-accumulation.md) — builds on the token reducers in `state.py`.

---

## 🎯 Objective

Define the typed `PlanStep` and `StepResult` structures and extend `AgentState` with the plan-and-execute fields exactly per data-model §2, establishing the data contract every later agentic node depends on — without mutating `raw_user_intent` and without a clarification-pending field.

## 🛠️ Implementation Details

### Files to Create

- `backend/tests/unit/agent/test_agent_state_plan_types.py` — type/shape tests for `PlanStep`, `StepResult`, and the new state fields.

### Files to Update (REQUIRED)

- `backend/src/agent/state.py` — add `PlanStep` and `StepResult` (TypedDicts) and the new `AgentState` fields. Reuse the existing `TypedDict(total=False)` idiom and `Annotated`/reducer conventions already in the file.

### Code/Logic Requirements

- Read `state.py` first (it already holds `total_input_tokens`/`total_output_tokens` reducers from T-050); mirror its style.
- `PlanStep` and `StepResult` are `TypedDict` (LangGraph state values must be JSON-serializable dict shapes, not frozen dataclasses).
- `status` and `verdict` are constrained string literals (`Literal[...]`).
- `budget` is a read-only snapshot dict; the guard (T-057) reads it, no node mutates it.
- Acceptance Criteria:
  - A valid `PlanStep` / `StepResult` dict type-checks; a missing required key fails the shape test.
  - mypy passes on `state.py`.

## 🔌 Wiring Checklist

### Web
- [ ] Backend route → N/A

### Shared (All Platforms)
- [ ] Database model → N/A (LangGraph state, not persisted)

## ✅ Verification

**Command**:
```bash
docker compose exec -T backend python -m pytest tests/unit/agent/test_agent_state_plan_types.py --no-cov -q
docker compose exec -T backend mypy src/agent/state.py
```
**Success Criteria**: pytest reports all tests `passed` (shapes enforced; no `clarification_pending`); mypy prints `Success: no issues found`.

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
