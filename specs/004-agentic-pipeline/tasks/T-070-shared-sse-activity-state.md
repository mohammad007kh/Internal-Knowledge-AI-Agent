# Task: T-070 - shared-sse-activity-state

**Status**: Pending
**Created**: 2026-06-04 | **Completed**: N/A
**Platform**: web | **Task Target**: frontend
**User Story**: US5 (the agent's thinking is visible, on demand)
**Requirement**: FR-016, FR-017 (foundation)
**Dependencies**: none (backend `plan`/`step`/`replan`/`budget` events are being built in parallel under Slice C — the frontend builds against the wire CONTRACT below, not the running backend)

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
| `frontend.form_library` | react-hook-form + zod |
| `frontend.icons` | lucide-react |
| `frontend.toast` | sonner |
| `conventions.components` | PascalCase (`.tsx`) |
| `conventions.utilities` | kebab-case (`agent-events.ts`) |
| `testing.unit_framework` | vitest + @testing-library/react |
| `tooling.lint_format` | Biome (NEVER eslint) |
| `tooling.types` | tsc (`pnpm exec tsc --noEmit`) |

### Feature Summary

Feature 004 evolves the linear retrieve-then-answer pipeline into a transparent
plan-and-execute agent. Story 5 (the slice this task seeds) is the two-layer
thinking UX: a live status line plus a collapsed-by-default per-role activity
accordion, persisted compactly. This task is the FOUNDATION of that slice — the
shared SSE event model and per-turn `activityLog` state that every later UI
component (StatusLine, summary chip, ActivityAccordion, PlanCard, BudgetFooter)
reads from.

### KEY ARCHITECTURAL FACT (load-bearing — embed in design)

There are TWO SSE consumers with currently-DUPLICATED `switch` statements over
event types:
- `frontend/src/hooks/use-chat-stream.ts` (the main chat)
- `frontend/src/app/(admin)/admin/sources/[id]/_components/useSandboxStream.ts`
  (admin Test tab) — **PRIMARY; the sandbox ships first per FR-026.**

This task ENDS that duplication: extract the event-handling into ONE shared
module (`frontend/src/lib/sse/agent-events.ts`) consumed by BOTH hooks.

The new events (`plan`, `step`, `replan`, `budget`) are **INTERMEDIATE**
(additive to the per-turn `activityLog`), NOT terminal. Today every non-delta
event is terminal; this is a NEW event class the state model must support.
Unknown event types are still dropped silently (mandatory parser tolerance).

### SSE Wire Contract (COPIED VERBATIM from contracts/sse-events.md — the source of truth)

Wire format: `event: <type>\n` + `data: <json>\n\n`. Frontend parsers drop
unknown event types silently.

**Event `plan`:**
```jsonc
event: plan
data: {
  "revision": 0,                       // 0 = initial, 1 = revised
  "reason": null,                      // present when revision == 1
  "steps": [
    {
      "id": "s1",
      "label": "Read names from users.csv",   // user-facing, plain language
      "source_id": "…uuid…",
      "source_name": "users.csv",
      "depends_on": []
    }
  ]
}
```

**Event `step`:**
```jsonc
event: step
data: {
  "step_id": "s1",
  "role": "executor",                  // planner|executor|verifier|synthesizer
  "state": "started",                  // started | finished | failed | retrying
  "label": "Reading users.csv…",       // present-tense for started, past for finished
  "summary": null,                     // short partial result on finished
  "progress": {"current": 1, "total": 4}
}
```

**Event `replan`:**
```jsonc
event: replan
data: {
  "reason": "CRM returned emails; switching to email match",
  "superseded_revision": 0
}
```
Always followed by a fresh `plan` event with `revision: 1`.

**Event `budget`:**
```jsonc
event: budget
data: {
  "ceiling_hit": true,
  "not_completed": ["Verify rows match the names", "Write the full answer"],
  "offer_continue": true
}
```

**Extended `done`** gains `activity_summary` (compact shape from data-model §3 —
copied below). **Extended `clarification`** gains optional `options[]` (handled
in T-080/T-081 — this task's discriminated union should leave room for it but
need not parse it).

### data-model §3 — compact `activity_summary` shape (COPIED VERBATIM, carried on `done`)

```jsonc
{
  "step_count": 4,
  "source_count": 2,
  "had_replan": false,
  "had_failure": false,
  "budget_hit": false,
  "turn_tokens": {"input": 9120, "output": 1480},
  "cost_label": "medium",
  "plan": [ {"id": "s1", "label": "Read names from users.csv", "status": "done"} ],
  "superseded_plan": null,
  "revision_reason": null,
  "roles": [
    {"role": "planner",  "line": "read names file, then query CRM"},
    {"role": "executor", "step": "s1", "line": "found 7 names in users.csv"},
    {"role": "verifier", "step": "s2", "line": "rows match the 7 names ✓"}
  ]
}
```

### Gate Criteria

- [ ] ONE shared module owns the event switch; both hooks import it (no duplicated switch).
- [ ] `plan`/`step`/`replan`/`budget` are additive (intermediate) — they append/update `activityLog` and NEVER end the turn.
- [ ] Unknown event types are dropped silently (no throw, no log spam).
- [ ] Discriminated-union types mirror the wire contract above exactly.
- [ ] Sandbox hook wired FIRST (PRIMARY), then main chat hook.

---

## 🎯 Objective

Extract the duplicated SSE event-switch into one shared module that produces a
typed, additive per-turn `activityLog: ActivityEntry[]`. Define
discriminated-union types mirroring the wire contract, implement a pure reducer
that folds an event sequence into log state, and wire BOTH stream hooks to it
(sandbox first).

## 🛠️ Implementation Details

### Files to Create

- `frontend/src/lib/sse/agent-events.ts` - discriminated-union event types (`PlanEvent`, `StepEvent`, `ReplanEvent`, `BudgetEvent`), the `ActivityEntry` type, and a pure `activityLogReducer(state, event)` that folds intermediate events into the log; a `parseAgentEvent(type, data): AgentEvent | null` that returns `null` for unknown types (silent drop).
- `frontend/src/lib/sse/__tests__/agent-events.test.ts` - vitest: event sequences → expected `activityLog` states (initial plan → step started → step finished → replan → revised plan → budget); unknown event → no-op; intermediate events never set a terminal flag.

### Files to Update (REQUIRED)

- `frontend/src/app/(admin)/admin/sources/[id]/_components/useSandboxStream.ts` - **wire FIRST (PRIMARY)**: replace the inline event switch with `parseAgentEvent` + `activityLogReducer`; expose `activityLog` from the hook.
- `frontend/src/hooks/use-chat-stream.ts` - then wire identically: same shared module, expose `activityLog`.

### Code/Logic Requirements

- Types are a discriminated union keyed on the event name; mirror the JSON shapes above field-for-field (snake_case wire → camelCase TS is acceptable, but document the mapping; keep it mechanical).
- `ActivityEntry` models a per-step / per-role narration entry the later UI reads: at minimum `{ stepId, role, state, label, summary, progress }` plus plan/replan/budget-derived entries.
- The reducer is PURE (no side effects) and immutable — return a NEW array/object every fold (registry coding-style: NEVER mutate).
- `replan` records the superseded plan + reason; the subsequent `plan` (revision 1) becomes the active plan. Do NOT discard the superseded plan (later UI inspects it).
- `budget` records a budget entry; it is intermediate (does NOT end the turn — the turn still ends on `done`/`error`).
- Unknown event types: `parseAgentEvent` returns `null`; the caller skips. Never throw.
- IMPORTANT (cross-cutting): the new intermediate-event class must NOT be treated as a terminal frame. The optimistic-bubble lifecycle in `useChat.ts` (wired in T-077) relies on terminal frames; this module must expose a clear signal that these four events are intermediate so T-077 can keep the optimistic bubble alive.

## 🔌 Wiring Checklist

### Web (React/Next.js)
- [x] **Component** → consumed by both stream hooks (sandbox + main chat)
- [ ] **Frontend page** → N/A (state layer; UI lands in T-071..T-077)

## ✅ Verification

**Command**:
```bash
cd frontend && pnpm exec vitest run src/lib/sse/__tests__/agent-events.test.ts
cd frontend && pnpm exec tsc --noEmit
```
**Success Criteria**: vitest reports all reducer tests `passed` (scripted event
sequences → expected `activityLog`; unknown event no-op; intermediate events do
not flip a terminal flag); `tsc --noEmit` prints no errors.

## 📝 Completion Log

- [ ] Shared `agent-events.ts` module implemented (types + pure reducer + `parseAgentEvent`)
- [ ] Reducer unit tests pass (event sequences → expected states)
- [ ] Both hooks wired (sandbox FIRST, then main chat); no duplicated switch remains
- [ ] `tsc --noEmit` clean
- [ ] Biome check clean (`cd frontend && pnpm lint`)
