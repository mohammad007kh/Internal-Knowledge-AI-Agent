# T-090-gate-run-and-calibration

**Status**: Pending
**Created**: 2026-06-04 | **Completed**: N/A

## Implementation Context

- **Platform**: web · **Task Target**: backend
- **Subagents Enabled**: yes · **Relevant Subagents**: ml-engineer, ai-engineer

## Requirement Mapping

| Requirement | Description | Priority |
|-------------|-------------|----------|
| FR-023 | Evaluation runs score answers pass/fail, honesty on separate axis, cost recorded, comparable across versions | P6 |
| FR-026 | Flag widened to all users only after evaluation gates (SC-002, SC-004, SC-005) pass | P6 |

**User Story**: US-6: Operators can measure quality and bound cost

## 📋 Embedded Context (READ THIS FIRST)

### Project Standards (from registry)
| Key | Value |
|-----|-------|
| `architecture.pattern` / `layers` | modular_monolith / clean |
| `testing.unit_framework` | pytest |
| `backend.language` | python (3.12) |

### Feature Summary
The agentic pipeline (plan-and-execute with per-step verification, behind
`PIPELINE_AGENTIC_ENABLED`) must prove itself against the frozen eval set
before the flag widens beyond the admin sandbox. This task runs the full
gate evaluation and calibrates the cost ceiling from measured data.

### Gate contract (verbatim from quickstart §7 / plan Slice F)
- `evals.compare` exits 0 iff ALL gates pass: honesty ≥90% explained-decline
  on the agentic run (SC-002); agentic pass-rate ≥ baseline pass-rate on the
  single-source subset (SC-005). `evals.run` exiting 0 certifies bounded
  termination for every case (SC-004).
- Cost calibration (research R9 v1.1): replace the seed ceiling
  (30k in / 4k out) with **p95 of measured per-turn cost** from the agentic
  eval run; update `AGENT_TOKEN_CEILING_INPUT/_OUTPUT` defaults in
  `backend/src/core/config.py` + `.env.example` with a comment citing the
  measured p95 and the run id.

## Task Objective

Run the full agentic eval (all cases), verify all three gates pass, and
calibrate the token ceiling to measured p95.

## Technical Implementation Detail

### Files to Modify
- `backend/src/core/config.py` — ceiling defaults updated to measured p95 (+ provenance comment)
- `backend/.env.example` — same values + comment
- `backend/evals/BASELINE.md` — append the agentic gate-run summary table (run id, per-gate result, p95 cost)

### Dependencies
- [T-045-eval-baseline-run](./T-045-eval-baseline-run.md) — baseline numbers to compare against
- [T-059-integration-us2-us3](./T-059-integration-us2-us3.md) — agentic pipeline functional end-to-end

### Implementation Steps
1. `docker compose exec -T backend python -m evals.run --pipeline agentic` (all cases, incl. multi).
2. `docker compose exec -T backend python -m evals.compare <baseline-run> <agentic-run>` — must exit 0.
3. Compute p95 per-turn input/output tokens from the agentic run JSON sidecar.
4. Update config defaults + .env.example + BASELINE.md.
5. If any gate FAILS: do NOT calibrate; file the failing cases as findings and stop (the flag stays sandbox-only).

### Acceptance Criteria
- [ ] Agentic run exits 0 (SC-004: 100% bounded termination)
- [ ] compare exits 0 (SC-002 honesty ≥90%; SC-005 ≥ baseline on single-source)
- [ ] Ceiling defaults replaced by measured p95 with provenance comment
- [ ] BASELINE.md gate summary appended

## Verification Command

```bash
docker compose exec -T backend python -m evals.run --pipeline agentic && \
docker compose exec -T backend python -m evals.compare <baseline-run> <agentic-run> && echo GATES-PASS
```

Use the positional form (the explicit baseline-run path vs the agentic-run path) consistent with Step 2 — `<baseline-run>`/`<agentic-run>` are the JSON sidecar paths under `evals/runs/`. The `--latest` convenience flag is OPTIONAL and only usable if it was actually implemented in T-044's compare CLI — confirm it exists before relying on it.

**Expected Output**: `GATES-PASS` (compare exit 0 with each gate named PASS on stdout)

## Completion Checklist
- [ ] Implementation complete
- [ ] Acceptance criteria met
- [ ] Verification passes
- [ ] Updated traceability.md
