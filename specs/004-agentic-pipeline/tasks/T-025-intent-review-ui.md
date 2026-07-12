# Task: T-025 - intent-review-ui

**Status**: Pending
**Created**: 2026-06-04 | **Completed**: N/A
**User Story**: US1 (admin reviews + authors intent)
**Requirement**: FR-001, FR-002
**Platform**: web | **Subagents Enabled**: yes
**Dependencies**: [T-023-intent-api-endpoints](./T-023-intent-api-endpoints.md)

---

## 📋 Embedded Context (READ THIS FIRST)

<!-- SELF-CONTAINED TASK (Constitution Directive 8): all context needed is here. Do NOT read plan.md/spec.md/stations. -->

### Project Standards (from registry)

| Key | Value |
|-----|-------|
| `architecture.pattern` | modular_monolith |
| `frontend.framework` | nextjs (v15, App Router) |
| `frontend.ui_library` | shadcn (+ Radix) |
| `frontend.styling` | tailwind (v4) |
| `frontend.state_management` | context + TanStack Query v5 |
| `frontend.form_library` | react-hook-form |
| `frontend.validation_library` | zod |
| `conventions.classes` | PascalCase (components) |
| `ui_specs.accessibility` | wcag-aa |
| `ui_specs.notifications` | sonner |
| `testing.e2e_framework` | playwright (unit: Vitest) |

### Feature Summary

Evolve the linear retrieve-then-answer pipeline into a transparent plan-and-execute agent. Admins author and review source intent in the source Settings area: a system-proposed draft (`ai_set`) is shown for review; saving upgrades it to `user_set`, which activates out-of-scope decline authority. This task builds that review UI.

### Domain Rules

- **Capability ramp status copy**: for `ai_set`, the status badge MUST read "AI-proposed — review to activate declines" (FR-002: the review surface must make clear that reviewing activates out-of-scope decline authority).
- **Caps mirrored client-side** (server is source of truth, Zod mirrors it): `purpose` ≤ 500 chars, `example_questions` ≤ 5 items, `out_of_scope` ≤ 10 items.
- **Save = review**: Save → PUT (server flips status to `user_set`); "Regenerate draft" → POST propose, surface a 409 (in-flight) as a Sonner toast.
- Reuse existing source-settings UI patterns (e.g. `AINamingCard.tsx`, the SaveBar) for consistency.

### API Context (frontend client → these endpoints)

```yaml
GET  /api/v1/sources/{id}/intent          → getIntent()
PUT  /api/v1/sources/{id}/intent          → putIntent()  (status → user_set)
POST /api/v1/sources/{id}/intent/propose  → proposeIntent()  (202; 409 = in-flight → toast)
```
(API client functions are added/confirmed in T-037; this task consumes them via TanStack Query hooks.)

### Gate Criteria

- [ ] Intent section rendered in the source Settings area (`app/(admin)/admin/sources/[id]/`).
- [ ] Purpose textarea + example-questions list editor + out-of-scope list editor.
- [ ] Status badge with `ai_set` copy "AI-proposed — review to activate declines".
- [ ] Save → PUT mutation (status becomes `user_set`); "Regenerate draft" → propose POST; 409 → Sonner toast.
- [ ] React Hook Form + Zod schema mirrors server caps (≤500 / ≤5 / ≤10).
- [ ] WCAG-AA: labelled inputs, keyboard-operable list editors.

---

## 🎯 Objective

Build the source-intent review section in the admin source Settings: editable purpose/example-questions/out-of-scope fields, a review-state badge, Save (PUT → `user_set`) and Regenerate-draft (propose, 409 toast), validated client-side with a Zod mirror of server caps.

## 🛠️ Implementation Details

### Files to Create

- `frontend/src/app/(admin)/admin/sources/[id]/_components/IntentSection.tsx` — the PascalCase component: purpose `Textarea`, example-questions list editor, out-of-scope list editor, status badge, Save + Regenerate buttons. React Hook Form + Zod resolver; TanStack Query `useMutation` for PUT and propose.
- `frontend/src/app/(admin)/admin/sources/[id]/_components/__tests__/IntentSection.test.tsx` — Vitest tests (co-located with the component, matching where `AINamingCard.test.tsx` lives): renders fields from `getIntent` data; `ai_set` badge copy present; Save triggers PUT and reflects `user_set`; Regenerate triggers propose; a 409 propose response surfaces a toast; Zod rejects 6 example questions / 501-char purpose.

### Files to Update (REQUIRED)

- `frontend/src/app/(admin)/admin/sources/[id]/page.tsx` (or the Settings tab component it renders) — mount `<IntentSection sourceId=... />` in the Settings area so it is reachable.

### Code/Logic Requirements

- Read `AINamingCard.tsx` and the existing SaveBar test to mirror the established source-settings UX + mutation idiom.
- Zod schema (client mirror): `purpose: z.string().max(500).optional()`, `example_questions: z.array(z.string()).max(5).optional()`, `out_of_scope: z.array(z.string()).max(10).optional()`.
- Status badge variants: `pending_ai` (neutral "Draft pending"), `ai_set` ("AI-proposed — review to activate declines"), `user_set` ("Reviewed").
- Regenerate-draft mutation: on 409 → `toast.error(...)` (Sonner) "A study or proposal is already running."
- No mutation of form state objects in place (immutable updates for list editors).
- Acceptance Criteria:
  - Component renders existing intent values for an `ai_set` source and shows the review-to-activate badge copy.
  - Save calls the PUT mutation; on success the badge updates to "Reviewed" (`user_set`).
  - Submitting 6 example questions is blocked client-side by Zod.

## 🔌 Wiring Checklist

### Web
- [ ] **Backend route** → N/A (consumes T-023)
- [x] **Frontend page** → `IntentSection` mounted in source Settings (`[id]` page)
- [x] **Component** → rendered by the source detail/settings parent
- [x] **API endpoint** → TanStack hooks call getIntent/putIntent/proposeIntent (client funcs wired in T-037)

## ✅ Verification

**Command**:
```bash
cd frontend && pnpm exec vitest run "src/app/(admin)/admin/sources/[id]/_components/__tests__/IntentSection.test.tsx"
cd frontend && pnpm exec tsc --noEmit
```
**Success Criteria**: Vitest reports the intent test file `passed` (render, badge copy, Save→user_set, Regenerate, 409 toast, Zod cap rejection); `tsc --noEmit` exits 0 with no errors.

**Expected output (vitest tail)**:
```
Test Files  1 passed
```

## 📝 Completion Log

- [ ] Code implemented
- [ ] Tests passed
- [ ] Linter passed (Biome)
- [ ] Wiring checklist verified
- [ ] Integration verification passed
