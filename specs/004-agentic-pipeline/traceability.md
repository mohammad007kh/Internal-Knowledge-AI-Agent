# Traceability Matrix: Transparent Multi-Step Agent (Agentic Pipeline)

**Purpose**: Maintains the link between Requirements (Spec) and Execution (Tasks).
**Coverage**: 26/26 functional requirements mapped (100%). FR-025 is a
negative-scope constraint — enforced by absence + review, see note below.

## 🗺️ Requirement Coverage

| User Story | Priority | Requirement ID | Covered By Tasks | Status |
| --- | --- | --- | --- | --- |
| US1 | P1 | FR-001 (intent authoring) | T-010, T-020, T-023, T-025, T-037 | 🔴 Pending |
| US1 | P1 | FR-002 (AI propose, live-flagged, review surface) | T-012, T-021, T-022, T-023, T-025 | 🔴 Pending |
| US1 | P1 | FR-003 (selection considers intent) | T-024, T-052 | 🔴 Pending |
| US1 | P1 | FR-004 (purpose to synthesizer, survives truncation) | T-024 | 🔴 Pending |
| US1 | P1 | FR-005 (out-of-scope tiered authority) | T-024 | 🔴 Pending |
| US2 | P2 | FR-006 (plan decomposition, planner-always) | T-051, T-052, T-053 | 🔴 Pending |
| US2 | P2 | FR-007 (caps: ≤5 steps, ≤1 revision) | T-001, T-051, T-052, T-056 | 🔴 Pending |
| US2 | P2 | FR-008 (plan visible, revision announced, card threshold) | T-052, T-056, T-073 | 🔴 Pending |
| US2 | P2 | FR-009 (per-step permission re-clipping) | T-052, T-053 | 🔴 Pending |
| US3 | P3 | FR-010 (every step verified) | T-012, T-054 | 🔴 Pending |
| US3 | P3 | FR-011 (heavy DB verification) | T-055 | 🔴 Pending |
| US3 | P3 | FR-012 (retry once with reason) | T-054 | 🔴 Pending |
| US3 | P3 | FR-013 (honest abstain + what-I-tried + quick replies) | T-057, T-075 | 🔴 Pending |
| US4 | P4 | FR-014 (clarify with 2-4 options + free text) | T-080, T-081 | 🔴 Pending |
| US4 | P4 | FR-015 (only-when-stuck; choice into history) | T-080, T-081, T-082 | 🔴 Pending |
| US5 | P5 | FR-016 (always-visible status line) | T-053, T-070, T-071 | 🔴 Pending |
| US5 | P5 | FR-017 (collapsible per-role activity panel) | T-070, T-073 | 🔴 Pending |
| US5 | P5 | FR-018 (compact persistence, survives reload) | T-011, T-058, T-072 | 🔴 Pending |
| US6 | P6 | FR-019 (hard limits bound all loops) | T-001, T-050, T-057 | 🔴 Pending |
| US6 | P6 | FR-020 (graceful wrap-up + keep-going) | T-057, T-074 | 🔴 Pending |
| US6 | P6 | FR-021 (cost recorded; quiet user note) | T-050, T-058, T-074 | 🔴 Pending |
| US6 | P6 | FR-022 (frozen eval set incl. honesty cases) | T-040, T-041 | 🔴 Pending |
| US6 | P6 | FR-023 (scored, comparable eval runs) | T-042, T-043, T-044, T-045, T-090 | 🔴 Pending |
| US6 | P6 | FR-024 (on-demand + scheduled evals) | T-042, T-044 | 🔴 Pending |
| — | — | FR-025 (OUT OF SCOPE: external tools, writes, mid-flight asks, editable plans) | Constraint — no task implements these; enforced by scope review at T-093 | 🟡 Constraint |
| US6 | P6 | FR-026 (flag-gated sandbox-first rollout) | T-001, T-058, T-077, T-090, T-091 | 🔴 Pending |

## 🎯 Success Criteria Mapping

| SC | Verified by |
| --- | --- |
| SC-001 (chained file→DB answered) | T-059, T-093 |
| SC-002 (honesty ≥90% explained-decline) | T-043, T-090 |
| SC-003 (first progress ≤2s; status always visible) | T-071, T-093 |
| SC-004 (100% bounded termination) | T-042, T-057, T-090 |
| SC-005 (agentic ≥ baseline, single-source) | T-045, T-090 |
| SC-006 (intent authoring <5 min) | T-025, T-093 |
| SC-007 (clarify <10% / 100% of ambiguous set) | T-080, T-090, T-093 |
| SC-008 (activity inspectable incl. reload) | T-072, T-073, T-093 |

## 🔁 Task → Requirement (reverse index)

