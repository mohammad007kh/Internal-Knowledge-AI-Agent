# T-019: Frontend — Users Page (Last Login, Source Access Tab, Invitations Table)

- **Status**: Pending
- **Created**: 2026-04-22
- **Branch**: `003-phase2-completion`
- **User Story**: As an admin, I want to see all users with their last login time, manage which sources each user can access, and cancel pending invitations from one place.
- **Requirement**: FR-029 (user list enhancements), FR-030 (source access tab), FR-031 (invitations table with cancel)
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
- TanStack Query for all server state.
- Users page likely already exists at `app/(dashboard)/admin/users/page.tsx` — enhance it.
- Last login: display as relative time if available; `Never` if null.
- Invitations: show only `pending` status invitations (backend already filters).
- Cancel invitation: calls `DELETE /api/v1/users/invitations/{id}` → 409 if accepted (show error toast).
- After cancel: invalidate `['invitations']` query to refresh list.

### Dependent Tasks
- T-012: provides `GET /users/invitations` and `DELETE /users/invitations/{id}` backend endpoints.

### Gate Criteria
- Users table shows `last_login_at` column (relative time, `Never` if null).
- Each user row has an "Access" action that opens a Source Access dialog.
- Source Access dialog shows which sources the user can access; admin can toggle access.
- Invitations section (separate tab or bottom table) shows pending invitations with Cancel button.
- Cancel on accepted invitation → 409 error toast.
- Cancel on pending invitation → 204 → removed from list.

---

## 🎯 Objective

Enhance `/admin/users` with a last-login column and source-access dialog per user, and add a pending invitations table with cancel action. This may involve adding a Tabs layout to the existing page.

---

## 🛠️ Implementation Details

### Files to Update/Create

1. **`frontend/src/app/(dashboard)/admin/users/page.tsx`** — Add Tabs layout:
   ```tsx
   <Tabs defaultValue="users">
     <TabsList>
       <TabsTrigger value="users">Users</TabsTrigger>
       <TabsTrigger value="invitations">Invitations</TabsTrigger>
     </TabsList>
     <TabsContent value="users"><UsersTable /></TabsContent>
     <TabsContent value="invitations"><InvitationsTable /></TabsContent>
   </Tabs>
   ```

2. **`frontend/src/components/admin/UsersTable.tsx`** — Update columns:

   | Column | Content |
   |---|---|
   | Name/Email | Existing |
   | Role | `admin` / `user` badge |
   | Last Login | Relative time or `Never` |
   | Status | Active / Inactive |
   | Actions | Access button + existing ⋯ menu |

   "Access" button → opens `<SourceAccessDialog userId={user.id}>`.

3. **`frontend/src/components/admin/SourceAccessDialog.tsx`** — Dialog:
   - Fetches `GET /api/v1/sources` (all sources) and `GET /api/v1/users/{id}/source-permissions` (if endpoint exists, else empty).
   - Shows list of sources with Switch per source (on = user has access).
   - Toggle → calls `POST /api/v1/users/{id}/source-permissions` or `DELETE /api/v1/users/{id}/source-permissions/{source_id}`.
   - If permissions endpoint is not yet implemented, render placeholder: "Source access control coming in a future update."

4. **`frontend/src/components/admin/InvitationsTable.tsx`** — New component:
   - Fetches `GET /api/v1/users/invitations` with `useQuery(['invitations'], getInvitations)`.
   - Columns: Email | Role | Invited By | Expires At | Actions (Cancel button).
   - Cancel → `useMutation` calling `cancelInvitation(id)` → on 204: `toast.success`, invalidate query; on 409: `toast.error('Cannot cancel accepted invitation')`.

5. **`frontend/src/lib/api/invitations.ts`** — New file:
   ```ts
   export const getInvitations = (params?: PaginationParams) =>
     apiClient.get<InvitationsResponse>('/users/invitations', { params });
   export const cancelInvitation = (id: string) =>
     apiClient.delete(`/users/invitations/${id}`);
   ```

---

## 🔌 Wiring Checklist (Web frontend)

- [ ] Users page has Tabs: "Users" and "Invitations".
- [ ] `UsersTable` includes `last_login_at` column.
- [ ] "Access" button per user row opens `SourceAccessDialog`.
- [ ] `InvitationsTable` shows pending invitations with Cancel button.
- [ ] Cancel mutation handles 204 (success) and 409 (already accepted) distinctly.
- [ ] `getInvitations`, `cancelInvitation` exported from `src/lib/api/invitations.ts`.
- [ ] Dark mode applied.

---

## ✅ Verification

```bash
cd frontend && npx tsc --noEmit 2>&1 | grep "InvitationsTable\|SourceAccessDialog\|UsersTable" | head -10
```
Expected: no TypeScript errors.

Manual smoke test:
1. Navigate to `/admin/users` → two tabs visible (Users, Invitations).
2. Users tab → `Last Login` column populated or shows `Never`.
3. Click "Access" on a user → dialog opens with source list.
4. Invitations tab → pending invitations listed.
5. Click Cancel on a pending invitation → toast success; row disappears.
6. Cancel on already-accepted invitation → toast error "Cannot cancel accepted invitation".

---

## 📝 Completion Log

- [ ] Users page enhanced with Tabs layout.
- [ ] `last_login_at` column in UsersTable.
- [ ] `SourceAccessDialog` renders source list per user.
- [ ] `InvitationsTable` with Cancel mutation.
- [ ] `npx tsc --noEmit` passes.
- [ ] Traceability: FR-029, FR-030, FR-031 → this task → commit SHA _TBD_.
