# Task: T-077 - wire-us5-sandbox

**Status**: Pending
**Created**: 2026-06-04 | **Completed**: N/A
**Platform**: web | **Task Target**: frontend
**User Story**: US5 (the agent's thinking is visible, on demand)
**Requirement**: FR-016, FR-017, FR-018 (end-to-end wiring)
**Dependencies**: [T-071-status-line](./T-071-status-line.md), [T-072-summary-chip-persistence](./T-072-summary-chip-persistence.md), [T-073-activity-accordion-plan-card](./T-073-activity-accordion-plan-card.md), [T-074-budget-footer-cost-note](./T-074-budget-footer-cost-note.md), [T-075-honest-failure-ui-optionbuttons](./T-075-honest-failure-ui-optionbuttons.md)

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

Feature 004's transparency UX (Story 5) ships in the admin Test tab FIRST (the
sandbox is the staging ground, per FR-026 rollout posture), then the main chat.
This is the WIRING task: assemble StatusLine / ActivityAccordion / PlanCard /
BudgetFooter / honest-failure into both surfaces, driven by the per-turn
`activityLog` from T-070.

### KEY ARCHITECTURAL FACT (load-bearing — the crux of this task)

The new events (`plan`, `step`, `replan`, `budget`) are **INTERMEDIATE**
(additive to `activityLog`), NOT terminal. Today every non-delta event is
terminal, and the **optimistic-bubble lifecycle in `useChat.ts`** ends the
in-flight bubble on the first terminal frame. This task MUST confirm the
intermediate-event class does NOT trip that terminal-frame logic — the
optimistic assistant bubble must SURVIVE `plan`/`step`/`replan`/`budget` frames
and only finalize on `done`/`error`.

### Adopted §3D.1 Design Spec (COPIED from plan.md "Additional UI Requirements")

- Staging: **all of the transparency UX ships in the admin Test tab first
  (FR-026).** Then the main chat.
- Layer 1 status line replaces pulsing dots; Layer 2 collapsed-by-default inline
  accordion; post-answer summary chip; budget-hit footer inside the bubble;
  honest-failure turn styling.

### Sandbox is PRIMARY

`useSandboxStream.ts` is the PRIMARY consumer and ships first; `use-chat-stream.ts`
+ `useChat.ts` follow. Both were unified onto the shared event module in T-070.

### Gate Criteria

- [ ] TestTab renders StatusLine / ActivityAccordion / PlanCard / BudgetFooter from `useSandboxStream`'s `activityLog` (sandbox FIRST).
- [ ] Main chat (`MessageThread` + `useChat`) renders the same components from the chat `activityLog`.
- [ ] The intermediate-event class does NOT trip terminal-frame logic — the optimistic bubble survives `plan`/`step`/`replan`/`budget` and finalizes only on `done`/`error`.
- [ ] Files are UPDATED, not created (TestTab.tsx, MessageThread.tsx, useChat.ts).

---

## 🎯 Objective

Wire the full transparency UX end-to-end: the admin Test tab FIRST (sandbox
staging), then the main chat — and confirm the intermediate-event class keeps
the optimistic bubble alive (no terminal-frame trip).

## 🛠️ Implementation Details

### Files to Create

- `frontend/src/app/(admin)/admin/sources/[id]/_components/__tests__/TestTab.test.tsx` - vitest integration: feed a SCRIPTED SSE frame sequence (`plan` → `step` started → `step` finished → `done` with `activity_summary`) into the TestTab path and assert StatusLine progresses, the accordion/plan-card render, and the summary chip appears on `done`. Add a sequence with `replan` + revised `plan` (PlanCard superseded handling) and one with `budget` (BudgetFooter). CRITICAL assertion: the in-flight bubble survives the intermediate frames (it is NOT finalized until `done`).

### Files to Update (REQUIRED)

- `frontend/src/app/(admin)/admin/sources/[id]/_components/TestTab.tsx` - render `StatusLine` (in-flight), `ActivityAccordion` + `PlanCard`, `BudgetFooter`, honest-failure block, and the summary chip from `useSandboxStream`'s exposed `activityLog` + `done.activity_summary`. **(SANDBOX FIRST.)**
- `frontend/src/components/chat/MessageThread.tsx` - same assembly for the main chat assistant turn (most component integration was stubbed in T-071..T-075; here finalize the activityLog plumbing into each).
- `frontend/src/components/chat/useChat.ts` - confirm/adjust the optimistic-bubble lifecycle so the intermediate events (`plan`/`step`/`replan`/`budget`) update `activityLog` WITHOUT finalizing the optimistic bubble; only `done`/`error` finalize. Carry `done.activity_summary` onto the finalized message for the summary chip.

### Code/Logic Requirements

- Sandbox path (`TestTab` + `useSandboxStream`) is wired and verified FIRST; then the main chat.
- The optimistic-bubble lifecycle in `useChat.ts`: today it likely finalizes on any non-delta frame. Adjust so it distinguishes the intermediate-event class (from the T-070 shared module's signal) from terminal frames. The optimistic assistant bubble must remain in its "in-flight" state across all `plan`/`step`/`replan`/`budget` frames and finalize only on `done`/`error`. Do NOT regress the existing terminal behavior for legacy events.
- Pass `activityLog` (live) into StatusLine (`isStreaming` derived from delta arrival), ActivityAccordion (`mode="live"`), PlanCard (visibility per FR-008), BudgetFooter (on budget entry), HonestFailureBlock (on abstain). On finalize, attach `done.activity_summary` so T-072's chip + review-mode accordion work.
- Reuse the SHARED components; do not fork sandbox vs chat variants.
- Immutability throughout (no in-place mutation of message/log state).

## 🔌 Wiring Checklist

### Web (React/Next.js)
- [x] **Component** → TestTab assembles the transparency UX from `useSandboxStream` (FIRST)
- [x] **Component** → MessageThread assembles the same from the chat `activityLog`
- [x] **API endpoint** → consumes existing chat + sandbox SSE; no new endpoint

### Integration Verification (wiring checked)

The TestTab integration test scripts SSE frames and asserts (a) StatusLine
progresses, (b) accordion/plan-card/budget render, (c) summary chip on `done`,
and (d) the optimistic bubble survives the intermediate frames.

## ✅ Verification

**Command**:
```bash
cd frontend && pnpm exec vitest run "src/app/(admin)/admin/sources/[id]/_components/__tests__/TestTab.test.tsx"
cd frontend && pnpm exec tsc --noEmit
```
**Success Criteria**: vitest integration passes with scripted SSE frames —
StatusLine/accordion/plan-card/budget render, summary chip on `done`, and the
optimistic bubble is NOT finalized by intermediate frames; `tsc --noEmit` clean.

## 📝 Completion Log

- [ ] TestTab wired (sandbox FIRST) — full transparency UX renders from `useSandboxStream`
- [ ] Main chat wired (`MessageThread` + `useChat`)
- [ ] Optimistic bubble survives intermediate frames; finalizes only on `done`/`error` (verified)
- [ ] `done.activity_summary` carried onto the finalized message
- [ ] Vitest integration passes (scripted SSE frames)
- [ ] `tsc --noEmit` clean + Biome check clean
