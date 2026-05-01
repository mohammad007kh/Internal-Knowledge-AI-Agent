# T-018: Frontend — Company Policy Editor + Guardrail Events Page

- **Status**: Pending
- **Created**: 2026-04-22
- **Branch**: `003-phase2-completion`
- **User Story**: As an admin, I want to edit the company policy rules that guide the AI's responses, and audit which messages were blocked or sanitized by guardrails.
- **Requirement**: FR-025 (view policy), FR-026 (edit/save policy), FR-027 (list guardrail events), FR-028 (view event detail with original input)
- **Priority**: P1

---

## 📋 Embedded Context

### Registry Standards (binding)
| Key | Value |
|-----|-------|
| `frontend.framework` | nextjs (v15, App Router) |
| `frontend.ui_library` | shadcn/ui |
| `frontend.styling` | tailwind (v4) |
| `frontend.state_management` | TanStack Query + React Context |
| `frontend.form_library` | react-hook-form |
| `frontend.validation_library` | zod |
| `ui_specs.icons` | lucide-react |
| `ui_specs.notifications` | sonner |
| `ui_specs.dark_mode` | true |
| `conventions.files` | kebab-case (Next.js) |
| `api.versioning` | /api/v1/ |
| `api.pagination` | offset (limit/offset/total) |

### Domain Rules
- All API calls go through `apiClient` in `src/lib/api-client.ts`.
- TanStack Query for server state; React Hook Form for policy editor.
- Policy `content` is raw markdown/text; render as `<Textarea>` — no rich text editor.
- Policy versioning: each save creates a new version (backend handles this); show current `version` and `created_at`.
- Guardrail events table: paginated with limit/offset.
- Event detail: `original_input` contains the user's blocked message — display with appropriate content warning.
- `guard_type` filter: `input` or `output`. `action` filter: `blocked` or `sanitized`.

### Dependent Tasks
- T-010: provides `GET/PUT /admin/policy` backend endpoints.
- T-011: provides `GET /admin/guardrail-events` and `GET /admin/guardrail-events/{id}` backend endpoints.

### Gate Criteria
- Policy editor shows current content; Save persists new version.
- Version number and timestamp visible after save.
- Guardrail events table paginated; filter by guard_type and action works.
- Clicking a row opens detail sheet/dialog with `original_input`.
- `original_input` displayed with a content warning label.

---

## 🎯 Objective

Build `/admin/policy` page with two sections: policy editor (top) and guardrail events audit log (bottom). Both sections share the same page but are visually distinct.

---

## 🛠️ Implementation Details

### Files to Create

1. **`frontend/src/app/(dashboard)/admin/policy/page.tsx`** — Page shell:
   - Loads policy via `useQuery(['policy'], getPolicy)`.
   - Renders `<PolicyEditor>` and `<GuardrailEventsTable>`.

2. **`frontend/src/components/admin/PolicyEditor.tsx`**:
   - `<Textarea>` bound to React Hook Form field `content`.
   - Footer row: version badge + last saved timestamp.
   - Save button → `PUT /admin/policy` → `toast.success('Policy saved (v{n})')`.
   - Unsaved changes indicator (dirty state from `formState.isDirty`).

   Zod schema:
   ```ts
   const policySchema = z.object({
     content: z.string().min(10, 'Policy must be at least 10 characters'),
   });
   ```

3. **`frontend/src/components/admin/GuardrailEventsTable.tsx`**:
   - Columns: Guard Type badge | Action badge | Trigger Reason | User | Date.
   - Filter bar: `<Select>` for guard_type, `<Select>` for action.
   - Pagination: `<Button>` Prev/Next with count display.
   - Row click → opens `<GuardrailEventDetailSheet>`.

4. **`frontend/src/components/admin/GuardrailEventDetailSheet.tsx`**:
   - Uses shadcn `Sheet` (side panel).
   - Shows all event fields.
   - `original_input` displayed in a `<Card>` with red border and label "⚠️ Original blocked input".
   - `guard_type` and `action` as colored badges.

5. **`frontend/src/lib/api/policy.ts`**:
   ```ts
   export const getPolicy = () => apiClient.get<Policy>('/admin/policy');
   export const updatePolicy = (content: string) => apiClient.put<Policy>('/admin/policy', { content });
   ```

6. **`frontend/src/lib/api/guardrail-events.ts`**:
   ```ts
   export const getGuardrailEvents = (params: GuardrailEventsParams) =>
     apiClient.get<GuardrailEventsResponse>('/admin/guardrail-events', { params });
   export const getGuardrailEvent = (id: string) =>
     apiClient.get<GuardrailEventDetail>(`/admin/guardrail-events/${id}`);
   ```

### Badge Colors
- `guard_type: input` → blue; `output` → purple.
- `action: blocked` → red; `sanitized` → amber.

---

## 🔌 Wiring Checklist (Web frontend)

- [ ] Page at `app/(dashboard)/admin/policy/page.tsx`.
- [ ] `PolicyEditor` uses React Hook Form; dirty state shows "Unsaved changes" indicator.
- [ ] Policy save toast includes version number.
- [ ] `GuardrailEventsTable` paginates with limit=20.
- [ ] Row click opens `GuardrailEventDetailSheet` with `original_input`.
- [ ] `getPolicy`, `updatePolicy` exported from `src/lib/api/policy.ts`.
- [ ] `getGuardrailEvents`, `getGuardrailEvent` exported from `src/lib/api/guardrail-events.ts`.
- [ ] Dark mode classes applied.

---

## ✅ Verification

```bash
cd frontend && npx tsc --noEmit 2>&1 | grep "policy\|guardrail\|Policy\|Guardrail" | head -10
```
Expected: no TypeScript errors.

Manual smoke test:
1. Navigate to `/admin/policy` → current policy text in textarea; version number visible.
2. Edit text → "Unsaved changes" indicator appears.
3. Save → toast shows new version number.
4. Scroll to guardrail events table → filter by `blocked` → list updates.
5. Click a row → side sheet opens with `original_input` in red card.

---

## 📝 Completion Log

- [ ] Policy editor with form validation and dirty state.
- [ ] Guardrail events table with pagination and filters.
- [ ] Event detail sheet with original input warning.
- [ ] API functions in `policy.ts` and `guardrail-events.ts`.
- [ ] `npx tsc --noEmit` passes.
- [ ] Traceability: FR-025, FR-026, FR-027, FR-028 → this task → commit SHA _TBD_.
