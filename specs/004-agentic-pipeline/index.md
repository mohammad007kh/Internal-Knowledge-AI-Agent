# Feature Dashboard: Transparent Multi-Step Agent (Agentic Pipeline)

**Branch**: `004-agentic-pipeline`
**Spec**: [Link to spec.md](./spec.md)
**Plan**: [Link to plan.md](./plan.md)
**Matrix**: [Link to traceability.md](./traceability.md)
**Design refs**: [research.md](./research.md) · [data-model.md](./data-model.md) · [contracts/intent-api.yaml](./contracts/intent-api.yaml) · [contracts/sse-events.md](./contracts/sse-events.md) · [quickstart.md](./quickstart.md)

## 📊 Status Overview

| Metric      | Value |
| ----------- | ----- |
| Total Tasks | 41    |
| Completed   | 19    |
| Verified    | 19    |
| Coverage    | 100% (26/26 FRs mapped; FR-025 is a scope constraint — see traceability) |

**Current Phase**: Implementation (pending `/atomicspec.implement`)

## 🚦 Execution Order (slices — respect dependencies)

1. **Foundation** T-001, T-010, T-011, T-012
2. **Slice A — Source Intent (US1, P1)** T-020 → T-025, wire T-037
3. **Slice B — Eval harness (US6a)** T-040 → T-045 (baseline BEFORE the graph)
4. **Slice C — Agentic graph (US2+US3)** T-050 → T-059 (strictly ordered C0→C8 + integration)
5. **Slice D — Transparency UX (US5)** T-070 → T-075, wire T-077 (sandbox FIRST)
6. **Slice E — Clarify-with-options (US4)** T-080, T-081, wire T-082
7. **Slice F — Gates & rollout (US6b)** T-090 → T-093 (T-091 contains HUMAN-GATE items)

## 🧩 Atomic Task List

