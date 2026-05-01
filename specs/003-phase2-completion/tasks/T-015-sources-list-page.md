# T-015: Sources List Page — Status Badges, Document Count, Sync Now

**Feature**: Phase 2 — Product Completion (Internal Knowledge AI Agent)
**Branch**: `003-phase2-completion`
**Priority**: P1
**Agent**: frontend-developer
**Requirements**: FR-009 (type icon, status badge, mode badge, doc count, last synced, actions), FR-010 (search, filter by type, filter by status)

---

## 📋 Embedded Context

### Project
An AI-powered internal knowledge retrieval and Q&A system. It indexes internal documents and surfaces relevant answers through a conversational interface using an 8-node LangGraph pipeline.

### Feature Summary
Phase 2B completes the admin experience. These frontend tasks deliver: sources list with status/badges/sync controls, source detail with 4 tabs, LLM settings admin page, company policy editor with guardrail audit log, users page improvements with source access tab and pending invitations, and the navigation sidebar for both admin and chat layouts.

### Registry Standards (binding)
| Key | Value |
|-----|-------|
| `architecture.pattern` | modular_monolith |
| `frontend.framework` | nextjs (v15, App Router) |
| `frontend.ui_library` | shadcn/ui |
| `frontend.styling` | tailwind (v4) |
| `frontend.state_management` | TanStack Query + React Context |
| `frontend.data_fetching` | tanstack-query |
| `frontend.form_library` | react-hook-form |
| `frontend.validation_library` | zod |
| `ui_specs.icons` | lucide-react |
| `ui_specs.notifications` | sonner |
| `ui_specs.dark_mode` | true |
| `ui_specs.responsive` | true |
| `conventions.files` | kebab-case (Next.js) |
| `conventions.classes` | PascalCase |
| `api.versioning` | /api/v1/ |
| `api.auth_header` | bearer |

### Domain Rules (frontend-developer)
- All API calls go through `apiClient` in `src/lib/api-client.ts`.
- Typed API functions live in `src/lib/api/` directory (one file per resource).
- TanStack Query (`useQuery`/`useMutation`) for ALL server state — no local fetch effects.
- shadcn/ui components (Table, Dialog, Badge, Card, Tabs, Select, Switch, Textarea, Input, Button, DropdownMenu, Tooltip).
- Forms: React Hook Form + Zod resolver.
- Toast notifications: sonner (`toast.success()`, `toast.error()`, `toast.info()`).
- All dashboard pages in `frontend/src/app/(dashboard)/...`.
- Admin components in `frontend/src/components/admin/...`.
- Icons from `lucide-react` only.

---

## 🎯 Objective

Complete the `/admin/sources` list page so it shows every source with its live status, supports search + type/status filters, and offers a working "Sync Now" action that live-polls until completion. This is the operational dashboard admins rely on to know which connectors are healthy.

---

## 🛠️ Implementation Details

### Files to Update

1. **`frontend/src/components/admin/SourcesTable.tsx`** — Complete the table with all columns, actions, search, and filters.
2. **`frontend/src/lib/api/sources.ts`** — Ensure typed functions exist: `getSources()`, `getSource(id)`, `syncSource(id)`, `deleteSource(id)`.

### New Components to Create

- **`frontend/src/components/admin/SourceStatusBadge.tsx`** — Status-to-color badge for source status.

### Table Columns (left → right)

| Column | Content |
|---|---|
| Type icon | lucide icon based on source kind |
| Name | clickable link to `/admin/sources/{id}` |
| Status | `<SourceStatusBadge>` |
| Mode | `Live` (green outline) \| `Snapshot` (gray outline) |
| Documents | integer count (fallback `—` if null) |
| Last Synced | relative time (e.g., "2h ago"), `Never` if null |
| Actions | `[Sync Now]` `[⋯]` (Edit, Delete in DropdownMenu) |

