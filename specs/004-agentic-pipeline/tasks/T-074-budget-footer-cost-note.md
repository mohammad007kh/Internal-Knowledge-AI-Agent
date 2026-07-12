# Task: T-074 - budget-footer-cost-note

**Status**: Pending
**Created**: 2026-06-04 | **Completed**: N/A
**Platform**: web | **Task Target**: frontend
**User Story**: US6 (operators bound cost; users get graceful budget-hit)
**Requirement**: FR-020, FR-021
**Dependencies**: [T-070-shared-sse-activity-state](./T-070-shared-sse-activity-state.md), [T-073-activity-accordion-plan-card](./T-073-activity-accordion-plan-card.md)

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
| `conventions.constants` | SCREAMING_SNAKE_CASE |
| `testing.unit_framework` | vitest + @testing-library/react |
| `tooling.lint_format` | Biome (NEVER eslint) |
| `tooling.types` | tsc (`pnpm exec tsc --noEmit`) |

### Feature Summary

Feature 004 runs every question under a hard processing ceiling. When the
ceiling trips, the agent wraps up gracefully with the best partial answer and a
calm note of what it didn't get to (FR-020). Separately, processing cost is
shown to users only as an unobtrusive plain-language note inside the activity
panel — never a meter (FR-021).

### Adopted §3D.1 Design Spec (COPIED VERBATIM from plan.md "Additional UI Requirements")

- Budget-hit: **slim neutral-amber footer banner inside the answer bubble
  (persists in history) + optional "Keep going" quick-reply (new turn).**
- Cost note: **plain-language size leading ("This was a medium question"),
  token count as dimmed suffix, panel-only; NO meters/counters/$.**

### Decided copy (load-bearing — use verbatim)

- Wrap-up line: **"I reached this question's budget, so I'm wrapping up here…"**
- Not-completed line: **"I didn't get to: …"** followed by the items from the
  `budget` event's `not_completed` array (plain-language, comma/line joined).
- Quick-reply: a quiet **`Keep going`** button that simply sends the literal
  text **"Keep going"** as a NORMAL user message (new turn, fresh budget — NO
  special endpoint). It is offered only when the `budget` event has
  `offer_continue: true`.

### `budget` SSE event shape (COPIED VERBATIM from contracts/sse-events.md)

```jsonc
event: budget
data: {
  "ceiling_hit": true,
  "not_completed": ["Verify rows match the names", "Write the full answer"],
  "offer_continue": true               // UI may render the "Keep going" quick-reply
}
```

`budget` is an INTERMEDIATE event (additive to the activityLog) — it must NOT
trip terminal-frame logic. Persistence: the footer persists in history via
`activity_summary.budget_hit` (data-model §3) — render the footer on reload when
`budget_hit === true`.

### Cost-note spec (FR-021 — panel footer, NO meters/counters/$)

- Leading plain-language size: `This was a {small|medium|large} question`.
- Size derived from the budget FRACTION (turn tokens / token ceiling). Use
  NAMED CONSTANTS for the thresholds (SCREAMING_SNAKE_CASE), e.g.
  `COST_LABEL_SMALL_MAX = 0.33`, `COST_LABEL_MEDIUM_MAX = 0.66` (small < medium
  threshold ≤ medium < large threshold ≤ large). Prefer reading `cost_label`
  directly from `activity_summary` when present; the threshold helper is the
  fallback / source of the label when computing live.
- Token count rendered as a DIMMED suffix: `· ~12k tokens` (rounded, `text-muted-foreground`).
- Lives in the ACCORDION footer (panel-only). NO meters, NO progress bars, NO
  numeric counters of remaining budget, NO dollar amounts.

### data-model §3 fields used here

`budget_hit` (bool), `cost_label` ("small"|"medium"|"large"), `turn_tokens`
(`{input, output}`).

### Gate Criteria

- [ ] BudgetFooter renders INSIDE the answer bubble, slim neutral-amber, on a `budget` event with `ceiling_hit`.
- [ ] Uses the decided copy verbatim (wrap-up + "I didn't get to: …").
- [ ] `Keep going` sends the literal "Keep going" as a normal user message; shown only when `offer_continue`.
- [ ] Footer persists on reload via `activity_summary.budget_hit`.
- [ ] Cost note is panel-only, plain-language size + dimmed token suffix; NO meters/counters/$.
- [ ] Size thresholds are named constants (SCREAMING_SNAKE_CASE).

---

## 🎯 Objective

