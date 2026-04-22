# T-016: Frontend — Source Detail Page (4 Tabs)

- **Status**: Pending
- **Created**: 2026-04-22
- **Branch**: `003-phase2-completion`
- **User Story**: As an admin, I want to click on a source and see all its details across Overview, Sync, Access, and Settings tabs.
- **Requirement**: FR-011 (source detail view), FR-012 (view source stats), FR-013 (refresh AI description)
- **Priority**: P1

---

## 📋 Embedded Context

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
| `api.versioning` | /api/v1/ |
| `api.auth_header` | bearer |

### Domain Rules
- All API calls go through `apiClient` in `src/lib/api-client.ts`.
- TanStack Query for all server state.
- shadcn/ui `Tabs`, `Card`, `Badge`, `Button`, `Textarea`, `Dialog` components.
- `connection_config` and `file_storage_path` never appear in API responses — do not attempt to render them.
- "Refresh Description" calls `POST /sources/{id}/refresh-description` and shows proposed description in a Dialog — admin must explicitly click "Save" to persist via `PATCH /sources/{id}`.
- All dashboard pages in `frontend/src/app/(dashboard)/admin/sources/[id]/page.tsx`.

### Dependent Tasks
- T-014: provides `GET /sources/{id}/stats` and `POST /sources/{id}/refresh-description` backend endpoints.
- T-015: provides `SourceStatusBadge` component to reuse.

### Gate Criteria
- Four tabs render: Overview, Sync, Access, Settings.
- Overview tab shows name, description, status badge, document count, chunk count, last synced.
- Sync tab shows sync mode, schedule (if scheduled), sync history placeholder.
- Access tab shows source permissions (which users can see this source).
- Settings tab shows type, retrieval mode, citations enabled toggle, plus Delete button.
- Refresh Description button opens proposed description in Dialog; Save button calls `PATCH /sources/{id}`.
- Navigation: breadcrumb "Sources → {name}" at top.

---

## 🎯 Objective

Build the `/admin/sources/[id]` page with a four-tab layout that surfaces all source metadata, stats, sync history, access controls, and settings. Reuse `SourceStatusBadge` from T-015.

---

## 🛠️ Implementation Details

### Files to Create/Update

1. **`frontend/src/app/(dashboard)/admin/sources/[id]/page.tsx`** — Page component:
   - Fetches `GET /api/v1/sources/{id}` and `GET /api/v1/sources/{id}/stats` in parallel.
   - Renders `<SourceDetailTabs>` passing source + stats data.

2. **`frontend/src/components/admin/SourceDetailTabs.tsx`** — Tabs shell:
   ```tsx
   <Tabs defaultValue="overview">
     <TabsList>
       <TabsTrigger value="overview">Overview</TabsTrigger>
       <TabsTrigger value="sync">Sync</TabsTrigger>
       <TabsTrigger value="access">Access</TabsTrigger>
       <TabsTrigger value="settings">Settings</TabsTrigger>
     </TabsList>
     <TabsContent value="overview"><OverviewTab /></TabsContent>
     <TabsContent value="sync"><SyncTab /></TabsContent>
     <TabsContent value="access"><AccessTab /></TabsContent>
     <TabsContent value="settings"><SettingsTab /></TabsContent>
   </Tabs>
   ```

3. **`frontend/src/components/admin/source-detail/OverviewTab.tsx`**:
   - Name, description (editable via Textarea + Save button → `PATCH /sources/{id}`).
   - Status badge (reuse `SourceStatusBadge`).
   - Stats row: `document_count`, `chunk_count`, `last_synced_at`.
   - "Refresh Description" button → calls `POST /sources/{id}/refresh-description` → opens Dialog with proposed text → Save calls `PATCH /sources/{id}` with `{description: proposed}`.

4. **`frontend/src/components/admin/source-detail/SyncTab.tsx`**:
   - Shows `sync_mode` (Manual / Scheduled / Delta).
   - If scheduled: display `sync_schedule` cron string.
   - "Sync Now" button (same mutation as T-015).
   - Placeholder table for sync job history (can be empty with "No sync history yet" message).

5. **`frontend/src/components/admin/source-detail/AccessTab.tsx`**:
   - Calls `GET /api/v1/sources/{id}/permissions` if endpoint exists, else shows placeholder "Access control coming soon".
   - Lists users with access; admin can revoke.

6. **`frontend/src/components/admin/source-detail/SettingsTab.tsx`**:
   - Shows `source_type`, `retrieval_mode` (Select, editable → PATCH), `citations_enabled` (Switch, auto-saves on toggle).
   - Danger zone: Delete button → confirmation Dialog → calls `DELETE /sources/{id}` → redirects to `/admin/sources`.

7. **`frontend/src/lib/api/sources.ts`** — Add if not present:
   - `getSourceStats(id: string): Promise<SourceStats>`
   - `refreshDescription(id: string): Promise<{ proposed_description: string }>`
   - `updateSource(id: string, body: Partial<SourceUpdateRequest>): Promise<Source>`

### Breadcrumb
Add at top of page:
```tsx
<nav aria-label="breadcrumb">
  <ol>
    <li><Link href="/admin/sources">Sources</Link></li>
    <li aria-current="page">{source.name}</li>
  </ol>
</nav>
```

---

## 🔌 Wiring Checklist (Web frontend)

- [ ] Page exists at `app/(dashboard)/admin/sources/[id]/page.tsx`.
- [ ] `SourceDetailTabs` renders four tab panels.
- [ ] `OverviewTab` shows stats and refresh-description flow.
- [ ] `SettingsTab` delete button shows confirmation dialog before deleting.
- [ ] `getSourceStats`, `refreshDescription`, `updateSource` exported from `src/lib/api/sources.ts`.
- [ ] Link from T-015 sources table (`/admin/sources/{id}`) resolves to this page.
- [ ] No `connection_config` or `file_storage_path` rendered or logged.
- [ ] Dark mode classes applied.

---

## ✅ Verification

```bash
cd frontend && npx tsc --noEmit 2>&1 | grep "source-detail\|SourceDetail" | head -10
```
Expected: no TypeScript errors.

Manual smoke test:
1. Click a source in the list → detail page loads with breadcrumb.
2. Overview tab → stats visible, "Refresh Description" button triggers proposed text dialog.
3. Sync tab → sync mode shown; "Sync Now" triggers ingesting state.
4. Settings tab → Toggle `citations_enabled` → saves without reload.
5. Settings tab → Delete → confirmation dialog → redirect to sources list.

---

## 📝 Completion Log

- [ ] Four tab panels implemented.
- [ ] Overview: stats, refresh-description dialog.
- [ ] Sync: mode, schedule, sync now.
- [ ] Access: placeholder or live permissions.
- [ ] Settings: retrieval mode, citations toggle, delete with confirmation.
- [ ] `npx tsc --noEmit` passes.
- [ ] Traceability: FR-011, FR-012, FR-013 → this task → commit SHA _TBD_.
