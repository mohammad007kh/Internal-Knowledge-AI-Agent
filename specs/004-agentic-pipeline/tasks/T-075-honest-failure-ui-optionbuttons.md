# Task: T-075 - honest-failure-ui-optionbuttons

**Status**: Pending
**Created**: 2026-06-04 | **Completed**: N/A
**Platform**: web | **Task Target**: frontend
**User Story**: US3 (the assistant checks its work and is honest when stuck)
**Requirement**: FR-013
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

Feature 004's honesty layer (Story 3): when no trustworthy answer is achievable,
the response leads with an honest statement, offers an expandable account of
what was tried (with the failing SQL behind a nested toggle), and proposes next
actions as one-click choices. This task builds the SHARED `OptionButtonGroup`
primitive (reused by clarify options in T-081) and the honest-failure/abstain
turn styling.

### Adopted §3D.1 Design Spec (COPIED VERBATIM from plan.md "Additional UI Requirements")

- Shared `OptionButtonGroup` primitive (clarify options + abstain quick-replies):
  **vertical stack, hints, optional `Suggested` pill (never auto-selected),
  selection echoes as a user message.**
- Honest-failure turn: **extends dimmed-italic fallback styling + SearchX icon +
  thin amber left border; collapsible "What I tried" with SQL behind nested
  toggle.**

### Existing fallback pattern to EXTEND (MessageThread.tsx ~282-296 — COPIED for context)

The assistant bubble already softens fallback replies:
```tsx
// Fallback assistant replies are visually softened so users can tell
// at a glance the system did not produce a grounded answer.
isFallback && 'bg-muted/40'
// …
<div className={cn('break-words text-sm', isFallback && 'italic text-muted-foreground')}>
  {isFallback && (
    <InfoIcon className="mr-1.5 inline-block h-3.5 w-3.5 align-[-2px]" aria-hidden="true" />
  )}
  <MarkdownLite content={message.content} />
</div>
```
Honest-failure EXTENDS this: keep the dimmed-italic `bg-muted/40` base, swap the
glyph to lucide **`SearchX`**, and add a **thin amber left border**.

### OptionButtonGroup spec (load-bearing — accessibility-critical)

- Vertical, full-width stack of **2-4 options**.
- Optional dimmed **hint** line per option.
- Optional quiet **`Suggested` pill** on one option (when `recommended`) — it is
  **NEVER auto-selected** (no default focus/selection; user must choose).
