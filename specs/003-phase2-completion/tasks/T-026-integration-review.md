# T-026: Integration Review — Full Wiring, Routing & Button Verification

- **Status**: Pending
- **Created**: 2026-04-22
- **Branch**: `003-phase2-completion`
- **User Story**: As the development team, before marking Phase 2 complete, we want a systematic review confirming every backend endpoint has a frontend caller, every navigation link resolves, and every button performs its intended action.
- **Requirement**: All FR-001 through FR-043 — final cross-cutting verification
- **Priority**: P0 (must pass before phase is closed)

---

## 📋 Embedded Context

### Registry Standards (binding)
| Key | Value |
|-----|-------|
| `architecture.pattern` | modular_monolith |
| `frontend.framework` | nextjs (v15, App Router) |
| `frontend.ui_library` | shadcn/ui |
| `backend.framework` | fastapi |
| `api.versioning` | /api/v1/ |
| `api.auth_header` | bearer |
| `testing.e2e_framework` | playwright |

### What This Task Covers
This is a review task, not an implementation task. Its job is to:
1. Audit every backend endpoint defined in plan.md and verify it is called by the frontend.
2. Audit every frontend page and verify it is reachable from the navigation.
3. Audit every button/action in the UI and verify it performs its stated purpose.
4. Report any gaps found as inline checklist items with suggested fixes.

### Gate Criteria
- Every endpoint in the API Contracts section of plan.md has a corresponding frontend API function in `src/lib/api/`.
- Every page in the app is linked from the navigation (sidebar or breadcrumb).
- Every button in the UI either navigates, mutates, or explicitly communicates its disabled state.
- No dead routes (pages that exist but are unreachable from nav).
- No orphan API functions (functions in `src/lib/api/` that are never called).

---

## 🎯 Objective

Perform a systematic end-to-end review across backend endpoints, frontend routes, navigation links, and UI buttons. Produce a report of any gaps and fix them before closing Phase 2.

---

## 🛠️ Review Checklist

### Section 1: Backend Endpoint → Frontend Caller Mapping

For each endpoint, verify a corresponding typed function exists in `frontend/src/lib/api/`:

#### Source Endpoints
- [ ] `POST /sources/inspect` → `inspectSource()` in `sources.ts`
- [ ] `POST /sources/upload-url` → `getUploadUrl()` in `sources.ts`
- [ ] `POST /sources` → `createSource()` in `sources.ts`
- [ ] `GET /sources` → `getSources()` in `sources.ts`
- [ ] `GET /sources/{id}` → `getSource(id)` in `sources.ts`
- [ ] `GET /sources/{id}/stats` → `getSourceStats(id)` in `sources.ts`
- [ ] `POST /sources/{id}/refresh-description` → `refreshDescription(id)` in `sources.ts`
- [ ] `POST /sources/{id}/sync` (if exists) → `syncSource(id)` in `sources.ts`
- [ ] `PATCH /sources/{id}` → `updateSource(id, body)` in `sources.ts`
- [ ] `DELETE /sources/{id}` → `deleteSource(id)` in `sources.ts`

#### Admin LLM Settings
- [ ] `GET /admin/llm-settings` → `getLLMSettings()` in `llm-settings.ts`
- [ ] `PUT /admin/llm-settings/{stage}` → `updateLLMStage(stage, body)` in `llm-settings.ts`
- [ ] `POST /admin/llm-settings/{stage}/test` → `testLLMStage(stage)` in `llm-settings.ts`

#### Admin Policy & Guardrails
- [ ] `GET /admin/policy` → `getPolicy()` in `policy.ts`
- [ ] `PUT /admin/policy` → `updatePolicy(content)` in `policy.ts`
- [ ] `GET /admin/guardrail-events` → `getGuardrailEvents(params)` in `guardrail-events.ts`
- [ ] `GET /admin/guardrail-events/{id}` → `getGuardrailEvent(id)` in `guardrail-events.ts`

#### Users
- [ ] `GET /users/me` → `getCurrentUser()` in `user.ts`
- [ ] `PATCH /users/me` → `updateCurrentUser(body)` in `user.ts`
- [ ] `GET /users/invitations` → `getInvitations(params)` in `invitations.ts`
- [ ] `DELETE /users/invitations/{id}` → `cancelInvitation(id)` in `invitations.ts`

#### Chat
- [ ] `POST /chat/sessions` → `createSession(body)` in `chat.ts`
- [ ] `GET /chat/sessions` → `getSessions()` in `chat.ts`
- [ ] `PATCH /chat/sessions/{id}` → `renameSession(id, title)` in `chat.ts`
- [ ] `DELETE /chat/sessions/{id}` → `deleteSession(id)` in `chat.ts`
- [ ] `GET /chat/sessions/{id}/messages` → `getMessages(sessionId)` in `chat.ts`
- [ ] `POST /chat/sessions/{id}/messages` (SSE) → SSE streaming logic in `ChatInput` component

---

### Section 2: Frontend Pages → Navigation Link Verification

Verify every page is reachable from navigation (sidebar link or breadcrumb):

| Page Route | Reachable From |
|---|---|
| `/admin` (dashboard) | Admin sidebar "Dashboard" |
| `/admin/sources` | Admin sidebar "Sources" |
| `/admin/sources/new` | Sources list "Add Source" button OR empty state CTA |
| `/admin/sources/[id]` | Sources table row name link |
| `/admin/users` | Admin sidebar "Users" |
| `/admin/llm-settings` | Admin sidebar "LLM Settings" |
| `/admin/policy` | Admin sidebar "Policy & Guardrails" |
| `/admin/analytics` | Admin sidebar "Analytics" |
| `/chat/new` | Chat sidebar "New Chat" button |
| `/chat/[id]` | Chat sidebar session list item |
| `/profile` | Chat sidebar "Profile" link |
| `/login` | Unauthenticated redirect |

