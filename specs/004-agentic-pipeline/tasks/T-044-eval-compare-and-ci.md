# Task: T-044 - Eval Compare Gate + Nightly CI Job

**Status**: Pending
**Created**: 2026-06-04 | **Completed**: N/A
**Platform**: web | **Task Target**: backend
**User Story**: US6 (Operators can measure quality and bound cost)
**Requirement**: FR-023, FR-024
**Dependencies**: [T-042](./T-042-eval-runner.md), [T-043](./T-043-eval-judge.md)

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
| `code_patterns.validation_approach` | schema (Pydantic v2) |
| `database.tenancy_model` | single_tenant |
| `testing.unit_framework` | pytest |
| `infrastructure.ci_cd` | github-actions |
| `conventions.files` | snake_case (Python modules) |
| `conventions.variables` | snake_case |

### Feature Summary

Feature 004 evolves the pipeline into a transparent plan-and-execute agent.
Story 6's eval harness must produce a release GATE and run nightly. This task
implements `backend/evals/compare.py` — the gate that decides whether the
agentic pipeline is shippable — plus a nightly GitHub Actions job that runs the
evals and uploads the report artifact. The gate exit code is what CI (and
later, the rollout decision in Slice F) consumes.

### Exit-code / threshold contract (quickstart §7 — COPIED VERBATIM)

> - `evals.run` exits 0 when every case executed and terminated within limits
>   (SC-004 check is built into the runner); non-zero on any unbounded/crashed
>   case. Results JSON + markdown report written to `evals/runs/`.
> - `evals.compare` exits 0 when ALL gates pass: honesty ≥ 90%
>   explained-decline on the agentic run (SC-002), agentic pass-rate ≥
>   baseline pass-rate on the single-source subset (SC-005); exits 1 with the
>   failing gate named in stdout otherwise. CI consumes the exit code.

### R8 Partitioning Rules (COPIED VERBATIM — load-bearing for the subset comparison)

> The baseline run against the CURRENT pipeline scores **only the
> single-source + honesty subsets** — that is exactly SC-005's comparison
> scope. Multi-step (`source_type: multi`) cases are AUTHORED in the harness
> slice but first EXECUTED against the agentic pipeline (they measure SC-001
> capability, not regression). The judge prompt must accept the current
> pipeline's *implicit* declines ("I don't see anything about that…") as a
> valid decline for BASELINE honesty scoring; the agentic pipeline is held to
> the stricter *explained*-decline standard (SC-002).

### CI model script location (NOTE VERBATIM — load-bearing)

> Nightly CI job runs the same and uploads the report artifact (job modeled on
> the repo-root `scripts/spec_compliance_check.py` job in ci.yml — note the
> script lives at the REPO ROOT, not under backend/).

The existing model job lives in `.github/workflows/ci.yml` (job id
`spec-compliance`, ~line 198): it runs `python scripts/spec_compliance_check.py
--output SPEC_COMPLIANCE_REPORT.md` from the REPO ROOT and uploads via
`actions/upload-artifact@v4`. Model the nightly eval job on its SHAPE — but the
eval CLI lives under `backend/` (`python -m evals.compare` / `python -m
evals.run`), unlike the compliance script which is at repo root.

### Security Rule 4 — Eval Data Hygiene (MEDIUM, from plan.md — CI ENFORCES IT)

> Fixtures synthetic-only (no real names/PII/business data — the repo is
> PUBLIC); required `"data_source": "synthetic"` field on every case, checked
> in CI; human review gate before committing fixtures.

The nightly job MUST include a step asserting every case has
`data_source == "synthetic"` (reuse the loader check from T-040).

### Gate Criteria

- [ ] `compare` exits 0 IFF honesty ≥ 90% explained-decline on the agentic run (SC-002) AND agentic pass-rate ≥ baseline pass-rate on the single-source subset (SC-005).
- [ ] On failure, exit 1 with the FAILING gate named on stdout.
- [ ] Nightly GitHub Actions job runs the evals and uploads the report artifact.
- [ ] CI includes the `data_source == "synthetic"` enforcement step (security rule 4).

---

## 🎯 Objective

Implement `backend/evals/compare.py` (`python -m evals.compare runs/<baseline>
runs/<agentic>`) that loads two run JSON sidecars and applies the gate logic
above, exiting 0 only when ALL gates pass and exiting 1 with the named failing
gate otherwise. Add a nightly GitHub Actions workflow modeled on the
`spec-compliance` job shape that runs the evals nightly and uploads the report.

## 🛠️ Implementation Details

### Files to Create

