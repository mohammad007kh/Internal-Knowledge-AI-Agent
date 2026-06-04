# Task: T-045 - Partitioned Baseline Run + Committed BASELINE.md

**Status**: Pending
**Created**: 2026-06-04 | **Completed**: N/A
**Platform**: web | **Task Target**: backend
**User Story**: US6 (Operators can measure quality and bound cost)
**Requirement**: FR-023, SC-005 (baseline)
**Dependencies**: [T-042](./T-042-eval-runner.md), [T-043](./T-043-eval-judge.md), [T-044](./T-044-eval-compare-and-ci.md)

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
| `code_patterns.error_handling` | exceptions |
| `database.tenancy_model` | single_tenant |
| `testing.unit_framework` | pytest |
| `conventions.files` | snake_case (Python modules) |
| `conventions.variables` | snake_case |

### Feature Summary

Feature 004 evolves the pipeline into a transparent plan-and-execute agent.
Story 6's eval harness must establish the BASELINE that the later rollout gates
(Slice F) compare the agentic pipeline against. This task EXECUTES the
partitioned baseline run against the CURRENT pipeline and commits a
human-readable `backend/evals/BASELINE.md` summary (the raw run artifacts under
`evals/runs/` stay git-ignored; only the summary is committed).

### R8 Partitioning Rules (COPIED VERBATIM — load-bearing for WHAT the baseline runs)

> The baseline run against the CURRENT pipeline scores **only the
> single-source + honesty subsets** — that is exactly SC-005's comparison
> scope. Multi-step (`source_type: multi`) cases are AUTHORED in the harness
> slice but first EXECUTED against the agentic pipeline (they measure SC-001
> capability, not regression). The judge prompt must accept the current
> pipeline's *implicit* declines ("I don't see anything about that…") as a
> valid decline for BASELINE honesty scoring; the agentic pipeline is held to
> the stricter *explained*-decline standard (SC-002).

**Concrete consequence for THIS task**: run `--pipeline current`, which skips
`source_type == "multi"`; honesty cases are scored with IMPLICIT-decline
acceptance (the baseline judge bar).

### Exit-code / threshold contract (quickstart §7 — COPIED VERBATIM)

> - `evals.run` exits 0 when every case executed and terminated within limits
>   (SC-004 check is built into the runner); non-zero on any unbounded/crashed
>   case. Results JSON + markdown report written to `evals/runs/`.
> - `evals.compare` exits 0 when ALL gates pass: honesty ≥ 90%
>   explained-decline on the agentic run (SC-002), agentic pass-rate ≥
>   baseline pass-rate on the single-source subset (SC-005); exits 1 with the
>   failing gate named in stdout otherwise. CI consumes the exit code.

### Quickstart §7 — baseline invocation (COPIED VERBATIM)

> ```bash
> cd backend
> python -m evals.run --pipeline current     # baseline — scores ONLY the
>                                            # single-source + honesty subsets
>                                            # (multi cases are skipped; they
>                                            # measure capability, not regression)
> ```

### Gate Criteria

- [ ] Baseline executed against the CURRENT pipeline only (`--pipeline current`).
- [ ] All executed cases TERMINATED within limits (runner exited 0, SC-004).
- [ ] Honesty axis scored with IMPLICIT-decline acceptance (baseline bar).
- [ ] `backend/evals/BASELINE.md` committed; raw `evals/runs/` artifacts remain git-ignored.

---

## 🎯 Objective

Execute the partitioned baseline run against the CURRENT pipeline (single-source
+ honesty subsets; multi cases skipped), confirm every case terminated within
limits, and produce the first COMMITTED baseline summary at
`backend/evals/BASELINE.md` documenting the numbers that Slice F's rollout gates
compare the agentic pipeline against.

## 🛠️ Implementation Details

### Files to Create

- `backend/evals/BASELINE.md` - committed human-readable summary: run date, pipeline = current, case counts (single-source + honesty subsets, multi skipped), per-subset pass-rate, honesty-axis result (implicit-decline acceptance), tokens-per-case aggregate, judge model + prompt version, and the SC-005 single-source pass-rate that the agentic run must meet or beat.

### Files to Update (REQUIRED)

- None (this is an execution + documentation task). Confirm `evals/runs/*` is already git-ignored (added in T-042); if a stray run artifact is staged, exclude it.

### Code/Logic Requirements

- This task RUNS the harness built in T-042/T-043; it does NOT add new runtime code. If the run surfaces a runner/judge defect, fix it in the owning task, not here.
- Procedure:
  1. Bring up the stack with the current pipeline (flag OFF / `--pipeline current`).
  2. Run `python -m evals.run --pipeline current` from `backend/`.
  3. Confirm exit code 0 (every case terminated within limits — SC-004). A non-zero exit BLOCKS this task: investigate the named non-terminating case before proceeding.
  4. Read the generated markdown report + JSON sidecar from `evals/runs/`.
  5. Transcribe the load-bearing numbers into `backend/evals/BASELINE.md`: single-source subset pass-rate (the SC-005 comparison number), honesty-axis pass-rate under implicit acceptance, tokens-per-case aggregate, judge model + prompt version, run date.
- BASELINE.md is the COMMITTED artifact; the raw `runs/<timestamp>-current.{json,md}` stay git-ignored (only the summary is committed, per the task contract).
- Document explicitly in BASELINE.md that `multi` cases were SKIPPED at baseline (they first execute against agentic) so future readers understand the partition.

## 🔌 Wiring Checklist

### Shared (All Platforms)
- [x] **Committed artifact** → `backend/evals/BASELINE.md` present and populated.
- [ ] **Environment var** → none new.

## ✅ Verification

**Command**:
```bash
docker compose exec -T backend python -m evals.run --pipeline current
```
**Success Criteria**: the runner exits 0 (every executed case terminated within
limits — SC-004), `multi` cases are skipped, the honesty axis is scored with
implicit-decline acceptance, and a markdown report + JSON sidecar are written to
`backend/evals/runs/`. THEN `backend/evals/BASELINE.md` is updated with the
transcribed single-source pass-rate (SC-005 number), honesty pass-rate, and
tokens-per-case.

BASELINE.md presence check:
```bash
docker compose exec -T backend test -s evals/BASELINE.md && echo "BASELINE.md present"
```

Direct (no Docker) fallback:
```bash
cd backend && python -m evals.run --pipeline current
```

## 📝 Completion Log

- [ ] `python -m evals.run --pipeline current` exited 0 (all cases terminated — SC-004)
- [ ] `multi` cases skipped at baseline (R8 partition)
- [ ] Honesty axis scored with implicit-decline acceptance
- [ ] `backend/evals/BASELINE.md` written with SC-005 single-source pass-rate + honesty + tokens
- [ ] Raw `evals/runs/` artifacts remain git-ignored; only BASELINE.md committed
- [ ] BASELINE.md documents that multi cases were skipped (and why)
