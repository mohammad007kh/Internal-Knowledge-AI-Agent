# Task: T-072 - summary-chip-persistence

**Status**: Pending
**Created**: 2026-06-04 | **Completed**: N/A
**Platform**: web | **Task Target**: frontend
**User Story**: US5 (the agent's thinking is visible, on demand)
**Requirement**: FR-018
**Dependencies**: [T-070-shared-sse-activity-state](./T-070-shared-sse-activity-state.md)

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
| `frontend.framework` | nextjs (App Router) |
| `frontend.ui_library` | shadcn/ui (+ Radix) |
| `frontend.styling` | tailwind (v4) |
| `frontend.state_management` | React Context + TanStack Query v5 |
| `frontend.icons` | lucide-react |
| `frontend.toast` | sonner |
| `conventions.components` | PascalCase (`.tsx`) |
| `testing.unit_framework` | vitest + @testing-library/react |
| `tooling.lint_format` | Biome (NEVER eslint) |
| `tooling.types` | tsc (`pnpm exec tsc --noEmit`) |

### Feature Summary

Feature 004 turns the Q&A system into a transparent plan-and-execute agent.
Story 5's third beat (FR-018): after the answer lands, the live activity folds
into a compact one-line summary chip on the message; it re-expands the activity
accordion on demand and SURVIVES conversation reloads. Full step payloads do
NOT persist — only the compact summary.

### Adopted §3D.1 Design Spec (COPIED from plan.md "Additional UI Requirements")

- Post-answer: **summary chip in the message meta row**
  (`✓ Used 4 steps · 2 sources · view activity`; **amber variant on
  retry/failure**); clicking re-expands the accordion **in review mode**;
  **compact persistence only.**

### Chip anatomy (this task — load-bearing detail)

- Neutral variant: `✓ Used {step_count} steps · {source_count} sources · view activity`.
- Amber variant: `⚠ Used {step_count} steps · {source_count} sources · 1 retry`
  — rendered when `had_replan === true` OR `had_failure === true`.
- Lives in the message **meta row** (alongside the existing citations/feedback
  affordances), not inside the bubble body.
- Click → re-opens the `ActivityAccordion` (T-073) in **review mode** (post-hoc;
  reads the compact summary, not a live stream).

### Two data sources (BOTH must render the chip identically)

1. **Live** (same turn it just answered): reads `done.activity_summary` carried
   on the `done` SSE event (shape below) — surfaced via the T-070 state.
2. **Persisted** (after reload): reads `activity_summary` stored on the
   `chat_messages` row (same shape) — fetched with the conversation.

**Compact-only persistence rule:** the deep per-step payloads stream-only. On
reload they are simply ABSENT — the chip + review-mode accordion render from the
compact summary; step-level slide-over payloads (T-073) are unavailable in
review mode and must degrade gracefully (UI hides what's absent).

### data-model §3 — compact `activity_summary` shape (COPIED VERBATIM)

```jsonc
{
  "step_count": 4,
  "source_count": 2,
  "had_replan": false,
  "had_failure": false,          // any retry or abstain
  "budget_hit": false,
  "turn_tokens": {"input": 9120, "output": 1480},
  "cost_label": "medium",         // small | medium | large
  "plan": [ {"id": "s1", "label": "Read names from users.csv", "status": "done"} ],
  "superseded_plan": null,        // present when had_replan
  "revision_reason": null,
  "roles": [
    {"role": "planner",  "line": "read names file, then query CRM"},
    {"role": "executor", "step": "s1", "line": "found 7 names in users.csv"},
    {"role": "verifier", "step": "s2", "line": "rows match the 7 names ✓"}
  ]
}
```

### Gate Criteria

- [ ] Chip renders the neutral and amber variants per `had_replan`/`had_failure`.
- [ ] Chip reads `done.activity_summary` live AND persisted `activity_summary` on reload — identical rendering.
- [ ] Click re-expands the accordion in review mode.
- [ ] Compact-only: deep payloads absent on reload degrade gracefully (no crash, no empty slide-over).
- [ ] Chip sits in the message meta row.

### Out of scope (handled elsewhere)

- The accordion itself + plan card → T-073. This task renders the chip and
  toggles the accordion's open/review state; it does NOT build the accordion.
- Backend persistence of `activity_summary` onto `chat_messages` → backend
  Slice C (done event extension); this task CONSUMES the field.

---

## 🎯 Objective

Build the post-answer `ActivitySummaryChip` in the message meta row, rendering
identically from live `done.activity_summary` and from persisted
`activity_summary` on reload, with neutral/amber variants and a click that
re-opens the activity accordion in review mode.

## 🛠️ Implementation Details

### Files to Create

- `frontend/src/components/chat/ActivitySummaryChip.tsx` - component. Named props interface (e.g. `ActivitySummaryChipProps { summary: ActivitySummary; onExpand: () => void }`). Renders neutral vs amber variant; counts/retry copy from the summary; lucide `Check` / `TriangleAlert` glyph; `view activity` affordance fires `onExpand`.
- `frontend/src/lib/sse/activity-summary.ts` (or extend `agent-events.ts`) - the `ActivitySummary` TS type mirroring the data-model §3 shape, plus a small selector that produces a summary from the live `activityLog` when `done` lacks it (defensive) — but primary path is reading `done.activity_summary`.
- `frontend/src/components/chat/__tests__/ActivitySummaryChip.test.tsx` - vitest: (a) neutral variant copy; (b) amber variant when `had_replan`/`had_failure`; (c) renders from a persisted-shape object (reload path) identically; (d) `onExpand` fires on click; (e) compact-only — a summary WITHOUT deep payloads renders fine (no crash).

### Files to Update (REQUIRED)

- `frontend/src/components/chat/MessageThread.tsx` - render `<ActivitySummaryChip>` in the assistant message meta row when `message.activity_summary` is present (persisted) OR when the just-finished turn carries `done.activity_summary` (live); wire `onExpand` to the accordion open state (the accordion is added in T-073; here expose/hold the open-in-review-mode state).

### Code/Logic Requirements

- `ActivitySummary` type mirrors data-model §3 exactly. Treat `plan`/`roles`/`superseded_plan` as optional-on-reload-safe (present, but the chip only needs counts + `had_replan`/`had_failure`).
- Variant logic: amber iff `had_replan || had_failure`; otherwise neutral. Retry count copy: derive a simple `· 1 retry` style suffix from `had_failure`/`had_replan` (the summary doesn't carry an explicit retry integer in v1 — render the qualitative `1 retry` when failure/replan occurred; do not fabricate a count).
- Live vs persisted: a SINGLE render path takes an `ActivitySummary`; the parent chooses the source (live `done.activity_summary` vs `message.activity_summary`). Do not branch rendering on source.
- Compact-only graceful degradation: if step-level deep payloads are absent (reload), the chip still renders; `onExpand` opens the accordion in review mode which renders from the compact summary only.
- Immutability; small component; named props interface.

## 🔌 Wiring Checklist

### Web (React/Next.js)
- [x] **Component** → rendered by `MessageThread.tsx` in the assistant meta row
- [x] **API endpoint** → consumes `activity_summary` from the conversation fetch (persisted) + `done` SSE (live); no new endpoint

## ✅ Verification

**Command**:
```bash
cd frontend && pnpm exec vitest run src/components/chat/__tests__/ActivitySummaryChip.test.tsx
cd frontend && pnpm exec tsc --noEmit
```
**Success Criteria**: vitest passes for neutral + amber variants, live-shape and
persisted-shape rendering parity, `onExpand` firing, and compact-only
no-deep-payload rendering; `tsc --noEmit` clean.

## 📝 Completion Log

- [ ] `ActivitySummaryChip` implemented (neutral + amber variants, meta-row placement)
- [ ] `ActivitySummary` type mirrors data-model §3
- [ ] Live (`done.activity_summary`) and persisted (`message.activity_summary`) render identically
- [ ] Click re-expands accordion in review mode (state wired)
- [ ] Compact-only graceful degradation verified
- [ ] `tsc --noEmit` clean + Biome check clean