| ID | Story | Description | Status | Verification |
| --- | --- | --- | --- | --- |
| [T-001](./tasks/T-001-config-flags-and-caps.md) | US6 | Config flags + hard-cap settings | ✅ Done | `pytest tests/unit/core` |
| [T-010](./tasks/T-010-migration-source-intent.md) | US1 | Migration 0036 — source intent columns | ✅ Done | `alembic upgrade head` |
| [T-011](./tasks/T-011-migration-message-activity.md) | US5 | Migration 0037 — activity_summary JSONB | ✅ Done | `alembic upgrade head` |
| [T-012](./tasks/T-012-stage-slots-planner-grader.md) | US2/3 | planner + retrieval_grader LLM slots | ✅ Done | `pytest startup_seed tests` |
| [T-020](./tasks/T-020-intent-model-and-repo.md) | US1 | Intent model columns + repo (TOCTOU guard) | ✅ Done | `pytest repo tests` |
| [T-021](./tasks/T-021-intent-sanitization.md) | US1 | Intent sanitizer (strict/lenient modes) | ✅ Done | `pytest sanitizer tests` |
| [T-022](./tasks/T-022-intent-proposal-task.md) | US1 | Celery intent-proposal task | ✅ Done | `pytest task tests` |
| [T-023](./tasks/T-023-intent-api-endpoints.md) | US1 | Intent GET/PUT/propose API (require_admin) | ✅ Done | `pytest api tests` |
| [T-024](./tasks/T-024-intent-prompt-wiring.md) | US1 | Intent → 3 prompt consumers + capability ramp | ✅ Done | `pytest render tests` |
| [T-025](./tasks/T-025-intent-review-ui.md) | US1 | Admin intent review UI | ✅ Done | `vitest + tsc` |
| [T-037](./tasks/T-037-wire-us1-intent.md) | US1 | WIRE US1: router + api client + hooks | ✅ Done | `pytest integration` |
| [T-040](./tasks/T-040-eval-case-schema-and-cases.md) | US6 | Eval case schema + frozen set (synthetic) | ✅ Done | `pytest case validation` |
| [T-041](./tasks/T-041-eval-fixtures-loader.md) | US6 | Ephemeral DB fixtures loader | ✅ Done | `pytest fixtures` |
| [T-042](./tasks/T-042-eval-runner.md) | US6 | Headless eval runner (partitioned, exit codes) | ✅ Done | `pytest runner` |
| [T-043](./tasks/T-043-eval-judge.md) | US6 | LLM judge (binary, dual decline standard) | ✅ Done | `pytest judge` |
| [T-044](./tasks/T-044-eval-compare-and-ci.md) | US6 | Gate compare + nightly CI job | ✅ Done | `pytest compare` |
| [T-045](./tasks/T-045-eval-baseline-run.md) | US6 | Partitioned baseline run + BASELINE.md | ✅ Done | `evals.run --pipeline current` |
| [T-050](./tasks/T-050-token-accumulation.md) | US2/3 | C0: token usage → additive state reducers | ✅ Done | 12 unit tests; all 142 agent tests pass; ruff clean |
| [T-051](./tasks/T-051-agent-state-plan-types.md) | US2 | C1: PlanStep/StepResult/state schema | ✅ Done | 18 unit tests; mypy + ruff clean; 160 agent tests pass |
| [T-052](./tasks/T-052-planner-node.md) | US2 | C2: planner node + plan event + perm assert | 🔴 Todo | `pytest planner` |
| [T-053](./tasks/T-053-executor-node.md) | US2 | C3: executor (R1b binding, step events) | 🔴 Todo | `pytest executor` |
| [T-054](./tasks/T-054-verify-node-light.md) | US3 | C4: verify node + R4b state machine | 🔴 Todo | `pytest verify` |
| [T-055](./tasks/T-055-verify-heavy-sql.md) | US3 | C5: heavy SQL verification | 🔴 Todo | `pytest heavy-verify` |
| [T-056](./tasks/T-056-replan-node.md) | US2 | C6: replan node + events | 🔴 Todo | `pytest replan` |
| [T-057](./tasks/T-057-budget-guard-diagnostics.md) | US3/6 | C7: budget guard + diagnostics + honest-failure | 🔴 Todo | `pytest guard` |
| [T-058](./tasks/T-058-agentic-graph-assembly.md) | US2/3 | C8: graph assembly + flag + done extension | 🔴 Todo | `pytest graph` |
| [T-059](./tasks/T-059-integration-us2-us3.md) | US2/3 | Integration: chained/honesty/budget e2e | 🔴 Todo | `pytest integration` |
| [T-070](./tasks/T-070-shared-sse-activity-state.md) | US5 | Shared SSE module + activityLog state | 🔴 Todo | `vitest + tsc` |
| [T-071](./tasks/T-071-status-line.md) | US5 | Status line (Layer 1) | 🔴 Todo | `vitest + tsc` |
| [T-072](./tasks/T-072-summary-chip-persistence.md) | US5 | Summary chip + compact persistence | 🔴 Todo | `vitest + tsc` |
| [T-073](./tasks/T-073-activity-accordion-plan-card.md) | US5 | Activity accordion + plan card (Layer 2) | 🔴 Todo | `vitest + tsc` |
| [T-074](./tasks/T-074-budget-footer-cost-note.md) | US5/6 | Budget footer + quiet cost note | 🔴 Todo | `vitest + tsc` |
| [T-075](./tasks/T-075-honest-failure-ui-optionbuttons.md) | US3/5 | Abstain turn UI + OptionButtonGroup | 🔴 Todo | `vitest + tsc` |
| [T-077](./tasks/T-077-wire-us5-sandbox.md) | US5 | WIRE US5: sandbox first, then main chat | 🔴 Todo | `vitest integration` |
| [T-080](./tasks/T-080-clarify-options-backend.md) | US4 | Clarify options event (backend, terminal) | 🔴 Todo | `pytest clarify` |
| [T-081](./tasks/T-081-clarify-options-ui.md) | US4 | ClarificationCard options UI | 🔴 Todo | `vitest + tsc` |
| [T-082](./tasks/T-082-wire-us4.md) | US4 | WIRE US4: ambiguous→options→proceed e2e | 🔴 Todo | `pytest + vitest` |
| [T-090](./tasks/T-090-gate-run-and-calibration.md) | US6 | Gate run + p95 ceiling calibration | 🔴 Todo | `evals compare GATES-PASS` |
| [T-091](./tasks/T-091-rollout-checklist.md) | US6 | ⚠️ HUMAN-GATE: deadline + flag widening | 🔴 Todo | config assert + ROLLOUT.md |
| [T-092](./tasks/T-092-constitution-amendment.md) | US6 | Constitution Art. IV amendment | 🔴 Todo | grep checks |
| [T-093](./tasks/T-093-final-e2e-quickstart.md) | All | Final e2e + ACCEPTANCE.md (8 SCs) | 🔴 Todo | `playwright + ACCEPTANCE.md` |

## 📚 Knowledge Resources

> **[Open the Station Map](../../.specify/knowledge/stations/00-station-map.md)** to find the right rulebook (API, Data, Auth, etc).
> All load-bearing design decisions are EMBEDDED in each task file (Context Pinning) — task files are self-contained.

<!--
  INSTRUCTIONS FOR AI AGENT (CONTEXT PINNING):
  1. This file is your HOME during `/atomicspec.implement`.
  2. Pick the next "Todo" task IN EXECUTION ORDER (slices above).
  3. READ ONLY that task file (e.g., tasks/T-001-config-flags-and-caps.md).
  4. Execute the work.
  5. Verify using the command.
  6. Return here and mark as ✅ Done; update traceability.md.
-->
