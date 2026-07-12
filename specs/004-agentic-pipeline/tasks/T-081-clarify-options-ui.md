# Task: T-081 - clarify-options-ui

**Status**: Pending
**Created**: 2026-06-04 | **Completed**: N/A
**Platform**: web | **Task Target**: frontend
**User Story**: US4 (when the question is ambiguous, ask — with choices)
**Requirement**: FR-014, FR-015
**Dependencies**: [T-070-shared-sse-activity-state](./T-070-shared-sse-activity-state.md), [T-075-honest-failure-ui-optionbuttons](./T-075-honest-failure-ui-optionbuttons.md), [T-080-clarify-options-backend](./T-080-clarify-options-backend.md)

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

Feature 004's clarify-with-options (Story 4): an ambiguous question pauses
BEFORE execution and presents 2-4 concrete option buttons plus a free-text
"something else" fallback. This task extends the existing `ClarificationCard`
with the structured options (rendered via the shared `OptionButtonGroup` from
T-075) and parses the extended payload in BOTH stream hooks.

### Adopted §3D.1 Design Spec (COPIED from plan.md "Additional UI Requirements")

- Shared `OptionButtonGroup` primitive (clarify options + abstain quick-replies):
  vertical stack, hints, optional `Suggested` pill (never auto-selected),
  **selection echoes as a user message.**

### Extended `clarification` payload (COPIED VERBATIM from contracts/sse-events.md)

```jsonc
event: clarification
data: {
  "question": "Which users did you mean?",
  "options": [
    {"id": "hr", "label": "Employees", "hint": "HR database", "recommended": false},
    {"id": "crm", "label": "Customers", "hint": "CRM file", "recommended": true},
    {"id": "both", "label": "Both"}
  ],
  "allow_free_text": true
}
```

- Absent `options` = **legacy free-text behavior** (the existing card with just
  the textarea must still work). Additive only.

### ClarificationCard extension spec (this task)

- New OPTIONAL `options[]` prop. When present, render `OptionButtonGroup` ABOVE
  the existing textarea.
- The **textarea remains** as the "Something else…" escape hatch (free-text
  fallback) when `allow_free_text` is true.
- Selecting an option posts the option's **LABEL** as a normal user message
  (echoes into the thread). Unselected options are NOT persisted.
- **Dismiss/supersede behavior unchanged**: a new question supersedes the
  pending clarification (the existing card behavior — do not regress it).
- BOTH stream hooks (`useSandboxStream.ts` PRIMARY + `use-chat-stream.ts`) must
  parse the extended payload (`options` + `allow_free_text`) — via the shared
  T-070 event module.

### KEY ARCHITECTURAL FACT

Both SSE consumers must handle the extended event identically:
- `frontend/src/app/(admin)/admin/sources/[id]/_components/useSandboxStream.ts` (PRIMARY)
- `frontend/src/hooks/use-chat-stream.ts`
(unified onto the shared event module in T-070 — extend the parse there).

### Gate Criteria

- [ ] `ClarificationCard` gains an optional `options[]` prop → renders `OptionButtonGroup` above the textarea.
- [ ] Textarea = "Something else…" free-text escape hatch (when `allow_free_text`).
- [ ] Selection posts the option LABEL as a normal user message (echoes); unselected options NOT persisted.
- [ ] Legacy no-options payload still renders the free-text-only card (additive).
- [ ] Both stream hooks parse the extended payload.
- [ ] Dismiss/supersede behavior unchanged.

---

## 🎯 Objective

Extend `ClarificationCard` with an optional structured-options path (rendered
via the shared `OptionButtonGroup`, textarea as free-text fallback, selection
echoes the label as a user message), and parse the extended `clarification`
payload in both stream hooks — preserving legacy no-options behavior.

## 🛠️ Implementation Details

### Files to Create

- `frontend/src/components/chat/__tests__/ClarificationCard.test.tsx` - vitest + testing-library (if a test file already exists, extend it): (a) options render via `OptionButtonGroup` above the textarea; (b) selecting an option calls the send handler with the option LABEL (echo as user message); (c) free-text fallback (textarea) still works when `allow_free_text`; (d) LEGACY payload with no `options` renders the original free-text-only card; (e) supersede — a new question dismisses the pending clarification (behavior unchanged).

### Files to Update (REQUIRED)

- `frontend/src/components/chat/ClarificationCard.tsx` - add optional `options?: ClarificationOption[]` and `allowFreeText?: boolean` props; render `<OptionButtonGroup options={options} onSelect={…} />` above the existing textarea when options are present; keep the textarea as the free-text fallback; selection posts the option label via the existing send path.
- `frontend/src/lib/sse/agent-events.ts` (shared module from T-070) - extend the `clarification` parse to carry `options[]` + `allow_free_text` (typed `ClarificationOption`). Both hooks already consume this module, so both gain the extended payload for free.

**T-070 handoff (load-bearing):** T-070 deliberately leaves `clarification` parsing inline in both hooks. THIS task moves/extends clarification parsing into the shared `agent-events.ts` module (or extends the inline parse in BOTH hooks consistently — choose one and do it in both); the extended payload is `{question, options[], allow_free_text}` with `options` optional for legacy compatibility.

### Code/Logic Requirements

- Reuse the SHARED `OptionButtonGroup` from T-075 (do NOT build a second options component). It already handles number keys 1-4, roving focus, `role="group"`, 44px targets, and the never-auto-selected `Suggested` pill — pass `recommended` through to it.
- Selection posts the option `label` as a NORMAL user message via the existing send path (echoes into the thread). Unselected options are not persisted (no extra state survives the turn).
- `allow_free_text`: when true, keep the textarea visible as the "Something else…" escape hatch; when false (rare in v1), the card may rely on options only — but default behavior keeps the textarea.
- Legacy compatibility: when the payload has NO `options`, render exactly the existing free-text-only card (no behavior change). This is the additive guarantee.
- Supersede: do not change how a new question dismisses a pending clarification — preserve the existing card lifecycle.
- `ClarificationOption` TS type mirrors the backend `ClarificationOption` (`id`, `label`, `hint?`, `recommended?`).
- Immutability; named props interfaces.

## 🔌 Wiring Checklist

### Web (React/Next.js)
- [x] **Component** → `ClarificationCard` renders `OptionButtonGroup`; rendered by the chat + sandbox surfaces
- [x] **API endpoint** → consumes the extended `clarification` SSE via the shared event module; selection reuses the existing send path (no new endpoint)

## ✅ Verification

**Command**:
```bash
cd frontend && pnpm exec vitest run src/components/chat/__tests__/ClarificationCard.test.tsx
cd frontend && pnpm exec tsc --noEmit
```
**Success Criteria**: vitest passes for options rendering, selection-echo (label
as user message), free-text fallback, AND legacy no-options payload still
rendering the original card; `tsc --noEmit` clean.

## 📝 Completion Log

- [ ] `ClarificationCard` extended with optional `options[]` → renders shared `OptionButtonGroup` above the textarea
- [ ] Textarea free-text fallback preserved
- [ ] Selection posts the option label as a normal user message (echo)
- [ ] Legacy no-options payload still works (additive)
- [ ] Both stream hooks parse the extended payload (via shared module)
- [ ] Vitest passes; `tsc --noEmit` clean + Biome check clean
