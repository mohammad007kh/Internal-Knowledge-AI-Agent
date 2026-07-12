# Task: T-050 - token-accumulation

**Status**: Pending
**Created**: 2026-06-04 | **Completed**: N/A
**User Story**: US6 (bounded cost & operator measurement)
**Requirement**: FR-019, FR-021
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

- **Bounded cost (FR-019)**: every question runs under hard limits; a per-turn token ceiling is one of them. The ceiling can only be enforced if token usage is accumulated into state — today usage is measured per-node and discarded (only Langfuse sees it).
- **Cost recording (FR-021)**: per-question processing cost MUST be recorded for operator trend review (users see it only as an unobtrusive plain-language note).
- **Constitution II (LLM Observability)**: every LLM call is Langfuse-traced with a stage name; this task additionally emits a `turn_token_cost` Langfuse **score** at turn end.

**LLM-calling node set for token accumulation (R2 — COPY VERBATIM from data-model §2b):**

> Each returns its usage delta into the additive reducers: planner · source-catalog/routing call (if retained) · SQL-generation · retrieval_grader (light) · retrieval_grader (heavy judge) · clarification detection (when enabled) · synthesizer (budget-ESTIMATED pre-call from prompt size + max_tokens, reconciled post-stream — its usage arrives on the final streamed chunk). Offline eval judge excluded (not a turn cost).

**Synthesizer estimate-then-reconcile (R2 — COPY VERBATIM from data-model §2b):**

> Synthesizer output is budget-ESTIMATED pre-call, reconciled post-stream. Its usage arrives on the final streamed chunk, AFTER tokens have streamed to the user — so the budget guard treats synthesizer output as **estimated pre-call** (prompt size + configured max_tokens) and reconciles actuals post-stream for the cost record. SC-004's guarantee: pre-synthesis spend is hard-guarded; the synthesizer call is bounded by its own max_tokens.

**Additive reducer rule (data-model §2):** `total_input_tokens` / `total_output_tokens` are EXISTING fields converted to `Annotated[int, operator.add]` so nodes return deltas (no read-modify-write races).

### Current-state gap (must fix all)

- `backend/src/agent/nodes/generate.py` returns only `final_answer` and drops `response.usage`.
- `backend/src/agent/nodes/source_router.py` and `backend/src/agent/nodes/text_to_query.py` measure `response.usage` but drop it.
- Any other LLM-calling node in the enumerated set must return its delta.

### API Context

Not applicable — state + node return contracts only.

### Gate Criteria

- [ ] `total_input_tokens` / `total_output_tokens` are `Annotated[int, operator.add]` in `state.py`.
- [ ] Every LLM-calling node in the enumerated set returns `{total_input_tokens: <delta>, total_output_tokens: <delta>}`.
- [ ] Synthesizer estimates pre-call (prompt size + max_tokens) and reconciles post-stream for the cost record.
- [ ] `turn_token_cost` Langfuse score emitted at turn end with the accumulated totals.
- [ ] No node performs read-modify-write of the token fields (deltas only).

### Dependencies

- None (Slice C0 — independently testable prerequisite).

---

## 🎯 Objective

Make per-turn token usage a first-class, accumulated state value so the budget guard (T-057) can enforce a hard ceiling and the cost record (FR-021) is accurate — by converting the two token fields to additive reducers and having every LLM-calling node return its usage delta, with the synthesizer following estimate-then-reconcile.

## 🛠️ Implementation Details

### Files to Create

- `backend/tests/unit/agent/test_token_accumulation.py` — asserts accumulated totals across a mocked multi-node run.

### Files to Update (REQUIRED)

- `backend/src/agent/state.py` — change `total_input_tokens` / `total_output_tokens` to `Annotated[int, operator.add]` (add `import operator`).
- `backend/src/agent/nodes/generate.py` — return usage delta; implement synthesizer estimate-then-reconcile; emit `turn_token_cost` Langfuse score at turn end.
- `backend/src/agent/nodes/source_router.py` — return usage delta instead of dropping `response.usage`.
- `backend/src/agent/nodes/text_to_query.py` — return usage delta instead of dropping `response.usage`.
- Any other node in the enumerated LLM-calling set (planner/grader nodes land in later tasks — wire their deltas there per the same contract; this task fixes the EXISTING droppers). The EXISTING-dropper node list to fix here: `generate.py` (synthesizer), `source_router.py`, `text_to_query.py`, and `clarify.py`/clarification-detection IF it makes an LLM call when enabled (read it to confirm). Note: planner/grader nodes created later wire the same contract in their own tasks.

### Code/Logic Requirements

- Read `state.py` first; convert ONLY the two token fields to reducers, leaving all other fields intact.
- Each LLM node returns a partial state dict `{"total_input_tokens": delta_in, "total_output_tokens": delta_out}`; the reducer sums across the run.
- Synthesizer: before the call, estimate output tokens as `min(prompt_token_estimate?, configured max_tokens)` — record the ESTIMATE for the pre-call budget snapshot; after the stream completes, read actuals from the final chunk and reconcile the cost record.
- Emit `turn_token_cost` as a Langfuse score (numeric) keyed to the trace at turn end (Constitution II).
- Acceptance Criteria:
  - A mocked run through ≥3 LLM nodes yields `total_input_tokens` / `total_output_tokens` equal to the SUM of per-node deltas.
  - Synthesizer pre-call estimate is present in state before streaming; reconciled actual replaces it in the cost record post-stream.

## 🔌 Wiring Checklist

### Web
- [ ] Backend route → N/A
- [ ] API endpoint → N/A

### Shared (All Platforms)
- [ ] Database model → N/A (LangGraph state, not persisted)

## ✅ Verification

**Command**:
```bash
docker compose exec -T backend python -m pytest tests/unit/agent/test_token_accumulation.py --no-cov -q
docker compose exec -T backend ruff check src/agent/state.py src/agent/nodes/generate.py
```
**Success Criteria**: pytest reports all tests `passed` (accumulated totals == sum of mocked per-node deltas; synthesizer estimate→reconcile asserted); ruff prints `All checks passed!`.

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
