# Task: T-073 - activity-accordion-plan-card

**Status**: Pending
**Created**: 2026-06-04 | **Completed**: N/A
**Platform**: web | **Task Target**: frontend
**User Story**: US5 (the agent's thinking is visible, on demand)
**Requirement**: FR-008, FR-017
**Dependencies**: [T-070-shared-sse-activity-state](./T-070-shared-sse-activity-state.md), [T-071-status-line](./T-071-status-line.md)

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

Feature 004's two-layer thinking UX, Layer 2: a collapsed-by-default activity
accordion attached to the assistant turn, with per-role narration blocks and a
conditional plan card. Reads the per-turn `activityLog` from T-070.

### Adopted §3D.1 Design Spec (COPIED VERBATIM from plan.md "Additional UI Requirements")

- Two-layer thinking UX: Layer 2 **collapsed-by-default INLINE accordion — NOT
  the CitationPanel slide-over for the live tree** (slide-over reserved for
  post-hoc per-step payload inspection).
- Per-role blocks: **lucide icons for role identity (Compass/FileText/Database/
  ShieldCheck/PenLine); color expresses STATE only (amber retry/fail); handoff
  connector line + transient `A → B` micro-label; amber dot bubbles to
  collapsed header on trouble.**
- Plan card: **fallback `bg-muted/40` styling; numbered list with ✓ ↻ ○ ✗
  ticks; rendered only for ≥2-step plans or post-revision/clarification.**
- Replan: **one-line "Plan updated — reason" note; superseded plan collapses
  (`▸ Original plan (superseded)`); NO strikethrough diff.**
- Animations: **CSS-only 200ms ease expand, fade+slide-in 8px** for new blocks.

### Role → lucide icon map (load-bearing — icons identify ROLE, color identifies STATE)

| Role | lucide icon |
|------|-------------|
| Planner | `Compass` |
| File reader | `FileText` |
| SQL expert | `Database` |
| Verifier | `ShieldCheck` |
| Answer writer | `PenLine` |

Color rule: icons/blocks are neutral by default; turn **amber** on
retry/failure ONLY. Never use color to distinguish role (icon does that).

### ActivityAccordion spec (this task)

- Collapsed header: `▸ Agent activity · N steps` (N from the log/plan).
- Collapsed-by-default; attached inline to the assistant turn (NOT a slide-over).
- On trouble (any retry/fail in the log) an **amber dot bubbles to the collapsed
  header**.
- Expanded: one block per role that participated; each block shows its narration
  line(s); blocks fade+slide-in 8px (200ms ease) as they arrive live.
- **Handoff connector line** between consecutive blocks + a transient `A → B`
  micro-label on handoff.
- Step row click → opens the **generalized CitationPanel slide-over** showing
  that step's payload from the **in-memory `activityLog`** (post-hoc inspection
  only; review-mode reload has no deep payload → row is non-interactive/disabled
  and the slide-over is not offered).

### PlanCard spec (this task)

- Styling: fallback `bg-muted/40`.
- Numbered list; per-step status ticks: ✓ done · ↻ retrying · ○ pending · ✗ failed.
- **Visibility rule (FR-008): rendered ONLY for plans with ≥2 steps, OR
  post-revision (`revision >= 1`), OR when a clarification occurred.** 1-step
  plans surface via the status line only (T-071) — NO plan card.
- Replan: render a one-line `↻ Plan updated — {reason}` note; the OLD plan card
  collapses to `▸ Original plan (superseded)` (NO strikethrough diff). The new
  plan (revision 1) is the active card.

### Gate Criteria

- [ ] Accordion is INLINE + collapsed-by-default (NOT a slide-over for the live tree).
- [ ] Per-role blocks use the lucide icon map; color encodes STATE only (amber on trouble).
- [ ] Amber dot bubbles to the collapsed header on retry/fail.
- [ ] Handoff connector + transient `A → B` micro-label present.
- [ ] PlanCard renders ONLY for ≥2-step plans / revision≥1 / clarification.
- [ ] Replan = one-line note + superseded collapses (NO strikethrough).
- [ ] Step-row click opens the CitationPanel slide-over from the in-memory activityLog (post-hoc only); disabled in review mode.
- [ ] 200ms ease expand; fade+slide-in 8px for new blocks.

---

## 🎯 Objective

Build the inline `ActivityAccordion` (per-role narration blocks + handoffs) and
the conditional `PlanCard` (numbered status list with FR-008 visibility rules
and replan handling), driven by the per-turn `activityLog` from T-070, with
step-row payload inspection routed through the generalized CitationPanel
slide-over.

## 🛠️ Implementation Details

### Files to Create