### Status Badge Variants (`SourceStatusBadge`)
- `pending` → gray (`bg-gray-200 text-gray-700`)
- `ingesting` → blue + animated `Loader2` spinner (`animate-spin`)
- `ready` → green (`bg-green-100 text-green-800`)
- `error` → red (`bg-red-100 text-red-800`)
- `stale` → amber (`bg-amber-100 text-amber-800`)
- `paused` → gray

### Type Icons (lucide)
- `Database`: postgresql, mysql, mssql, mongodb
- `FileText`: pdf, docx, xlsx, csv, txt, markdown
- `Globe`: web_url
- `Plug`: confluence, sharepoint

Expose a helper `getSourceTypeIcon(type: string)` in `SourcesTable.tsx` (or a local file) that returns the correct icon component.

### "Sync Now" Behavior

```ts
const syncMutation = useMutation({
  mutationFn: (id: string) => syncSource(id),
  onSuccess: () => {
    toast.success('Sync started');
    queryClient.invalidateQueries({ queryKey: ['sources'] });
  },
  onError: (e) => toast.error(`Sync failed: ${e.message}`),
});
```
- Clicking `[Sync Now]` fires the mutation.
- While that row's `status === 'ingesting'`, re-query `GET /api/v1/sources/{id}` via `useQuery` with `refetchInterval: 5000`.
- When status transitions from `ingesting` → `ready` / `error`, show `toast.success("Sync complete")` or `toast.error("Sync failed")` and stop polling (`refetchInterval: false`).

### Search & Filter Bar (above the table)
- `<Input>` with `Search` icon: filters by source `name` client-side, debounced 250ms (use `useDeferredValue` or a small debounce hook).
- `<Select>` Type: `All` / `Database` / `File` / `Web` / `Integration`.
- `<Select>` Status: `All` / `Ready` / `Error` / `Ingesting` / `Pending` / `Stale` / `Paused`.
- All filters compose via `useMemo` over the fetched list.

### Accessibility
- Table has caption for screen readers.
- Sync button includes `aria-label="Sync source {name}"`.
- Status badges expose `aria-label={status}` for icon-only variants.

---

## 🔌 Wiring Checklist (Web frontend)

- [ ] `SourcesTable.tsx` is rendered inside `frontend/src/app/(dashboard)/admin/sources/page.tsx`.
- [ ] `getSources()`, `syncSource()`, `deleteSource()` exported from `frontend/src/lib/api/sources.ts` and use `apiClient`.
- [ ] `SourceStatusBadge` exported as a default export or named export and used in the table.
- [ ] Name column uses Next.js `<Link href={`/admin/sources/${id}`}>`.
- [ ] Toast provider (`<Toaster />`) already mounted in root layout — do NOT duplicate.
- [ ] TanStack Query provider already mounted — reuse the global client.
- [ ] Verify dark-mode classes (`dark:*`) for each badge/background.
- [ ] Mobile (<640px): table becomes horizontally scrollable (`overflow-x-auto`), primary column (Name) stays visible.

---

## ✅ Verification

```bash
cd frontend && npx tsc --noEmit 2>&1 | grep "SourcesTable\|SourceStatusBadge" | head -10
```
Expected: **No TypeScript errors** referencing these files.

Manual smoke test:
1. Navigate to `/admin/sources` — all columns render for every source.
2. Click `Sync Now` on a `ready` source — badge flips to `ingesting` with spinner; after backend completes, flips to `ready` and a success toast appears.
3. Type a partial name in search — list filters live.
4. Change Type filter to `Database` — only DB rows remain.
5. Change Status filter to `Error` — only error rows remain (or empty state shown).

---

## 📝 Completion Log

- [ ] `SourcesTable.tsx` updated with 7 columns, search, 2 filters.
- [ ] `SourceStatusBadge.tsx` created with 6 status variants.
- [ ] `sources.ts` API module has `getSources`, `getSource`, `syncSource`, `deleteSource`.
- [ ] Sync polling stops when status leaves `ingesting`.
- [ ] `npx tsc --noEmit` passes for changed files.
- [ ] Screenshot of populated table added to PR description.
