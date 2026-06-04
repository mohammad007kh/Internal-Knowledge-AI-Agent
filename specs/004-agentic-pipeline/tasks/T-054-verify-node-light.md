# Task: T-054 - verify-node-light

**Status**: Pending
**Created**: 2026-06-04 | **Completed**: N/A
**User Story**: US3 (verification & honesty)
**Requirement**: FR-010, FR-012
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

- **Light grading on EVERY step (FR-010)**: every step's result is checked for whether it plausibly answers the step's goal before being trusted, via the `retrieval_grader` stage slot (a ~200-token call: "does this result answer the sub_query? YES/PARTIAL/NO + reason"). The grader judges the RESOLVED `sub_query` (R1b).
- **Retry-once-then-stop (FR-012)**: on a failed check, retry the step once with the verifier's reason injected; on a second failure, stop that line of work.
- **`retrieval_grader` slot (data-model §7)**: shared by light + heavy verification; do NOT reuse `clarification_detector`. The stage slot is seeded from `STAGE_DEFAULTS` (foundation task T-012).
- **Constitution II**: the grader LLM call is Langfuse-traced under `retrieval_grader` and returns its token delta (T-050 contract).
- **This node OWNS the conditional edge** — it routes to next-step / executor (retry) / replan / synthesize per the state machine below.

**VERIFY → RETRY → REPLAN STATE MACHINE (R4b — COPY VERBATIM from data-model §2b):**

| Condition | Next |
|---|---|
| `verify == acceptable` | next step (or synthesize when plan empty) |
| `verify == partial` | accept + record verdict; synthesizer prompt branches (no retry burn) |
| `verify == unacceptable` AND `step.retry_count < 1` | **executor**, same step, verifier reason injected, `retry_count += 1` |
| `verify == unacceptable` AND `retry_count == 1` AND `plan_revision < 1` | **replan** (whole-plan revision, reason carried) |
| `verify == unacceptable` AND `retry_count == 1` AND `plan_revision == 1` | **synthesize-honest-failure** (diagnostics injected) |

> The **verify node owns the conditional edge**. Three-level fallback: retry → replan → honest failure. Both caps live in state and are checked here AND by the edge-level budget guard (belt + suspenders).

### API Context

Not applicable directly — `step` events for verifier role are emitted via the stream service (wired T-058); this task focuses on the verdict + edge logic.

### Gate Criteria

- [ ] Light grader runs on EVERY step via the `retrieval_grader` slot (~200-token call), judging the RESOLVED `sub_query`.
- [ ] Verdict recorded into `StepResult.verification = {verdict, reason, checks}`.
- [ ] Conditional edge implements ALL FIVE rows of the R4b table exactly.
- [ ] `acceptable` → next step / synthesize-when-empty; `partial` → accept + record (synthesizer branches, no retry); `unacceptable`+retry<1 → executor same step with reason injected + `retry_count += 1`; `unacceptable`+retry==1+revision<1 → replan; `unacceptable`+retry==1+revision==1 → synthesize-honest-failure.
- [ ] `retrieval_grader` Langfuse span present; token delta returned.

### Dependencies

- [T-053 executor-node](./T-053-executor-node.md) — grades the `StepResult` the executor produces (resolved sub_query).
- T-012 (foundation) — the `retrieval_grader` stage slot seed (`STAGE_DEFAULTS`).

---

## 🎯 Objective

Implement the verify node that light-grades every step (`retrieval_grader` slot) against its resolved sub_query, records the verdict on the `StepResult`, and OWNS the conditional edge implementing the full R4b verify→retry→replan→honest-failure state machine.

## 🛠️ Implementation Details

### Files to Create

- `backend/src/agent/nodes/verify.py` — the verify node + its conditional-edge routing function.
- `backend/src/prompts/retrieval_grader.v1.txt` — light grader prompt ("does this result answer the sub_query? YES/PARTIAL/NO + reason"; judges the resolved sub_query).
- `backend/tests/unit/agent/test_verify_node.py` — covers ALL FIVE rows of the R4b table with a mocked grader.

### Files to Update (REQUIRED)

- `backend/src/agent/nodes/__init__.py` — export the verify node + edge function for the T-058 graph builder.

### Code/Logic Requirements

- Read the just-executed step's `StepResult` (with its RESOLVED `sub_query` from `bound_inputs`); call the `retrieval_grader` slot once (~200 tokens) → `{verdict: acceptable|partial|unacceptable, reason, checks}`; write into `StepResult.verification`.
- Implement the edge as a routing function returning the next node name per the R4b table (use the literal conditions/columns above).
- On retry: increment `current_step.retry_count` and inject the verifier `reason` so the executor's re-attempt is reason-informed (FR-012).
- Wrap the grader call in a `retrieval_grader` Langfuse span; return the token delta.
- Acceptance Criteria (mocked grader, one test per row):
  - `acceptable` with steps remaining → next step; with empty plan → synthesize.
  - `partial` → accepted + recorded, no retry burn.
  - `unacceptable` & `retry_count==0` → executor (same step), `retry_count` becomes 1, reason injected.
  - `unacceptable` & `retry_count==1` & `plan_revision==0` → replan.
  - `unacceptable` & `retry_count==1` & `plan_revision==1` → synthesize-honest-failure.

## 🔌 Wiring Checklist

### Web
- [ ] Backend route → graph wiring (conditional edge) deferred to T-058 (node + edge fn built/exported here)

### Shared (All Platforms)
- [ ] Database model → N/A

## ✅ Verification

**Command**:
```bash
docker compose exec -T backend python -m pytest tests/unit/agent/test_verify_node.py --no-cov -q
docker compose exec -T backend ruff check src/agent/nodes/verify.py
```
**Success Criteria**: pytest reports all tests `passed` (all five R4b rows routed correctly with mocked grader); ruff prints `All checks passed!`.

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
