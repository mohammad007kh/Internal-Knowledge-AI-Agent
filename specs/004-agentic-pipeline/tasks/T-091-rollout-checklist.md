# T-091-rollout-checklist

**Status**: Pending
**Created**: 2026-06-04 | **Completed**: N/A

## Implementation Context

- **Platform**: web · **Task Target**: backend (config/process)
- **Subagents Enabled**: yes · **Type**: ⚠️ HUMAN-GATE task — operator decisions, not pure code

## Requirement Mapping

| Requirement | Description | Priority |
|-------------|-------------|----------|
| FR-026 | Agentic pipeline ships behind an operator-controlled switch; widened only after gates pass | P6 |
| FR-019 | Every question runs under hard limits incl. wall-clock deadline | P6 |

**User Story**: US-6: Operators can measure quality and bound cost

## 📋 Embedded Context (READ THIS FIRST)

### Feature Summary
Final rollout gate. Two decisions are explicitly HUMAN-GATE (plan Slice F):
the wall-clock deadline value and the flag-widening call. Neither may be
auto-decided.

### Rules (from plan Slice F + research R2)
- `AGENT_TURN_DEADLINE_SECS` is currently nullable/disabled. It MUST be set
  to a concrete value before any flag widening — the operator picks it from
  observed eval-run turn durations (e.g. p99 + safety margin), recorded with
  provenance.
- Optional DoS hardening (security rule 6, recommendation): consider
  `AGENT_MAX_CONCURRENT_TURNS_PER_USER` (default 2, Redis semaphore) —
  document the decision either way.
- Flag widening: `PIPELINE_AGENTIC_ENABLED` moves from sandbox-only to
  general chat ONLY after T-090 gates pass; v2 graph remains the rollback
  path ("a 30-second backend restart away").

## Task Objective

Complete the operator rollout checklist: set the deadline, decide the
concurrency cap, widen (or hold) the flag — each with documented rationale.

## Technical Implementation Detail

### Files to Modify
- `backend/src/core/config.py` + `backend/.env.example` — concrete `AGENT_TURN_DEADLINE_SECS` (+ optional concurrency cap if adopted)
- `specs/004-agentic-pipeline/ROLLOUT.md` (new) — the completed checklist: deadline value + how it was derived; concurrency-cap decision; widening decision + date; rollback procedure (flag off → v2)

### Dependencies
- [T-090-gate-run-and-calibration](./T-090-gate-run-and-calibration.md) — gates must be green first

### Implementation Steps
1. Derive deadline candidate from eval-run duration data (T-090 artifacts).
2. Operator confirms deadline + concurrency-cap decision (HUMAN-GATE — record who/when).
3. Set config values; restart backend; smoke the sandbox.
4. Operator makes the widening decision (HUMAN-GATE); if GO, flip the flag for general chat; record in ROLLOUT.md.

### Acceptance Criteria
- [ ] `AGENT_TURN_DEADLINE_SECS` concrete, with provenance, before widening
- [ ] Concurrency-cap decision documented (adopted or explicitly declined)
- [ ] ROLLOUT.md complete incl. rollback procedure
- [ ] Widening decision recorded (GO with date, or HOLD with reason)

## Verification Command

```bash
docker compose exec -T backend python -c "from src.core.config import settings; assert settings.AGENT_TURN_DEADLINE_SECS, 'deadline not set'; print('deadline:', settings.AGENT_TURN_DEADLINE_SECS)" && test -f "specs/004-agentic-pipeline/ROLLOUT.md" && echo ROLLOUT-DOCUMENTED
```

**Expected Output**: `deadline: <int>` then `ROLLOUT-DOCUMENTED`

## Completion Checklist
- [ ] Implementation complete
- [ ] Acceptance criteria met (incl. both HUMAN-GATE sign-offs)
- [ ] Verification passes
- [ ] Updated traceability.md