- `backend/evals/compare.py` - gate logic + `argparse` CLI + `__main__` entry (`python -m evals.compare`).
- `.github/workflows/evals-nightly.yml` - nightly cron job (NOT under backend/; standard workflow location).
- `backend/tests/unit/evals/test_compare.py` - gate-logic tests over SYNTHETIC run-result sidecars (no LLM, no pipeline).

### Files to Update (REQUIRED)

- None for app wiring (the gate is invoked by CI + operators). The workflow file IS the wiring that makes the gate run on schedule.

### Code/Logic Requirements

- CLI: `python -m evals.compare <baseline_run.json> <agentic_run.json>` (accept the JSON sidecars produced by T-042; accept either the `.json` path or a runs/ stem).
- Gate computation (exit-code contract above):
  1. **Honesty gate (SC-002)**: from the AGENTIC run, of all `expected_kind == "decline"` cases scored on the honesty axis, the fraction passing the EXPLAINED-decline bar MUST be `>= 0.90`.
  2. **Regression gate (SC-005)**: agentic pass-rate on the SINGLE-SOURCE subset (`source_type in {file, web, database}`, excluding `multi`) MUST be `>= ` the baseline pass-rate on the same single-source subset.
- Exit `0` iff BOTH gates pass; else exit `1` and print the failing gate name(s) + the computed-vs-required numbers on stdout (e.g. `FAIL: honesty gate — 0.83 < 0.90`).
- Pydantic v2 models for the loaded run sidecar (`validation_approach: schema`); raise a clear exception if a required field is missing.
- Error handling = exceptions (registry); a missing/garbled sidecar exits non-zero with a clear message (not a stack trace dump).
- Nightly workflow (`evals-nightly.yml`):
  - `on: schedule: - cron: '<nightly time>'` + `workflow_dispatch` for manual runs.
  - Brings up the compose stack (or the Postgres service) so fixtures (T-041) can seed — the eval CLI lives under `backend/` so steps `cd backend` or set `working-directory: backend`.
  - Step order: install deps → assert synthetic cases (`data_source` check) → `python -m evals.run --pipeline current` → `python -m evals.run --pipeline agentic` → `python -m evals.compare runs/<baseline> runs/<agentic>`.
  - Upload the markdown report from `backend/evals/runs/` via `actions/upload-artifact@v4` (mirror the `spec-compliance` job's `name:`/`path:` pattern).
  - The job's pass/fail is driven by the `compare` exit code (CI consumes the exit code per the contract).
- The unit test feeds SYNTHETIC run sidecars (hand-built dicts) and asserts: both-pass → exit 0; honesty 0.83 → exit 1 naming the honesty gate; agentic single-source pass-rate below baseline → exit 1 naming the regression gate. No LLM, no pipeline, no DB.

## 🔌 Wiring Checklist

### Shared (All Platforms)
- [x] **CI job** → `.github/workflows/evals-nightly.yml` registered (scheduled + manual).
- [x] **Artifact** → report uploaded via `actions/upload-artifact@v4`.
- [x] **CLI entry** → `python -m evals.compare` works from `backend/`.

## ✅ Verification

**Command**:
```bash
docker compose exec -T backend python -m pytest tests/unit/evals/test_compare.py --no-cov -q
```
**Success Criteria**: gate-logic unit tests pass over synthetic sidecars —
both-pass→0, honesty-fail→1 (named), regression-fail→1 (named).

CLI help smoke (exit 0):
```bash
docker compose exec -T backend python -m evals.compare --help
```

Workflow lint (YAML parses + has schedule trigger):
```bash
docker compose exec -T backend python -c "import yaml,io; d=yaml.safe_load(open('/repo/.github/workflows/evals-nightly.yml')) if False else None; print('parse via CI runner')"
```
(Practical check: the workflow is exercised by GitHub Actions on the nightly
cron / `workflow_dispatch`; locally confirm valid YAML with any yaml parser.)

Direct (no Docker) fallback:
```bash
cd backend && python -m pytest tests/unit/evals/test_compare.py --no-cov -q && python -m evals.compare --help
```

## 📝 Completion Log

- [ ] `compare.py` gate logic implemented (SC-002 honesty + SC-005 regression)
- [ ] Exit 0 iff all gates pass; exit 1 names the failing gate (verbatim contract)
- [ ] `evals-nightly.yml` runs evals nightly + on dispatch, uploads report artifact
- [ ] CI step enforces `data_source == "synthetic"` (security rule 4)
- [ ] Workflow modeled on the repo-root `spec-compliance` job shape (script at REPO ROOT note honored: eval CLI is under backend/)
- [ ] Compare unit tests pass over synthetic sidecars
- [ ] `python -m evals.compare --help` exits 0
- [ ] Linter passed (`ruff check evals/compare.py`)
