# T-039 — Phase 1 Sign-Off Checklist

## Metadata
| Field | Value |
|---|---|
| **ID** | T-039 |
| **Title** | Phase 1 Sign-Off — end-to-end smoke test and gate verification |
| **Phase** | 1 — Authentication & User Management |
| **Domain** | QA / Verification |
| **Depends on** | T-020, T-025–T-038 |
| **Blocks** | T-040 |
| **Est. complexity** | S |

### Project Standards
| Standard | Value |
|---|---|
| Python | 3.12 |
| Backend | FastAPI · SQLAlchemy 2.x · Pydantic v2 · dependency-injector |
| Frontend | Next.js 15 App Router · shadcn/ui · Tailwind CSS v4 |
| Auth | JWT 15-min access + 7-day rotating httpOnly refresh cookie · bcrypt · RBAC |
| Error Format | RFC 7807 Problem Details — all non-2xx API responses |
| Testing | pytest + httpx + Playwright · ≥80% coverage |
| Infrastructure | Docker Compose 9 services |

---

## Goal
Verify that every Phase 1 deliverable is present and working before opening Phase 2.
This task is a **comprehensive checklist run**, not new code. A developer (or CI job)
works through each item in order; failing items must be resolved before moving on.

---

## Pre-Conditions
All 9 Docker Compose services running and healthy:
```bash
make dev
docker compose ps   # all services: Up (healthy)
```

---

## Checklist

### Backend — API

- [ ] `GET /api/v1/health` → 200 `{"status":"ok","version":"0.1.0"}`
- [ ] `POST /api/v1/auth/login` with bootstrap admin creds → 200 + `access_token` + `refresh_token` cookie
- [ ] `POST /api/v1/auth/login` with wrong password → 401 RFC 7807 body
  (`Content-Type: application/problem+json`, fields: `status`, `type`, `detail`)
- [ ] `POST /api/v1/auth/refresh` (with cookie) → 200 rotated token
- [ ] `POST /api/v1/auth/logout` (Bearer) → 204, cookie cleared
- [ ] `POST /api/v1/auth/password-reset` (any email) → 202
- [ ] `GET /api/v1/users` unauthenticated → 401
- [ ] `GET /api/v1/users` regular user → 403
- [ ] `GET /api/v1/users` admin → 200 paginated list

### Backend — Security

- [ ] Response headers include `X-Content-Type-Options: nosniff`
- [ ] Response headers include `X-Frame-Options: DENY`
- [ ] `POST /api/v1/auth/login` from a single IP 6 times in 1 min → 6th response is 429
- [ ] `refresh_token` cookie is `HttpOnly; Secure; SameSite=Strict`
- [ ] Access token `exp` claim is ≤ 900 seconds from issue time

### Backend — Tests

```bash
cd backend
pytest tests/ -v --tb=short --cov=app --cov-report=term-missing
```
- [ ] All tests green
- [ ] Coverage ≥ 80% on `app/api/v1/auth.py`
- [ ] Coverage ≥ 80% on `app/api/v1/users.py`
- [ ] No test leaves uncommitted data (transaction rollback verified)

### Backend — Code Quality

```bash
cd backend
ruff check src/
mypy src/ --ignore-missing-imports
```
- [ ] `ruff check` → zero errors
- [ ] `mypy` → zero errors on `app/core/`, `app/api/v1/`, `app/services/`, `app/repositories/`

### Frontend — Build

```bash
cd frontend
npm run build
```
- [ ] Zero TypeScript errors
- [ ] Zero ESLint errors (Biome)
- [ ] Bundle builds successfully

### Frontend — Pages

- [ ] `/auth/login` renders without console errors
- [ ] `/auth/setup?token=INVALID` shows "Invalid link" card
- [ ] `/auth/password-reset` renders the request form
- [ ] After login, browser is on `/chat`
- [ ] Navigating to `/auth/login` while authenticated redirects to `/chat`
- [ ] Navigating to `/admin/users` as non-admin redirects to `/chat`
- [ ] `/admin/users` renders the users table for an admin

### Frontend — Auth Context

- [ ] Page refresh with valid refresh cookie restores session (no redirect to login)
- [ ] `useAuth().user` has correct `email` and `role` after login
- [ ] Logout clears the `__access` cookie and redirects to `/auth/login`
- [ ] `must_change_password=true` user is redirected to `/auth/change-password` on every dashboard visit

### E2E — Playwright

```bash
cd frontend
npx playwright test e2e/auth/
```
- [ ] `login.spec.ts` — all 4 tests pass
- [ ] `setup.spec.ts` — all 4 tests pass
- [ ] `password-reset.spec.ts` — both tests pass

### Data Integrity

- [ ] Invitation tokens are bcrypt-hashed in the DB (raw token never stored)
- [ ] PasswordResetToken records have `expires_at` set to 1 hour from creation
- [ ] Deactivated user cannot login (credentials correct but `is_active=false` → 401)
- [ ] Inviting an email that already has a pending invitation revokes the old one

---

## Sign-Off Command Sequence
Run the full suite in order:

```bash
make lint         # ruff + biome: zero errors
make test         # pytest: all green, coverage ≥ 80%
make e2e          # playwright: all green
make dev          # all 9 services healthy
```

All four commands must exit 0 before Phase 2 (T-040) begins.

---

## Gate Criteria
- All checklist items above are ticked
- `make lint && make test && make e2e` exits 0
- No open TODO/FIXME comments in Phase 1 source files
- `git log --oneline HEAD~10..HEAD` shows meaningful conventional-commit messages for T-020–T-038