- **Number-key shortcuts 1-4** select the corresponding option.
- **Roving focus** with `role="group"` (arrow-key navigation across options).
- **44px minimum touch targets** (`min-h-11` / equivalent).
- **Selection posts as a NORMAL user message** (the option's label text) via the
  existing send path — it echoes into the thread as the user's reply.

### Honest-failure turn spec

- Base = the extended dimmed-italic fallback styling above + `SearchX` icon +
  thin amber left border.
- A collapsible **"What I tried"** `<details>` section (Radix Collapsible or
  native `<details>`); the **SQL** sits behind a SECOND nested toggle inside it
  (SQL is opt-in-on-demand, not shown by default).
- Suggested next actions render via `OptionButtonGroup`.

### Gate Criteria

- [ ] `OptionButtonGroup` is a SHARED primitive at `frontend/src/components/chat/OptionButtonGroup.tsx` (reused by T-081).
- [ ] 2-4 vertical full-width options, optional hints, optional `Suggested` pill (never auto-selected).
- [ ] Number keys 1-4 + roving focus + `role="group"`; 44px touch targets.
- [ ] Selection posts the option label as a normal user message.
- [ ] Honest-failure turn extends dimmed-italic fallback + `SearchX` + thin amber left border.
- [ ] "What I tried" collapsible with SQL behind a nested toggle.

---

## 🎯 Objective

Build the shared `OptionButtonGroup` primitive (accessible, number-key +
roving-focus, selection-as-message) and the honest-failure/abstain turn styling
(extended dimmed fallback + `SearchX` + amber left border + collapsible "What I
tried" with SQL behind a nested toggle, next actions via `OptionButtonGroup`).

## 🛠️ Implementation Details

### Files to Create

- `frontend/src/components/chat/OptionButtonGroup.tsx` - the shared primitive. Props: `{ options: { id: string; label: string; hint?: string; recommended?: boolean }[]; onSelect: (option) => void }` (2-4 options). Vertical full-width stack; per-option hint; quiet `Suggested` pill when `recommended`; number-key 1-4 handlers; roving focus (`role="group"`, arrow-key roving tabindex); `min-h-11` targets; `onSelect` fires with the chosen option.
- `frontend/src/components/chat/HonestFailureBlock.tsx` - the abstain styling. Props: `{ content: string; whatITried?: { narration: string; sql?: string }; nextActions?: Option[]; onSelectAction?: (o) => void }`. Extends dimmed-italic fallback + `SearchX` + thin amber left border; collapsible "What I tried" with SQL behind a nested toggle; next actions via `OptionButtonGroup`.
- `frontend/src/components/chat/__tests__/OptionButtonGroup.test.tsx` - vitest + testing-library: renders 2-4 options + hints; `Suggested` pill present but NOT auto-selected (no element has selected/focused state on mount); number keys 1-4 select; arrow-key roving focus; `role="group"`; `onSelect` carries the label; (a11y) options are buttons with accessible names.
- `frontend/src/components/chat/__tests__/HonestFailureBlock.test.tsx` - vitest: dimmed-italic + amber-left-border classes + `SearchX`; "What I tried" collapsed by default; SQL hidden behind a second toggle (not visible until opened); next actions render via OptionButtonGroup.

### Files to Update (REQUIRED)

- `frontend/src/components/chat/MessageThread.tsx` - render `<HonestFailureBlock>` for honest-failure/abstain assistant turns (extend the existing `isFallback` branch around the current InfoIcon block); wire `OptionButtonGroup` selection (next actions) to the existing user-message send path (selection = a normal user message).

### Code/Logic Requirements

- `OptionButtonGroup` selection MUST post the option's `label` as a NORMAL user message via the existing send path (it echoes into the thread). The primitive itself only calls `onSelect`; the parent performs the send (keeps the primitive reusable for T-081 clarify).
- `Suggested` pill: never sets default focus or default selection — the user must explicitly pick. Verify in tests that nothing is pre-selected/auto-focused on mount.
- Accessibility: `role="group"` container; roving tabindex (one tabstop, arrow keys move focus); number keys 1-4 map to options 1-4; 44px (`min-h-11`) targets; each option a `<button>` with an accessible name.
- Honest-failure base reuses the existing fallback styling (`bg-muted/40`, `italic text-muted-foreground`) and ADDS `SearchX` + a thin amber left border (`border-l-2 border-amber-*`). Do not introduce red.
- "What I tried": collapsed by default; SQL behind a SECOND nested toggle (SQL never shown until explicitly opened) — matches the security posture (SQL is opt-in-on-demand).
- Immutability; small components; named props interfaces.

## 🔌 Wiring Checklist

### Web (React/Next.js)
- [x] **Component** → `OptionButtonGroup` is shared (reused by `ClarificationCard` in T-081)
- [x] **Component** → `HonestFailureBlock` rendered by `MessageThread.tsx` for abstain turns
- [x] **API endpoint** → selection reuses the existing user-message send path (no new endpoint)

## ✅ Verification

**Command**:
```bash
cd frontend && pnpm exec vitest run src/components/chat/__tests__/OptionButtonGroup.test.tsx src/components/chat/__tests__/HonestFailureBlock.test.tsx
cd frontend && pnpm exec tsc --noEmit
```
**Success Criteria**: vitest passes for keyboard nav (number keys + roving
focus), `role="group"`, never-auto-selected `Suggested`, selection-as-message,
AND honest-failure rendering (dimmed + amber border + `SearchX`, SQL behind
nested toggle); `tsc --noEmit` clean.

## 📝 Completion Log

- [ ] `OptionButtonGroup` shared primitive implemented (a11y: number keys, roving focus, role=group, 44px)
- [ ] `Suggested` pill never auto-selected (tested)
- [ ] Selection posts as a normal user message
- [ ] `HonestFailureBlock` implemented (extended fallback + `SearchX` + amber left border + nested SQL toggle)
- [ ] Vitest passes (a11y keyboard nav, selection-as-message, abstain render)
- [ ] `tsc --noEmit` clean + Biome check clean