Build the `BudgetFooter` (graceful budget-hit banner inside the answer bubble
with a quiet "Keep going" quick-reply) and the plain-language cost note in the
activity accordion footer (size label + dimmed token suffix, no meters),
driven by the `budget` event / `activity_summary`.

## 🛠️ Implementation Details

### Files to Create

- `frontend/src/components/chat/BudgetFooter.tsx` - slim neutral-amber strip. Props: `{ notCompleted: string[]; offerContinue: boolean; onKeepGoing: () => void }`. Renders the verbatim wrap-up + "I didn't get to: …" lines; lucide icon (neutral-amber, e.g. `CircleAlert`); `Keep going` button shown only when `offerContinue`.
- `frontend/src/components/chat/CostNote.tsx` - panel footer note. Props: `{ costLabel?: "small"|"medium"|"large"; turnTokens?: { input: number; output: number } }`. Renders `This was a {size} question · ~{N}k tokens` (token suffix dimmed). NO meter.
- `frontend/src/lib/agent/cost-label.ts` - `costLabelFromFraction(fraction: number)` using NAMED CONSTANTS (`COST_LABEL_SMALL_MAX`, `COST_LABEL_MEDIUM_MAX`); helper to format the dimmed token suffix (`~12k`).
- `frontend/src/components/chat/__tests__/BudgetFooter.test.tsx` - vitest: renders verbatim copy + not_completed items; `Keep going` calls `onKeepGoing` and is HIDDEN when `offerContinue` false.
- `frontend/src/components/chat/__tests__/cost-label.test.ts` - vitest: threshold boundaries → small/medium/large (table-driven); token formatting.

### Files to Update (REQUIRED)

- `frontend/src/components/chat/MessageThread.tsx` - render `<BudgetFooter>` inside the assistant answer bubble when a `budget` event with `ceiling_hit` is in the live log OR `message.activity_summary.budget_hit` is true on reload; wire `onKeepGoing` to send the literal "Keep going" as a normal user message (uses the existing send path — same as a user typing it).
- `frontend/src/components/chat/ActivityAccordion.tsx` - render `<CostNote>` in the accordion footer (panel-only), fed from `cost_label` + `turn_tokens`.

### Code/Logic Requirements

- `Keep going` MUST route through the existing user-message send path (new turn, fresh budget). NO new endpoint, NO special flag. The agent resumes unfinished work via conversation history (FR-020).
- `budget` event is intermediate — appended to the activityLog; it does NOT end the turn (the turn ends on `done`/`error`). Confirm the footer reads from the additive budget entry, not a terminal frame.
- Persistence: on reload, render the footer from `activity_summary.budget_hit === true` (the live `not_completed` list may be absent on reload — render the wrap-up line; if `not_completed` is unavailable, omit the "I didn't get to" line gracefully).
- Cost note thresholds: named constants only; no magic numbers. Prefer the persisted `cost_label`; compute via `costLabelFromFraction` when only `turn_tokens` + ceiling are available.
- Token suffix dimmed (`text-muted-foreground`), rounded to `~Nk`. Absolutely NO meters/progress bars/$/remaining-budget counters (FR-021).
- Immutability; small components; named props interfaces.

## 🔌 Wiring Checklist

### Web (React/Next.js)
- [x] **Component** → `BudgetFooter` rendered by `MessageThread.tsx` inside the answer bubble
- [x] **Component** → `CostNote` rendered by `ActivityAccordion.tsx` footer
- [x] **API endpoint** → `Keep going` reuses the existing chat send path (no new endpoint)

## ✅ Verification

**Command**:
```bash
cd frontend && pnpm exec vitest run src/components/chat/__tests__/BudgetFooter.test.tsx src/components/chat/__tests__/cost-label.test.ts
cd frontend && pnpm exec tsc --noEmit
```
**Success Criteria**: vitest passes for footer render + verbatim copy +
not_completed items, `Keep going` send (and hidden when `offer_continue` false),
and cost-label threshold boundaries; `tsc --noEmit` clean.

## 📝 Completion Log

- [ ] `BudgetFooter` implemented (verbatim copy, `Keep going` → normal user message)
- [ ] `CostNote` implemented (plain-language size + dimmed token suffix, NO meters)
- [ ] Size thresholds as named constants
- [ ] Footer persists on reload via `activity_summary.budget_hit`
- [ ] Vitest passes (footer + keep-going + cost-label thresholds)
- [ ] `tsc --noEmit` clean + Biome check clean
