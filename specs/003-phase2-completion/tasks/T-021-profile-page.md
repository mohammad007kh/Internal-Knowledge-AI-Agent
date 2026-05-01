# T-021: Frontend — Profile Page (Name, Password, Citation Preference)

- **Status**: Pending
- **Created**: 2026-04-22
- **Branch**: `003-phase2-completion`
- **User Story**: As an authenticated user, I want to update my display name, change my password, and toggle whether I see citations in chat responses, all from a profile page.
- **Requirement**: FR-032 (view profile), FR-033 (update name/preference), FR-034 (change password)
- **Priority**: P2

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

### Domain Rules
- All API calls go through `apiClient` in `src/lib/api-client.ts`.
- Data loaded via `GET /api/v1/users/me` (already returns `full_name` and `show_citations_preference` after T-013).
- Update via `PATCH /api/v1/users/me`.
- Password change: sends `current_password` + `new_password` — backend returns 400 on wrong current password.
- Citation preference: `show_citations_preference: boolean` — toggle Switch auto-saves or saves with the main form.
- After successful update: invalidate `['user', 'me']` query.

### Dependent Tasks
- T-013: provides `GET/PATCH /users/me` backend endpoints with `full_name` and `show_citations_preference`.

### Gate Criteria
- Profile form pre-filled with current `full_name` from API.
- Saving name/preference updates without requiring password change fields.
- Password change section is separate; requires current + new password.
- Wrong `current_password` → 400 → inline error shown under the current password field.
- `show_citations_preference` Switch saves correctly.

---

## 🎯 Objective

Build `/profile` page with two sections: general profile (name + citation preference) and security (password change). Available to all authenticated users.

---

## 🛠️ Implementation Details

### Files to Create

1. **`frontend/src/app/(dashboard)/profile/page.tsx`** — Page:
   - `useQuery(['user', 'me'], getCurrentUser)`.
   - Renders `<ProfileForm>` and `<PasswordChangeForm>`.

2. **`frontend/src/components/profile/ProfileForm.tsx`** — General info form:

   Fields:
   - `full_name`: `<Input>` pre-filled.
   - `show_citations_preference`: `<Switch>` with label "Show source citations in chat responses".

   Submit: `PATCH /users/me` with `{full_name, show_citations_preference}`.
   On success: `toast.success('Profile updated')`, invalidate `['user', 'me']`.

   Zod schema:
   ```ts
   const profileSchema = z.object({
     full_name: z.string().min(1, 'Name is required').max(100),
     show_citations_preference: z.boolean(),
   });
   ```

3. **`frontend/src/components/profile/PasswordChangeForm.tsx`** — Password section:

   Fields:
   - `current_password`: `<Input type="password">`.
   - `new_password`: `<Input type="password">` (min 8 chars, uppercase + lowercase + number).
   - `confirm_password`: `<Input type="password">` (must match new_password).

   Submit: `PATCH /users/me` with `{current_password, new_password}`.
   On 400 (wrong current password): set field error on `current_password` input.
   On success: `toast.success('Password changed')`, reset form.

   Zod schema:
   ```ts
   const passwordSchema = z.object({
     current_password: z.string().min(1),
     new_password: z.string()
       .min(8)
       .regex(/[A-Z]/, 'Must contain uppercase')
       .regex(/[a-z]/, 'Must contain lowercase')
       .regex(/[0-9]/, 'Must contain number'),
     confirm_password: z.string(),
   }).refine(d => d.new_password === d.confirm_password, {
     message: 'Passwords must match',
     path: ['confirm_password'],
   });
   ```

4. **`frontend/src/lib/api/user.ts`** — Ensure functions:
   ```ts
   export const getCurrentUser = () => apiClient.get<UserPublic>('/users/me');
   export const updateCurrentUser = (body: UserUpdateRequest) =>
     apiClient.patch<UserPublic>('/users/me', body);
   ```

---

## 🔌 Wiring Checklist (Web frontend)

- [ ] Page at `app/(dashboard)/profile/page.tsx`.
- [ ] Profile link in ChatSidebar (wired in T-020) points to `/profile`.
- [ ] `ProfileForm` pre-filled from API; saves name and citation preference.
- [ ] `PasswordChangeForm` shows field error on wrong current password.
- [ ] `getCurrentUser`, `updateCurrentUser` exported from `src/lib/api/user.ts`.
- [ ] TanStack Query cache invalidated after update.
- [ ] Dark mode classes applied.

---

## ✅ Verification

```bash
cd frontend && npx tsc --noEmit 2>&1 | grep "profile\|Profile" | head -10
```
Expected: no TypeScript errors.

Manual smoke test:
1. Navigate to `/profile` → form pre-filled with current name.
2. Update name → save → toast success.
3. Toggle citation preference → save → setting persists on reload.
4. Enter wrong current password → submit → field error shown.
5. Enter correct current password + valid new password → submit → toast success.

---

## 📝 Completion Log

- [ ] `/profile` page with `ProfileForm` and `PasswordChangeForm`.
- [ ] Form pre-fill from API.
- [ ] 400 error → field error on `current_password` input.
- [ ] `show_citations_preference` Switch saves correctly.
- [ ] `npx tsc --noEmit` passes.
- [ ] Traceability: FR-032, FR-033, FR-034 → this task → commit SHA _TBD_.
