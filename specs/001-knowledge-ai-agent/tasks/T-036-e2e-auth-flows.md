# T-036 â€” Playwright E2E: Auth Flows

## Metadata
| Field | Value |
|---|---|
| **Status** | Done |
| **ID** | T-036 |
| **Title** | Playwright E2E â€” login, setup, password-reset, change-password user journeys |
| **Phase** | 1 â€” Authentication & User Management |
| **Domain** | Testing / E2E |
| **Depends on** | T-009, T-030, T-031, T-032, T-034, T-035 |
| **Blocks** | T-039 |
| **Est. complexity** | M |

### Project Standards
| Standard | Value |
|---|---|
| Python | 3.12 |
| Backend | FastAPI Â· SQLAlchemy 2.x Â· Pydantic v2 Â· dependency-injector |
| Frontend | Next.js 15 App Router Â· shadcn/ui Â· Tailwind CSS v4 |
| Auth | JWT 15-min access + 7-day rotating httpOnly refresh cookie Â· bcrypt Â· RBAC |
| Testing | Playwright Â· â‰¥80% coverage |
| Infrastructure | Docker Compose 9 services |

### Domain Rules
- All passwords validated via validate_password_policy() (FR-034)
- Invitations are the only path to new accounts (FR-021)

---

## Goal
Write Playwright TypeScript tests for the four critical auth user flows. Tests run against
the full Docker Compose stack (all 9 services up). Each test creates its own data via direct
API calls in `beforeAll`/`beforeEach` so tests are self-contained and can be run in any order.

---

## Deliverables

### 1. `frontend/e2e/helpers/api.ts` â€” E2E API helper
```typescript
/**
 * Direct API helpers for E2E test setup/teardown.
 * These bypass the frontend and call the backend directly.
 */

const BASE = process.env.E2E_API_URL ?? "http://localhost:8000/api/v1";

export async function adminLogin(): Promise<string> {
  const res = await fetch(`${BASE}/auth/login`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({
      email: process.env.E2E_ADMIN_EMAIL ?? "admin@knowledge.internal",
      password: process.env.E2E_ADMIN_PASSWORD ?? "Admin@1234",
    }),
  });
  if (!res.ok) throw new Error(`Admin login failed: ${res.status}`);
  const body = await res.json();
  return body.access_token as string;
}

export async function createInvitation(
  token: string,
  email: string,
  role: "user" | "admin" = "user"
): Promise<void> {
  const res = await fetch(`${BASE}/users/invitations`, {
    method: "POST",
    headers: {
      "Content-Type": "application/json",
      Authorization: `Bearer ${token}`,
    },
    body: JSON.stringify({ email, role }),
  });
  if (!res.ok) throw new Error(`Create invitation failed: ${res.status}`);
}
```

---

### 2. `frontend/e2e/auth/login.spec.ts`
```typescript
import { test, expect } from "@playwright/test";

test.describe("Login page", () => {
  test.beforeEach(async ({ page }) => {
    await page.goto("/auth/login");
  });

  test("shows the login card", async ({ page }) => {
    await expect(page.getByRole("heading", { name: "Sign in" })).toBeVisible();
  });

  test("shows inline error for invalid email", async ({ page }) => {
    await page.getByLabel("Email").fill("not-an-email");
    await page.getByLabel("Password").fill("anything");
    await page.getByRole("button", { name: "Sign in" }).click();
    await expect(
      page.getByText("Enter a valid email address")
    ).toBeVisible();
  });

  test("shows toast error on wrong credentials", async ({ page }) => {
    await page.getByLabel("Email").fill("admin@knowledge.internal");
    await page.getByLabel("Password").fill("wrongpassword");
    await page.getByRole("button", { name: "Sign in" }).click();
    // Sonner toast
    await expect(page.getByRole("status").filter({ hasText: /invalid/i })).toBeVisible();
  });

  test("redirects to /chat after successful login", async ({ page }) => {
    await page.getByLabel("Email").fill(
      process.env.E2E_ADMIN_EMAIL ?? "admin@knowledge.internal"
    );
    await page.getByLabel("Password").fill(
      process.env.E2E_ADMIN_PASSWORD ?? "Admin@1234"
    );
    await page.getByRole("button", { name: "Sign in" }).click();
    await page.waitForURL("/chat");
    expect(page.url()).toContain("/chat");
  });

  test("forgot password link navigates to reset page", async ({ page }) => {
    await page.getByRole("link", { name: /forgot password/i }).click();
    await expect(page).toHaveURL("/auth/password-reset");
  });
});
```