- `frontend/src/components/chat/ActivityAccordion.tsx` - inline collapsible (shadcn/Radix Accordion or Collapsible). Props: `{ activityLog: ActivityEntry[]; mode: "live" | "review"; onInspectStep?: (stepId: string) => void }`. Collapsed header `▸ Agent activity · N steps` + amber dot on trouble; expanded per-role blocks with handoff connector + `A → B` micro-label; CSS 200ms ease expand + fade+slide-in 8px for new blocks.
- `frontend/src/components/chat/PlanCard.tsx` - `bg-muted/40` numbered list with ✓ ↻ ○ ✗ ticks; visibility per FR-008 (caller may also gate, but the component encodes the rule via a `shouldRender(plan, revision, hadClarification)` helper); replan one-line note + superseded `▸ Original plan (superseded)` collapse.
- `frontend/src/components/chat/__tests__/ActivityAccordion.test.tsx` - vitest: collapsed-by-default; expand shows per-role blocks with correct icons; amber dot on a log containing a retry/fail; handoff micro-label present; step-row click calls `onInspectStep` in live mode; row disabled / no slide-over in review mode.
- `frontend/src/components/chat/__tests__/PlanCard.test.tsx` - vitest: NOT rendered for a 1-step plan with revision 0 and no clarification; rendered for a 2-step plan; rendered for a 1-step plan when `revision >= 1`; rendered when clarification occurred; status ticks map correctly (✓/↻/○/✗); replan shows one-line note + superseded collapse with NO strikethrough.

### Files to Update (REQUIRED)

- `frontend/src/components/chat/MessageThread.tsx` - render `<ActivityAccordion>` (and `<PlanCard>` inside it when visible) attached to the assistant turn; open state toggled by the T-072 summary chip (review mode) and expandable live.
- `frontend/src/components/chat/CitationPanel.tsx` - generalize so it can present a step's payload (from the in-memory `activityLog`) in addition to citations; expose an open-for-step path used by `onInspectStep`. (If a shared slide-over already exists, extend it; do not create a second slide-over.)

### Code/Logic Requirements

- Icons identify ROLE (map above); color identifies STATE only (amber on retry/fail). No red.
- Accordion is INLINE (Collapsible/Accordion), NOT a slide-over, for the live tree. The slide-over is ONLY for post-hoc per-step payload inspection.
- New blocks animate fade+slide-in 8px (200ms ease) — CSS-only, within the registry animation budget.
- PlanCard visibility helper encodes FR-008 exactly: `steps.length >= 2 || revision >= 1 || hadClarification`.
- Replan: one-line `↻ Plan updated — {reason}`; collapse old plan to `▸ Original plan (superseded)`; the superseded plan stays inspectable (read from `superseded_plan` / the prior log entry). NO strikethrough diff.
- Step-row inspection: in `mode === "live"` (and same-turn just-finished, where the in-memory activityLog still holds deep payloads), clicking a row calls `onInspectStep(stepId)` → opens the CitationPanel slide-over with that step's payload. In `mode === "review"` (reload), deep payloads are absent → rows are non-interactive (disabled cursor, no slide-over).
- **Slide-over data source (resolve the ambiguity explicitly)**: the step-payload slide-over reads ONLY from the in-memory `activityLog` (stream-only payloads per data-model §3). There is NO new backend endpoint in v1 — do NOT create one. Ownership is implicitly satisfied: the activityLog only ever contains the current user's own session stream. (plan.md's "ownership-checked endpoint" phrasing applies only if a payload endpoint is ever added later — out of scope here.) On reload, deep payloads are absent and the slide-over affordance is hidden.
- Immutability; keep each component focused (<300 lines); named props interfaces.

## 🔌 Wiring Checklist

### Web (React/Next.js)
- [x] **Component** → `ActivityAccordion`/`PlanCard` rendered by `MessageThread.tsx`
- [x] **Component** → step inspection routed through the generalized `CitationPanel` slide-over

## ✅ Verification

**Command**:
```bash
cd frontend && pnpm exec vitest run src/components/chat/__tests__/ActivityAccordion.test.tsx src/components/chat/__tests__/PlanCard.test.tsx
cd frontend && pnpm exec tsc --noEmit
```
**Success Criteria**: vitest passes for accordion states, role-icon mapping,
amber-dot-on-trouble, handoff micro-label, live-vs-review step inspection, AND
PlanCard visibility rules + status ticks + replan/superseded rendering; `tsc
--noEmit` clean.

## 📝 Completion Log

- [ ] `ActivityAccordion` implemented (inline, collapsed-by-default, per-role blocks, handoffs)
- [ ] `PlanCard` implemented (`bg-muted/40`, ✓↻○✗ ticks, FR-008 visibility, replan/superseded)
- [ ] CitationPanel generalized for step-payload inspection (live only; disabled in review)
- [ ] Vitest passes (accordion + plan-card visibility + replan)
- [ ] `tsc --noEmit` clean + Biome check clean
