# Task: T-059 - integration-us2-us3

**Status**: Pending
**Created**: 2026-06-04 | **Completed**: N/A
**User Story**: US2 (multi-step planning), US3 (verification & honesty)
**Requirement**: FR-006, FR-007, FR-008, FR-009, FR-010, FR-011, FR-012, FR-013 (end-to-end)
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

### Domain Rules (end-to-end behaviors under test)

- **Chained multi-step (FR-006/SC-001)**: a file→database question produces a `plan` event, per-step events in dependency order, and a final grounded answer that could only come from chaining the two sources.
- **Retry-then-abstain (FR-012/FR-013/SC-002)**: a guaranteed-empty lookup retries ONCE then abstains, leading with "couldn't find a reliable answer", with an expandable diagnostics account and NO fabricated rows.
- **Graceful budget (FR-019/FR-020/SC-004)**: a tiny ceiling trips the `budget` event and yields the best partial answer + a calm not-completed note — never a silent failure.
- **Permission honouring (FR-009)** holds throughout (no inaccessible source planned/queried/named).
- These run against the SANDBOX endpoint with `PIPELINE_AGENTIC_ENABLED` on (sandbox-first rollout), via httpx streaming.

### API Context

httpx streaming integration against the admin sandbox chat endpoint (the SSE consumer that ships first); the SSE wire grammar is byte-identical to the live endpoint. Events to assert: `plan`, `step*`, `budget?`, `delta*`, `done` (with `activity_summary`).

### Gate Criteria

- [ ] (a) Multi-step chained scenario (file names → DB query): asserts `plan` event, per-step events, ORDERED execution, final grounded answer chaining both sources.
- [ ] (b) Honesty scenario (absent names): asserts ONE retry then abstain, leading "couldn't find a reliable answer", diagnostics present, NO fabricated rows.
- [ ] (c) Budget scenario (tiny ceiling): asserts graceful `budget` event + partial answer (no silent failure).
- [ ] All three run against the sandbox endpoint with the flag ON.

### Dependencies

- [T-058 agentic-graph-assembly](./T-058-agentic-graph-assembly.md) — drives the assembled, flag-selected sandbox graph end-to-end.

---

## 🎯 Objective

Prove Stories 2+3 end-to-end with httpx streaming integration tests against the sandbox endpoint (flag on): a chained multi-step answer, a retry-then-honest-abstain, and a graceful budget wrap-up — each asserting the wire events and the fabrication-free / bounded guarantees.

## 🛠️ Implementation Details

### Files to Create

- `backend/tests/integration/test_agentic_pipeline.py` — the three streaming scenarios (a), (b), (c).
- Test fixtures: a file source seeded with known names + a database source seeded with matching users (synthetic-only data — no real names/PII; the repo is PUBLIC, security rule 4).

### Files to Update (REQUIRED)

- `backend/tests/integration/conftest.py` (or the existing integration fixtures module) — register the sandbox httpx streaming client + the synthetic file/db sources, with `PIPELINE_AGENTIC_ENABLED` forced on for these tests.

### Code/Logic Requirements

- (a) Seed a file containing names + a DB containing those users; ask the combined question; collect the SSE stream; assert: a `plan` event with ≥2 steps; `step` events for each step in dependency order; a final answer containing per-user results that require both sources.
- (b) Ask a question whose DB lookup returns nothing (names absent); assert exactly one retry `step` event then an abstain; the final answer leads with "couldn't find a reliable answer"; a diagnostics account is available; assert NO fabricated data points appear.
- (c) Configure a tiny token ceiling for the turn; ask an oversized question; assert a `budget` event with `ceiling_hit: true` + `not_completed`, a best partial answer, and no error/silent failure.
- All data synthetic-only; assert the `"data_source": "synthetic"` discipline for any seeded fixtures.
- Acceptance Criteria: the three scenarios pass against the sandbox endpoint with the flag on.

## 🔌 Wiring Checklist

### Web
- [x] **API endpoint** → tests drive the sandbox chat streaming endpoint (assembled in T-058)

### Shared (All Platforms)
- [ ] Database model → uses existing tables + synthetic fixtures

## ✅ Verification

**Command**:
```bash
docker compose exec -T backend python -m pytest tests/integration/test_agentic_pipeline.py --no-cov -q
```
**Success Criteria**: pytest reports all tests `passed` — (a) plan + ordered per-step events + chained grounded answer; (b) one retry then honest abstain with diagnostics and zero fabricated rows; (c) graceful `budget` event + partial answer.

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
