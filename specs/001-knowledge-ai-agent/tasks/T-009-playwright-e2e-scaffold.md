---
id: T-009
title: GitHub Actions CI Pipeline â€” Playwright E2E Job
status: Done
created: 2026-02-25
phase: Phase 0 â€” Foundation
user_story: cross
requirements: []
priority: P2
depends_on: [T-007, T-005]
---

## ðŸ“‹ Embedded Context

**Stack**: Next.js 15 App Router Â· Playwright (E2E) Â· Docker Compose  
**E2E framework**: Playwright (configured in `frontend/playwright.config.ts`)  
**Test org**: `frontend/tests/e2e/` â€” full user-flow tests only (no unit tests in e2e folder)

---

## ðŸŽ¯ Objective

Install and configure Playwright in the frontend project, create the `playwright.config.ts` with correct base URL, browser targets, and retry settings. Add a GitHub Actions job that spins up the full stack and runs e2e tests. Create a stub e2e test to confirm the setup works.

---

## ðŸ› ï¸ Files to Create

| Path | Purpose |
|------|---------|
| `frontend/playwright.config.ts` | Playwright configuration |
| `frontend/tests/e2e/.gitkeep` | Placeholder for e2e test directory |
| `frontend/tests/e2e/smoke.spec.ts` | Smoke test: verify login page loads |
| `.github/workflows/e2e.yml` | E2E workflow (runs on PR to main only) |

---

## Implementation

**`frontend/playwright.config.ts`:**
```typescript
import { defineConfig, devices } from "@playwright/test";

export default defineConfig({
  testDir: "./tests/e2e",
  fullyParallel: true,
  forbidOnly: !!process.env.CI,
  retries: process.env.CI ? 2 : 0,
  workers: process.env.CI ? 1 : undefined,
  reporter: "html",
  use: {
    baseURL: process.env.BASE_URL ?? "http://localhost:3000",
    trace: "on-first-retry",
    screenshot: "only-on-failure",
  },
  projects: [
    { name: "chromium", use: { ...devices["Desktop Chrome"] } },
  ],
  webServer: process.env.CI ? undefined : {
    command: "npm run dev",
    url: "http://localhost:3000",
    reuseExistingServer: !process.env.CI,
  },
});
```

**`frontend/tests/e2e/smoke.spec.ts`:**
```typescript
import { test, expect } from "@playwright/test";

test("login page loads", async ({ page }) => {
  await page.goto("/login");
  await expect(page).toHaveTitle(/Knowledge AI Agent/);
  await expect(page.getByRole("heading", { name: /Sign in/i })).toBeVisible();
});

test("unauthenticated access to /chat redirects to /login", async ({ page }) => {
  await page.goto("/chat");
  await expect(page).toHaveURL(/\/login/);
});
```

**`.github/workflows/e2e.yml`:**
```yaml
name: E2E Tests

on:
  pull_request:
    branches: [main]

jobs:
  e2e:
    runs-on: ubuntu-latest
    steps:
      - uses: actions/checkout@v4
      - uses: actions/setup-node@v4
        with: { node-version: "20" }
      - name: Start full stack
        run: |
          cp .env.example .env
          docker compose up -d --wait
        env:
          JWT_SECRET_KEY: e2e-secret-256bits
          JWT_REFRESH_SECRET_KEY: e2e-refresh-256bits
          BOOTSTRAP_ADMIN_EMAIL: admin@e2e.com
          BOOTSTRAP_ADMIN_PASSWORD: AdminE2E123
          ENCRYPTION_KEY: e2etestkey==
      - name: Install Playwright
        run: |
          cd frontend
          npm ci
          npx playwright install --with-deps chromium
      - name: Run E2E tests
        run: cd frontend && npx playwright test
        env:
          BASE_URL: http://localhost:3000
      - uses: actions/upload-artifact@v4
        if: failure()
        with:
          name: playwright-report
          path: frontend/playwright-report/
          retention-days: 7
```

---

## ðŸ”Œ Wiring Checklist

- [ ] `playwright.config.ts` sets `baseURL` from `BASE_URL` env var (defaults to localhost:3000)
- [ ] Smoke test verifies login page renders and `/chat` redirects
- [ ] E2E workflow uses `docker compose up --wait` (requires healthchecks in T-002)
- [ ] Playwright artifacts uploaded on failure for debugging

---

## âœ… Verification

```bash
cd frontend
npx playwright install chromium
npx playwright test --reporter=list
# Expected: "smoke.spec.ts > login page loads" PASSED
#           "smoke.spec.ts > unauthenticated access redirects" PASSED
```

---

## ðŸ“ Completion Log

- [ ] Code implemented
- [ ] Tests passed
- [ ] Linter passed
- [ ] Wiring verified
- [ ] Integration verification passed
