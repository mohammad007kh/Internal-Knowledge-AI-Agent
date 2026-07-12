# Task: T-071 - status-line

**Status**: Pending
**Created**: 2026-06-04 | **Completed**: N/A
**Platform**: web | **Task Target**: frontend
**User Story**: US5 (the agent's thinking is visible, on demand)
**Requirement**: FR-016
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
Story 5 ships a two-layer thinking UX: **Layer 1** is a one-line live status
INSIDE the in-flight assistant turn (this task), replacing the existing pulsing
dots; **Layer 2** is a collapsed activity accordion (T-073). The status line is
the always-visible heartbeat of the agent's work.

### Adopted §3D.1 Design Spec (COPIED from plan.md "Additional UI Requirements")

- Two-layer thinking UX: **Layer 1 status line INSIDE the in-flight turn
  (replaces pulsing dots).**
- Per-role identity uses lucide icons (Compass/FileText/Database/ShieldCheck/
  PenLine); **color expresses STATE only** (amber for retry/fail) — never role.
- Animations: CSS-only 200ms ease; step-done flash ✓ then advance.

### StatusLine spec (this task — load-bearing detail)

- Anatomy: `[glyph] [label] · [2/4]` — a role/state glyph, the current step
  label, then progress `current/total`.
- **Progress count renders only once a plan exists** (i.e. a `plan` event has
  populated `progress.total`); before that, show glyph + label only.
- **Step-done flash**: when a step reaches `finished`, show a ✓ flash for
  ~600ms, then advance to the next step's started label.
- **Amber for retrying** (`state: "retrying"`) — NEVER red. (Red is reserved;
  amber = trouble-but-recovering, the calm-honesty palette.)
- **Budget-hit terminal label**: when a `budget` entry with `ceiling_hit` is in
  the log, the status line shows the wrap-up terminal label.
- **Collapses into a summary chip** when the answer starts streaming (deltas
  begin) — the live status line yields to T-072's post-answer chip.
- **Mobile**: truncate the label (ellipsis); never wrap to a second line.

### Source of state

Reads the per-turn `activityLog: ActivityEntry[]` produced by T-070
(`frontend/src/lib/sse/agent-events.ts`). Derive the "current step", its state,
and `progress` from the log — do not re-parse SSE here.

### Gate Criteria

- [ ] StatusLine renders INSIDE the in-flight assistant turn and replaces PulsingDots.
- [ ] Progress `· N/M` appears ONLY after a plan exists.
- [ ] Retrying state is amber, never red.
- [ ] Step-done ✓ flash (~600ms) then advance.
- [ ] Collapses to summary chip once answer streaming begins.
- [ ] Label truncates on mobile (no wrap).

---

## 🎯 Objective

Build the `StatusLine` component that renders the live one-line agent status
INSIDE the in-flight assistant turn (replacing PulsingDots in `MessageThread`),
driven entirely by the per-turn `activityLog` from T-070.

## 🛠️ Implementation Details

### Files to Create

- `frontend/src/components/chat/StatusLine.tsx` - the component. Props: a named TS interface (e.g. `StatusLineProps { activityLog: ActivityEntry[]; isStreaming: boolean }`). Derives current step, state, progress. Renders `[glyph] [label] · [N/M]`; amber when retrying; ✓ flash on step-done then advance; budget-hit terminal label; collapse when `isStreaming` (deltas started).
- `frontend/src/components/chat/__tests__/StatusLine.test.tsx` - vitest + testing-library: render from a SCRIPTED `activityLog` for each state — (a) no plan yet → glyph+label, no progress; (b) plan present → shows `· 1/4`; (c) retrying → amber class, NO red; (d) step finished → ✓ flash then next label; (e) budget-hit → terminal label; (f) `isStreaming` true → collapses (chip handoff).

### Files to Update (REQUIRED)

- `frontend/src/components/chat/MessageThread.tsx` - replace the in-flight PulsingDots indicator on the assistant turn with `<StatusLine activityLog={…} isStreaming={…} />`. (Full wiring of activityLog plumbing is finalized in T-077; here, integrate the component at the PulsingDots site and pass through the available log.)

### Code/Logic Requirements

- Glyphs: use lucide icons consistent with the per-role identity set (Compass=Planner, FileText=File reader, Database=SQL expert, ShieldCheck=Verifier, PenLine=Answer writer). Map the current entry's `role` → icon.
- Color encodes STATE only: default/neutral while progressing; amber (`text-amber-*` / Tailwind amber) when `state === "retrying"` or a failure is in flight. Never red.
- Progress: render `· {current}/{total}` only when `total` is known (a plan exists). Hide otherwise.
- Step-done flash: on transition to `finished`, swap the glyph to a ✓ for ~600ms (CSS/timeout), then advance to the next started step. Keep it CSS-only / minimal per the registry animation budget (200ms ease elsewhere; this is the one ~600ms flash the design calls for).
- Budget-hit: if the log contains a budget entry with `ceiling_hit`, render the calm wrap-up terminal label instead of step progress.
- Collapse: when `isStreaming` (answer deltas have begun), the StatusLine stops rendering live progress (the post-answer summary chip from T-072 takes over).
- Mobile truncation: single-line, `truncate` on the label.
- Immutability + small component (<150 lines); named props interface.

## 🔌 Wiring Checklist

### Web (React/Next.js)
- [x] **Component** → rendered by `MessageThread.tsx` in place of PulsingDots
- [ ] **API endpoint** → N/A (reads in-memory activityLog)

## ✅ Verification

**Command**:
```bash
cd frontend && pnpm exec vitest run src/components/chat/__tests__/StatusLine.test.tsx
cd frontend && pnpm exec tsc --noEmit
```
**Success Criteria**: vitest passes for all scripted-`activityLog` states (no
plan / plan / retrying-amber-not-red / step-done-flash / budget-hit /
streaming-collapse); `tsc --noEmit` clean.

## 📝 Completion Log

- [ ] `StatusLine` component implemented with named props interface
- [ ] Renders inside the in-flight turn (replaces PulsingDots in MessageThread)
- [ ] All state renderings tested (vitest, scripted activityLog)
- [ ] Amber-not-red verified for retrying
- [ ] `tsc --noEmit` clean + Biome check clean
