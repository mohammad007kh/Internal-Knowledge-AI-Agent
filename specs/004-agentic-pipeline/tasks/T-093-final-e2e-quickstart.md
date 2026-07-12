# T-093-final-e2e-quickstart

**Status**: Pending
**Created**: 2026-06-04 | **Completed**: N/A

## Implementation Context

- **Platform**: web · **Task Target**: shared (backend + frontend e2e)
- **Subagents Enabled**: yes · **Relevant Subagents**: code-reviewer (post-run), e2e

## Requirement Mapping

| Requirement | Description | Priority |
|-------------|-------------|----------|
| SC-001..SC-008 | All eight measurable success criteria verified end-to-end | P6 |

**User Story**: All (US-1..US-6 acceptance closure)

## 📋 Embedded Context (READ THIS FIRST)

### Feature Summary
Final acceptance: execute the quickstart walkthrough
(`specs/004-agentic-pipeline/quickstart.md`) end-to-end against the running
stack with `PIPELINE_AGENTIC_ENABLED=true` in the sandbox, plus an automated
Playwright sweep of the new UI surfaces.

### The eight checks (from spec Success Criteria)
SC-001 chained file→DB answer correct · SC-002 honesty ≥90% (from T-090
gate) · SC-003 first progress ≤2s + always-visible status · SC-004 100%
bounded termination (from gate run) · SC-005 ≥ baseline single-source (from
gate) · SC-006 intent authoring <5 min (timed walkthrough) · SC-007 clarify
<10% of eval Qs + 100% of deliberately-ambiguous cases · SC-008 activity
inspectable incl. after reload.

## Task Objective

Run the full quickstart walkthrough + a Playwright e2e covering the new
chat surfaces, and record per-SC results.

## Technical Implementation Detail

### Files to Create
- `frontend/e2e/agentic-pipeline.spec.ts` — Playwright: sandbox multi-step
  flow (status line visible ≤2s, plan card on ≥2-step plan, accordion
  expands live, summary chip after answer + after reload), clarify-options
  flow, budget-footer flow, abstain flow.
- `specs/004-agentic-pipeline/ACCEPTANCE.md` — per-SC results table with
  evidence pointers (run ids, screenshots, timings).

### Dependencies
- [T-090-gate-run-and-calibration](./T-090-gate-run-and-calibration.md) — supplies SC-002/004/005 evidence
- [T-077-wire-us5-sandbox](./T-077-wire-us5-sandbox.md), [T-082-wire-us4](./T-082-wire-us4.md), [T-037-wire-us1-intent](./T-037-wire-us1-intent.md) — all wiring complete

### Implementation Steps
1. Bring the stack up with the flag on (quickstart §1).
2. Walk quickstart §§2-6 manually; time the SC-006 intent authoring; record.
3. Run the Playwright spec against the sandbox.
4. Pull SC-002/004/005/007 numbers from the T-090 eval artifacts.
5. Write ACCEPTANCE.md; any SC failing → file findings, feature is NOT done.

### Acceptance Criteria
- [ ] All 8 SCs evidenced in ACCEPTANCE.md (pass), or failures filed as blockers
- [ ] Playwright spec green against the sandbox
- [ ] Reload-persistence (SC-008) explicitly exercised

## Verification Command

```bash
cd frontend && pnpm exec playwright test e2e/agentic-pipeline.spec.ts --project=chromium && test -f "../specs/004-agentic-pipeline/ACCEPTANCE.md" && echo ACCEPTANCE-RECORDED
```

**Expected Output**: Playwright `passed`; then `ACCEPTANCE-RECORDED`

## Completion Checklist
- [ ] Implementation complete
- [ ] Acceptance criteria met
- [ ] Verification passes
- [ ] Updated traceability.md