| Task | Requirements |
| --- | --- |
| T-001 | FR-007, FR-019, FR-026 — ✅ Done, Verified 2026-06-04 (18 tests + ruff) |
| T-010 | FR-001 — ✅ Done, Verified 2026-06-04 (0036 up/down/up clean; columns + index confirmed via psql) |
| T-011 | FR-018 — ✅ Done, Verified 2026-06-04 (0037 up/down/up clean; CHECK rejects >16KB on real row) |
| T-012 | FR-002, FR-010 — ✅ Done, Verified 2026-06-04 (17 tests; STAGES 11→13 no regression) |
| T-020 | FR-001 — ✅ Done, Verified 2026-06-03 (14 tests: caps, TOCTOU guard structural+behavioral; ruff clean; no new mypy errors) |
| T-021 | FR-002 — ✅ Done, Verified 2026-06-03 (63 tests: patterns/caps/dual-mode; ruff + mypy clean) |
| T-022 | FR-002 — ✅ Done, Verified 2026-06-04 (7 tests: user_set short-circuit, never-writes-purpose, lenient sanitize, TOCTOU race→skipped+no-commit; best-effort study-chain enqueue) |
| T-023 | FR-001, FR-002 — ✅ Done, Verified 2026-06-04 (19 tests: require_admin×3, 422 strict-sanitize, 409 in-flight, no config leak; error_handler input-strip; order-independent celery spy) |
| T-024 | FR-003, FR-004, FR-005 — ✅ Done, Verified 2026-06-04 (26 tests: ramp tiers, delimiters, router cap, fallback; ruff + mypy isolation clean) |
| T-025 | FR-001, FR-002 |
| T-037 | FR-001..FR-005 (wiring/integration) |
| T-040 | FR-022 — ✅ Done, Verified 2026-06-04 (53 tests; 26 synthetic cases, 13 declines, 4 multi; ruff + mypy clean) |
| T-041 | FR-022 — ✅ Done, Verified 2026-06-04 (ephemeral schema seed+teardown proven via in-container harness; loader renamed fixtures→fixtures_loader to avoid pkg/dir clash; conftest port/venv portability tracked as debt) |
| T-042 | FR-023, FR-024 |
| T-043 | FR-023 — ✅ Done, Verified 2026-06-04 (19 tests, LLM mocked; dual-decline standard for both pipelines; judge model pinned to dated version) |
| T-044 | FR-023, FR-024 |
| T-045 | FR-023 |
| T-050 | FR-019, FR-021 |
| T-051 | FR-006, FR-007 |
| T-052 | FR-006, FR-007, FR-008, FR-009, FR-014 (trigger) |
| T-053 | FR-006, FR-009, FR-016 |
| T-054 | FR-010, FR-012 |
| T-055 | FR-011 |
| T-056 | FR-007, FR-008 |
| T-057 | FR-013, FR-019, FR-020 |
| T-058 | FR-018, FR-021, FR-026 |
| T-059 | FR-006..FR-013 (integration) |
| T-070 | FR-016, FR-017 |
| T-071 | FR-016 |
| T-072 | FR-018 |
| T-073 | FR-008, FR-017 |
| T-074 | FR-020, FR-021 |
| T-075 | FR-013 |
| T-077 | FR-016..FR-018 (wiring) |
| T-080 | FR-014, FR-015 |
| T-081 | FR-014, FR-015 |
| T-082 | FR-014, FR-015 (wiring) |
| T-090 | FR-023, FR-026 |
| T-091 | FR-019, FR-026 |
| T-092 | FR-026 (governance closure) |
| T-093 | SC-001..SC-008 (acceptance) |

No orphan tasks. No uncovered requirements.

## 🛡️ Gate Verification Log

| Transition | Gate | Status | Verified By |
| --- | --- | --- | --- |
| Spec → Plan | Stn 03 (Discovery) | ✅ Pass | AI Agent (spec header gate block) |
| Spec → Plan | Stn 04 (PRD) | ✅ Pass | AI Agent + 4-Q clarify session |
| Spec → Plan | Stn 05 (User Flows) | ✅ Pass | AI Agent (edge-state checklist) |
| Plan → Tasks | Stn 06 (API Contracts) | ✅ Pass | contracts/ + 2-round expert review |
| Plan → Tasks | Stn 07 (Data) | ✅ Pass | data-model.md + 2-round expert review |
| Plan → Tasks | Stn 13 (Security) | ✅ Pass | security plan-review (6 findings → rules encoded in tasks) |
| Tasks → Impl | HITL checkpoints | ✅ Pass | Owner (4/4 approved 2026-06-04) |

<!--
  INSTRUCTIONS:
  - Update "Status" to ✅ Done when all linked tasks are verified.
  - This file proves that we built what was asked.
-->