- [ ] All rows above pass (manual nav walk-through).
- [ ] No 404 when clicking any of the above.
- [ ] Back-button (browser) works correctly on detail pages.
- [ ] Breadcrumbs on detail pages link to correct parent pages.

---

### Section 3: Button → Action Verification

Every interactive button must be verified:

#### Admin Sources Page
- [ ] "Add Source" button → navigates to source wizard / new source page.
- [ ] "Sync Now" in table row → fires `POST /sources/{id}/sync`, shows spinner on that row.
- [ ] ⋯ menu "Edit" → navigates to source detail / settings tab.
- [ ] ⋯ menu "Delete" → confirmation dialog → `DELETE /sources/{id}` → row removed.
- [ ] Search input → filters source list client-side.
- [ ] Type filter → filters source list.
- [ ] Status filter → filters source list.

#### Source Detail Page
- [ ] Overview tab → "Refresh Description" button → proposed text dialog → "Save" button persists via PATCH.
- [ ] Sync tab → "Sync Now" button → fires sync mutation.
- [ ] Settings tab → Citations Enabled switch → auto-saves.
- [ ] Settings tab → Retrieval Mode select → save button persists.
- [ ] Settings tab → "Delete Source" → confirmation dialog → DELETE → redirect to sources list.
- [ ] Breadcrumb "Sources" link → navigates to sources list.

#### Admin Users Page
- [ ] "Invite User" button → opens invite dialog (or navigates to invite page).
- [ ] "Access" button per user row → opens source access dialog.
- [ ] Source access switch per source in dialog → updates permissions via API.
- [ ] Invitations tab → "Cancel" button → `DELETE /invitations/{id}` → row removed (or 409 error toast).

#### Admin LLM Settings
- [ ] Save button per stage card → `PUT /admin/llm-settings/{stage}` → toast success.
- [ ] "Test Connection" button → `POST /admin/llm-settings/{stage}/test` → inline result shown.
- [ ] Enabled toggle per stage → part of save form (not auto-save).

#### Admin Policy Page
- [ ] Policy textarea → edit → "Save" button → `PUT /admin/policy` → version updated in UI.
- [ ] Guardrail events table row → click → side sheet opens with full event detail.
- [ ] Guardrail filter (guard_type, action) → updates table data.
- [ ] Pagination Prev/Next → correct page loaded.

#### Chat Interface
- [ ] "New Chat" button → `POST /chat/sessions` → navigates to new session.
- [ ] Chat input send button → SSE stream starts, tokens appear.
- [ ] Chat session rename (⋯ menu or double-click) → `PATCH /chat/sessions/{id}` → name updates.
- [ ] Chat session delete (⋯ menu) → confirmation → `DELETE /chat/sessions/{id}` → removed from sidebar.
- [ ] Citation panel expand/collapse (if shown) → toggles citation details.
- [ ] Clarification card buttons → submits clarification response.
- [ ] Guardrail blocked card → no action button (informational only).

#### Profile Page
- [ ] "Save" button (profile form) → `PATCH /users/me` → toast success.
- [ ] "Change Password" button → `PATCH /users/me` with passwords → success or field error.
- [ ] Citations preference switch → part of profile save (not auto-save).

#### Shared / Global
- [ ] Logout button (sidebar bottom) → clears tokens → redirect to `/login`.
- [ ] Error state "Try again" button → calls `refetch()` (not full page reload).
- [ ] Empty state action buttons → navigate / trigger mutations correctly.
- [ ] Offline toast "network restored" → auto-dismisses after 3s.

---

### Section 4: Playwright E2E Coverage Check

Run existing Playwright tests and confirm critical flows are covered:

```bash
cd frontend && npx playwright test --reporter=list 2>&1 | tail -30
```

Critical flows that MUST have at least one E2E test:
- [ ] Admin can register a new source (wizard completion).
- [ ] User can chat and receive a streamed response.
- [ ] Admin can save LLM settings and test connection.
- [ ] User can update their profile name.
- [ ] Admin can cancel a pending invitation.
- [ ] Offline → online toast cycle.

If any flow is missing an E2E test, add a `TODO` in `frontend/tests/` and create a GitHub issue.

---

## 🔌 Wiring Checklist (Web — both backend + frontend)

- [ ] All Section 1 endpoint→caller pairs verified.
- [ ] All Section 2 page→nav pairs verified (no dead routes, no unreachable pages).
- [ ] All Section 3 buttons verified (no no-op buttons).
- [ ] Section 4 E2E coverage checked; gaps noted.
- [ ] Any gaps found in Sections 1–4 are fixed before marking this task complete.

---

## ✅ Verification Command

```bash
# TypeScript check — must pass clean before marking complete
cd frontend && npx tsc --noEmit 2>&1 | grep -c "error TS" || echo "0 errors"

# Backend imports check
cd backend && python -m pytest tests/ -x -q --tb=short 2>&1 | tail -20

# Playwright smoke run (adjust to your test file names)
cd frontend && npx playwright test --headed --timeout=30000 2>&1 | tail -30
```

Expected:
- `0 errors` from tsc.
- All backend tests pass.
- Playwright: all critical flow tests pass.

---

## 📝 Completion Log

- [ ] Section 1: all endpoint→caller pairs verified (gaps fixed).
- [ ] Section 2: all pages reachable from nav (dead routes removed).
- [ ] Section 3: all buttons perform correct actions (no-ops fixed).
- [ ] Section 4: E2E coverage checked; missing tests noted/created.
- [ ] TypeScript check passes.
- [ ] Backend tests pass.
- [ ] Phase 2 marked complete in `index.md`.