---

### 3. `frontend/e2e/auth/setup.spec.ts`
```typescript
import { test, expect } from "@playwright/test";
import { adminLogin, createInvitation } from "../helpers/api";

test.describe("Invitation setup flow", () => {
  let invitationToken: string;
  const testEmail = `setup-${Date.now()}@test.local`;

  test.beforeAll(async () => {
    const adminToken = await adminLogin();
    await createInvitation(adminToken, testEmail);

    // Retrieve the raw token from the backend test helper endpoint
    // (only available when APP_ENV=test or TESTING=true)
    const res = await fetch(
      `${process.env.E2E_API_URL ?? "http://localhost:8000"}/api/v1/_test/invitations/${encodeURIComponent(testEmail)}`
    );
    const body = await res.json();
    invitationToken = body.token as string;
  });

  test("shows invalid-link card when token is missing", async ({ page }) => {
    await page.goto("/auth/setup");
    await expect(page.getByRole("heading", { name: "Invalid link" })).toBeVisible();
  });

  test("shows setup form with valid token", async ({ page }) => {
    await page.goto(`/auth/setup?token=${invitationToken}`);
    await expect(page.getByRole("heading", { name: "Set your password" })).toBeVisible();
  });

  test("shows error for weak password", async ({ page }) => {
    await page.goto(`/auth/setup?token=${invitationToken}`);
    await page.getByLabel("New password").fill("weak");
    await page.getByLabel("Confirm password").fill("weak");
    await page.getByRole("button", { name: "Create account" }).click();
    // Zod inline error
    await expect(page.getByText(/at least 8 characters/i)).toBeVisible();
  });

  test("completes setup and redirects to login", async ({ page }) => {
    await page.goto(`/auth/setup?token=${invitationToken}`);
    await page.getByLabel("New password").fill("Setup@1234");
    await page.getByLabel("Confirm password").fill("Setup@1234");
    await page.getByRole("button", { name: "Create account" }).click();
    await page.waitForURL("/auth/login");
    // Sonner success toast
    await expect(page.getByRole("status").filter({ hasText: /created/i })).toBeVisible();
  });
});
```

---

### 4. `frontend/e2e/auth/password-reset.spec.ts`
```typescript
import { test, expect } from "@playwright/test";

test.describe("Password reset flow", () => {
  test("shows success card regardless of email existence", async ({ page }) => {
    await page.goto("/auth/password-reset");
    await page.getByLabel("Email").fill("nobody@unknown.local");
    await page.getByRole("button", { name: "Send reset link" }).click();
    await expect(page.getByRole("heading", { name: "Check your inbox" })).toBeVisible();
  });

  test("shows invalid-link card when reset token is missing", async ({ page }) => {
    await page.goto("/auth/password-reset/confirm");
    await expect(page.getByRole("heading", { name: "Invalid link" })).toBeVisible();
  });
});
```

---

### 5. `frontend/playwright.config.ts` additions
Ensure the base config (T-009) has the correct `baseURL` and `testDir`:
```typescript
// frontend/playwright.config.ts  (additions to T-009 base)

import { defineConfig, devices } from "@playwright/test";

export default defineConfig({
  testDir: "./e2e",
  fullyParallel: false,        // auth tests share server state
  forbidOnly: !!process.env.CI,
  retries: process.env.CI ? 1 : 0,
  workers: 1,
  reporter: process.env.CI ? "github" : "list",
  use: {
    baseURL: process.env.E2E_BASE_URL ?? "http://localhost:3000",
    trace: "on-first-retry",
  },
  projects: [
    {
      name: "chromium",
      use: { ...devices["Desktop Chrome"] },
    },
  ],
});
```

---

## Files to Create

| Path | Description |
|---|---|
| `frontend/e2e/helpers/api.ts` | Direct API helpers for test setup |
| `frontend/e2e/auth/login.spec.ts` | Login page tests |
| `frontend/e2e/auth/setup.spec.ts` | Invitation setup tests |
| `frontend/e2e/auth/password-reset.spec.ts` | Password reset tests |
| `frontend/playwright.config.ts` | Updated Playwright config |

---

## Gate Criteria
- `make e2e` passes all tests in CI with `workers=1`
- Login test verifies redirect to `/chat` after successful authentication
- Invalid email shows inline Zod error without server round-trip
- Invitation setup test completes the full flow including redirect to `/login`
- Password reset "always success" test passes â€” no email enumeration
- All tests pass with `--reporter=github` in CI environment
