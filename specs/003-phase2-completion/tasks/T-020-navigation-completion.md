# T-020: Frontend — Admin + Chat Sidebars, Navigation Completion

- **Status**: Pending
- **Created**: 2026-04-22
- **Branch**: `003-phase2-completion`
- **User Story**: As a user, I want consistent navigation that shows me all available pages and highlights where I am, in both the admin area and the chat interface.
- **Requirement**: FR-035 (admin sidebar complete), FR-036 (chat sidebar complete), FR-037 (active link highlighting)
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
| `ui_specs.icons` | lucide-react |
| `ui_specs.dark_mode` | true |
| `ui_specs.responsive` | true |
| `conventions.files` | kebab-case (Next.js) |

### Domain Rules
- All dashboard pages live under `frontend/src/app/(dashboard)/`.
- Admin pages: `(dashboard)/admin/**`.
- Chat pages: `(dashboard)/chat/**`.
- Active link: use `usePathname()` from `next/navigation` and compare to current route.
- Admin sidebar is admin-only — hide from `role: 'user'` users entirely (or redirect them from `/admin/**` routes).
- Chat sidebar shows user's sessions list (loads from API).
- Mobile: sidebars collapse to hamburger drawer.

### All Admin Nav Links (complete list)
| Label | Route | Icon |
|---|---|---|
| Dashboard | /admin | LayoutDashboard |
| Sources | /admin/sources | Database |
| Users | /admin/users | Users |
| LLM Settings | /admin/llm-settings | Cpu |
| Policy & Guardrails | /admin/policy | Shield |
| Analytics | /admin/analytics | BarChart |

### All Chat Nav Links (complete list)
| Label | Route | Icon |
|---|---|---|
| New Chat | /chat/new | PlusCircle |
| (Session list) | /chat/{id} | MessageSquare |
| Profile | /profile | UserCircle |

### Gate Criteria
- Admin sidebar shows all 6 links listed above.
- Chat sidebar shows "New Chat" button + session list + profile link.
- Active link has distinct visual state (border-left or background highlight).
- Sidebars collapse correctly on mobile.
- `role: 'user'` cannot see or access admin sidebar links.

---

## 🎯 Objective

Complete both sidebars so every page in the app is reachable from the nav. Wire active-link highlighting. Ensure role-based visibility hides admin nav from regular users.

---

## 🛠️ Implementation Details

### Files to Update

1. **`frontend/src/components/layout/AdminSidebar.tsx`** (update):
   - Ensure all 6 admin nav items are present with correct routes and icons.
   - Use `usePathname()` to apply active styles:
     ```tsx
     const isActive = pathname.startsWith(href);
     className={cn('flex items-center gap-2 px-3 py-2 rounded-md', isActive && 'bg-muted font-semibold')}
     ```
   - Show user's name/email at bottom of sidebar.
   - "Logout" button at bottom → calls existing auth logout.

2. **`frontend/src/components/layout/ChatSidebar.tsx`** (update):
   - "New Chat" button → `POST /chat/sessions` → redirect to `/chat/{new_id}`.
   - Session list: `useQuery(['sessions'], getSessions)` → render each as `<Link href={/chat/${id}}>`.
   - Active session highlighted.
   - Profile link at bottom → `/profile`.
   - Session rename: double-click or ⋯ menu → inline edit.
   - Session delete: ⋯ menu → confirmation → `DELETE /chat/sessions/{id}`.

3. **`frontend/src/app/(dashboard)/layout.tsx`** (update):
   - Conditionally render `AdminSidebar` or `ChatSidebar` based on current route prefix.
   - Mobile: wrap sidebar in a `Sheet` component (hamburger trigger in top navbar).

4. **`frontend/src/lib/api/chat.ts`** — Ensure exported:
   - `getSessions()` — GET /chat/sessions
   - `createSession(body)` — POST /chat/sessions
   - `deleteSession(id)` — DELETE /chat/sessions/{id}
   - `renameSession(id, title)` — PATCH /chat/sessions/{id}

### Role-Based Guard
```tsx
// In AdminSidebar (or layout):
const { user } = useAuth();
if (user?.role !== 'admin') return null; // or redirect
```

---

## 🔌 Wiring Checklist (Web frontend)

- [ ] `AdminSidebar` has all 6 links including LLM Settings and Policy & Guardrails (new from this phase).
- [ ] `ChatSidebar` has New Chat, session list, and Profile.
- [ ] Active link styling applied via `usePathname()`.
- [ ] Admin sidebar hidden from `role: 'user'`.
- [ ] Mobile sidebar collapses to drawer (shadcn `Sheet`).
- [ ] Chat session create, rename, delete all wired.
- [ ] Layout correctly picks which sidebar to show.

---

## ✅ Verification

```bash
cd frontend && npx tsc --noEmit 2>&1 | grep "Sidebar\|layout" | head -10
```
Expected: no TypeScript errors.

Manual smoke test:
1. Admin user → all 6 admin nav links visible; active route highlighted.
2. Regular user → admin links not visible.
3. Chat interface → New Chat button creates session and navigates.
4. Chat session rename via ⋯ menu → name updates.
5. Chat session delete via ⋯ menu → confirmation dialog → removed from list.
6. Mobile viewport → sidebar hidden; hamburger opens drawer.

---

## 📝 Completion Log

- [ ] Admin sidebar: all 6 links with icons and active state.
- [ ] Chat sidebar: New Chat, sessions, profile, session actions.
- [ ] Mobile drawer implemented.
- [ ] Role guard hides admin nav from regular users.
- [ ] `npx tsc --noEmit` passes.
- [ ] Traceability: FR-035, FR-036, FR-037 → this task → commit SHA _TBD_.
