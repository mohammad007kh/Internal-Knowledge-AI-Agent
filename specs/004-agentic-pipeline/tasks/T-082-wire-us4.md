# Task: T-082 - wire-us4

**Status**: Pending
**Created**: 2026-06-04 | **Completed**: N/A
**Platform**: web | **Task Target**: full-stack (backend integration test + frontend flow test)
**User Story**: US4 (when the question is ambiguous, ask — with choices)
**Requirement**: FR-014, FR-015 (end-to-end)
**Dependencies**: [T-080-clarify-options-backend](./T-080-clarify-options-backend.md), [T-081-clarify-options-ui](./T-081-clarify-options-ui.md)

---

## 📋 Embedded Context (READ THIS FIRST)

<!--
  SELF-CONTAINED TASK (Constitution Directive 8):
  This section contains ALL context needed to implement this task.
  Do NOT read plan.md, spec.md, stations, or subagents.
-->

### Project Standards (from registry)

| Key | Value |
|-----|-------|
| `architecture.pattern` | modular_monolith |
| `architecture.layers` | clean |
| `code_patterns.validation_approach` | schema (Pydantic v2) |
| `database.tenancy_model` | single_tenant |
| `testing.unit_framework` | pytest (backend) / vitest + testing-library (frontend) |
| `conventions.files` | snake_case (Python) / PascalCase (.tsx) |
| `tooling.lint` | ruff (be) / Biome (fe) — NEVER eslint/jest/npm |
| `tooling.types` | mypy (be) / tsc (fe) |

### Feature Summary

Feature 004's clarify-with-options (Story 4) end-to-end: an ambiguous question
triggers an options card BEFORE any step execution; the user's choice becomes a
normal user message that starts the next turn, which proceeds with the chosen
source. An unambiguous question shows NO card. This is the WIRING/integration
task tying the backend emission (T-080) and the frontend card (T-081) together.

### Architecture facts (load-bearing)

- Clarification is TERMINAL: the planner's `needs_clarification` path emits the
  extended `clarification` event BEFORE any execution and ends the turn (NO
  `interrupt()`/checkpointer/cross-turn pending state).
- History-based resume: the chosen option's LABEL posts as a normal user message
  → the NEXT turn proceeds with that choice.
- Options are generated EXCLUSIVELY from the user's permitted source set
  (security rule 2).

### Acceptance flow (FR-014/FR-015 — what the integration verifies)

1. **Ambiguous question** (two sources plausibly match) → `clarification` event
   with 2-4 options emitted BEFORE any `step` event → turn ends.
2. **User picks an option** → its label posts as a normal user message → the
   next turn proceeds with the chosen source (the right source is consulted).
3. **Unambiguous question** → NO clarification event/card; normal planning +
   execution.

### Gate Criteria

- [ ] Backend integration test: ambiguous → `clarification` (2-4 options) emitted BEFORE any `step`; choice (next turn) proceeds with the chosen source; unambiguous → no clarification.
- [ ] Frontend vitest flow test: options card appears before execution; selection echoes the label as a user message; unambiguous → no card.
- [ ] Options never name an inaccessible source (permission clipping verified).

---

## 🎯 Objective

Verify the clarify-with-options flow end-to-end: a backend integration test
covering ambiguous → options-before-execution → choice-proceeds-with-source and
unambiguous → no-card; plus a frontend vitest flow test covering the card render,
selection echo, and the no-card path.

## 🛠️ Implementation Details

### Files to Create

- `backend/tests/integration/test_clarify_flow.py` - pytest integration: (a) seed two sources with overlapping subject matter; ask an ambiguous question; assert the SSE stream emits `clarification` (2-4 options) and NO `step` event precedes/follows it (terminal, pre-execution); (b) simulate the next turn carrying the chosen option label as a user message; assert execution proceeds against the chosen source; (c) ask an unambiguous question; assert NO `clarification` event; (d) assert options are clipped to the requesting user's permitted source set (no inaccessible source named).
- `frontend/src/components/chat/__tests__/clarify-flow.test.tsx` - vitest flow test: feed a scripted SSE sequence where `clarification` (with options) arrives before any `step`; assert the options card renders before any execution UI; selecting an option echoes the LABEL as a user message; a sequence WITHOUT a clarification event renders no card.

### Files to Update (REQUIRED)

- None expected (T-080 emits, T-081 renders + parses). If the integration reveals a gap (e.g. the next-turn resume path or a parse edge), fix it in the owning file (`backend/src/services/chat_stream_service.py` or `frontend/src/components/chat/ClarificationCard.tsx` / `frontend/src/lib/sse/agent-events.ts`) and note it in the Completion Log. Do NOT duplicate logic here.

### Code/Logic Requirements

- This is an integration/wiring task: prefer asserting OBSERVABLE behavior (emitted event ordering, card presence, message echo) over re-testing units already covered by T-080/T-081.
- Backend: assert event ORDERING (`clarification` before any `step`; terminal). Assert the permitted-set clipping (security rule 2) with a user who lacks access to one of the two candidate sources.
- Frontend: assert the card renders BEFORE execution UI and that selection routes through the normal send path (label echoed as user message).
- Unambiguous path: explicitly assert the ABSENCE of a clarification event/card (FR-015 — no routine speed bump).

## 🔌 Wiring Checklist

### Shared (All Platforms)
- [x] **API endpoint** → exercises the existing chat/sandbox SSE endpoint end-to-end (no new endpoint)
- [x] **Component** → `ClarificationCard` + `OptionButtonGroup` exercised in the frontend flow test

### Integration Verification (wiring checked)

Backend integration asserts the ambiguous → options-before-execution → choice →
proceed-with-source path and the unambiguous → no-card path; frontend flow test
asserts card-before-execution + selection echo + no-card.

## ✅ Verification

**Command**:
```bash
docker compose exec -T backend python -m pytest tests/integration/test_clarify_flow.py --no-cov -q
cd frontend && pnpm exec vitest run src/components/chat/__tests__/clarify-flow.test.tsx
```
**Success Criteria**: backend integration passes (ambiguous → clarification
before any step → choice proceeds with the chosen source; unambiguous → no
clarification; options clipped to permitted set); frontend flow test passes
(card before execution, selection echo, no-card path).

Direct (no Docker) backend fallback:
```bash
cd backend && python -m pytest tests/integration/test_clarify_flow.py --no-cov -q
```

Frontend type check:
```bash
cd frontend && pnpm exec tsc --noEmit
```

## 📝 Completion Log

- [ ] Backend integration test passes (ambiguous → options-before-execution → choice → proceed; unambiguous → no card)
- [ ] Options clipped to the permitted source set (verified with a restricted user)
- [ ] Frontend flow test passes (card before execution, selection echo, no-card path)
- [ ] Any gap found wired in the owning file (noted here), not duplicated
- [ ] `ruff check` (be) + `tsc --noEmit` / Biome (fe) clean
