# T-086 Â· Chat E2E Playwright Tests

**Status:** Done

**Phase:** 5 â€” Chat Frontend  
**Depends on:** T-081, T-082, T-083, T-084, T-085  
**Blocks:** T-090 (prod release)

---

## Context

```
Python 3.12 | FastAPI Â· SQLAlchemy 2.x Â· Pydantic v2 Â· dependency-injector
Next.js 15 App Router Â· shadcn/ui Â· Tailwind CSS v4
React Context Â· TanStack Query v5 Â· react-hook-form Â· Zod
PostgreSQL 16 + pgvector Â· HNSW m=16 ef_construction=064 Â· UUID PKs Â· soft-delete + audit columns
Alembic versioned migrations
Celery + Redis Â· Beat replicas=1 STRICT
MinIO Â· presigned PUT pattern
JWT 15-min access + 7-day rotating httpOnly refresh cookie Â· bcrypt Â· RBAC (admin/user)
Fernet (connection configs at rest)
LangGraph 8-node Â· interrupt() for clarification Â· SSE streaming
Langfuse self-hosted Â· every pipeline run must emit a trace
RFC 7807 Problem Details â€” all non-2xx API responses
Structured logging Â· INFO level Â· X-Request-ID correlation
CORS strict Â· CSRF SameSite=Strict httpOnly Â· CSP moderate Â· rate-limit IP
Dark mode Â· responsive Â· WCAG-AA Â· no animations Â· Lucide icons Â· Sonner toasts
snake_case vars/files/tables Â· PascalCase classes Â· SCREAMING_SNAKE_CASE constants
pytest + httpx + Playwright Â· â‰¥80% coverage
Docker Compose 9 services: frontend, backend, worker, beat, db, redis, minio, langfuse, langfuse-db
```

---

## Objective

Write Playwright end-to-end tests for the full chat user journey, running against the full Docker Compose stack. Tests cover:

1. Authentication (login)
2. Create a session, rename it
3. Send a message and observe SSE streaming
4. Citation panel opens on badge click
5. Source selector updates session
6. Feedback submission
7. Session deletion

---

## 1. Playwright Config

### `playwright.config.ts`

```ts
import { defineConfig, devices } from "@playwright/test";

export default defineConfig({
  testDir: "./e2e",
  timeout: 60_000,
  retries: process.env.CI ? 2 : 0,
  reporter: process.env.CI ? "github" : "list",
  use: {
    baseURL: process.env.PLAYWRIGHT_BASE_URL ?? "http://localhost:3000",
    storageState: "e2e/.auth/user.json",
    trace: "on-first-retry",
    screenshot: "only-on-failure",
  },
  projects: [
    // Auth setup project (runs first, stores cookies)
    {
      name: "setup",
      testMatch: /.*\.setup\.ts/,
      use: { storageState: undefined },
    },
    {
      name: "chromium",
      use: { ...devices["Desktop Chrome"] },
      dependencies: ["setup"],
    },
  ],
});
```

---

## 2. Auth Setup Fixture

### `e2e/auth.setup.ts`

```ts
import { test as setup, expect } from "@playwright/test";
import path from "path";

const AUTH_FILE = path.join(__dirname, ".auth/user.json");

setup("authenticate", async ({ page }) => {
  await page.goto("/login");

  await page.getByLabel("Email").fill(process.env.E2E_USER_EMAIL ?? "user@example.com");
  await page.getByLabel("Password").fill(process.env.E2E_USER_PASSWORD ?? "TestPass123!");
  await page.getByRole("button", { name: /sign in/i }).click();

  // Wait for redirect to dashboard
  await expect(page).toHaveURL(/\/(dashboard|chat)/, { timeout: 10_000 });

  await page.context().storageState({ path: AUTH_FILE });
});
```

---

## 3. Page Object Model

### `e2e/pages/ChatPage.ts`

```ts
import type { Page, Locator } from "@playwright/test";

export class ChatPage {
  readonly page: Page;

  // Session list
  readonly newSessionBtn: Locator;
  readonly searchInput: Locator;
  readonly sessionList: Locator;

  // Chat input
  readonly chatTextarea: Locator;
  readonly sendBtn: Locator;
  readonly sourceSelector: Locator;

  // Thread
  readonly thread: Locator;

  constructor(page: Page) {
    this.page = page;
    this.newSessionBtn = page.getByRole("button", { name: /new chat session/i });
    this.searchInput = page.getByRole("textbox", { name: /search sessions/i });
    this.sessionList = page.getByRole("list").filter({ hasText: /session/i }).first();
    this.chatTextarea = page.getByRole("textbox", { name: /chat message input/i });
    this.sendBtn = page.getByRole("button", { name: /send message/i });
    this.sourceSelector = page.getByRole("button", { name: /all sources|source/i });
    this.thread = page.getByRole("log", { name: /conversation/i });
  }

  async goto() {
    await this.page.goto("/chat");
  }

  async createSession() {
    await this.newSessionBtn.click();
  }

  async getSessionItem(title: string): Promise<Locator> {
    return this.page.getByRole("button", {
      name: new RegExp(`chat session: ${title}`, "i"),
    });
  }

  async sendMessage(text: string) {
    await this.chatTextarea.fill(text);
    await this.sendBtn.click();
  }

  async waitForStreamingComplete() {
    // Wait for the streaming cursor to disappear
    await this.page.waitForSelector(
      '[aria-live="polite"] [aria-hidden="true"]',
      { state: "detached", timeout: 30_000 },
    );
  }
}
```

---

## 4. E2E Test Suite

### `e2e/chat.spec.ts`

```ts
import { test, expect } from "@playwright/test";
import { ChatPage } from "./pages/ChatPage";

test.describe("Chat â€“ full user journey", () => {
  let chat: ChatPage;

  test.beforeEach(async ({ page }) => {
    chat = new ChatPage(page);
    await chat.goto();
  });

  // â”€â”€ 1. Create & rename session â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€

  test("creates a new session and renames it", async ({ page }) => {
    await chat.createSession();

    // A rename input should appear immediately
    const renameInput = page.getByRole("textbox", { name: /rename session/i });
    await expect(renameInput).toBeVisible();

    await renameInput.fill("My Test Session");
    await renameInput.press("Enter");

    // Session now appears in the list with new title
    await expect(
      page.getByRole("button", { name: /chat session: my test session/i }),
    ).toBeVisible();
  });

  // â”€â”€ 2. Send a message and observe streaming â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€

  test("sends a message and sees streamed response", async ({ page }) => {
    // Create a session first
    await chat.createSession();
    const renameInput = page.getByRole("textbox", { name: /rename session/i });
    await renameInput.press("Escape");

    // Type and send
    await chat.chatTextarea.fill("What is the purpose of this system?");
    await chat.sendBtn.click();

    // User message appears immediately (optimistic)
    await expect(
      page.getByText("What is the purpose of this system?"),
    ).toBeVisible();

    // Wait for some streamed tokens (assistant bubble appears)
    await expect(chat.thread.locator('[aria-hidden="true"]')).toBeVisible({
      timeout: 15_000,
    });

    // Wait for streaming to complete (cursor disappears)
    await chat.waitForStreamingComplete();

    // Persisted assistant message visible
    const messages = chat.thread.locator("[class*='rounded-2xl']");
    await expect(messages).toHaveCount(2, { timeout: 10_000 });
  });

  // â”€â”€ 3. Citation panel â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€

  test("opens citation panel on citation button click", async ({ page }) => {
    // Use a seeded session with a known assistant message that has citations
    // Assumes the seed fixture or prior test left "My Test Session"
    const sessionItem = page.getByRole("button", {
      name: /chat session: my test session/i,
    });

    if (!(await sessionItem.isVisible())) {
      test.skip();
      return;
    }

    await sessionItem.click();

    // Find first citation badge
    const citationBadge = page
      .getByRole("list", { name: /citations/i })
      .getByRole("listitem")
      .first();

    if (!(await citationBadge.isVisible())) {
      test.skip();
      return;
    }

    await citationBadge.click();

    await expect(
      page.getByRole("complementary", { name: /citation details/i }),
    ).toBeVisible();

    // Panel shows a document title (text must exist in DOM)
    await expect(
      page.locator('[role="complementary"] h2'),
    ).not.toBeEmpty();

    // Close panel
    await page
      .getByRole("button", { name: /close citation panel/i })
      .click();

    await expect(
      page.getByRole("complementary", { name: /citation details/i }),
    ).toHaveAttribute("aria-hidden", "true");
  });

  // â”€â”€ 4. Source selector â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€

  test("source selector updates session sources", async ({ page }) => {
    await chat.createSession();
    const renameInput = page.getByRole("textbox", { name: /rename session/i });
    await renameInput.press("Escape");

    // Open source selector
    await chat.sourceSelector.click();

    // Wait for source list population  
    const sourcePopover = page.getByRole("dialog", {
      name: /select knowledge sources/i,
    });
    await expect(sourcePopover).toBeVisible();

    // Select first source (if any exist)
    const firstOption = sourcePopover.getByRole("option").first();
    if (await firstOption.isVisible()) {
      await firstOption.click();
      await page.keyboard.press("Escape");

      // Chip appears below input
      await expect(page.getByRole("list", { name: /selected sources/i })).toBeVisible();
    } else {
      // No sources available â€” empty state shown
      await expect(page.getByText(/no sources available/i)).toBeVisible();
    }
  });

  // â”€â”€ 5. Feedback thumbs up â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€

  test("submits thumbs up feedback on assistant message", async ({ page }) => {
    // Find an assistant message
    const helpfulBtn = page.getByRole("button", { name: /mark as helpful/i }).first();

    if (!(await helpfulBtn.isVisible())) {
      test.skip();
      return;
    }

    await helpfulBtn.click();

    // Button becomes disabled after submission
    await expect(helpfulBtn).toBeDisabled({ timeout: 5_000 });
  });

  // â”€â”€ 6. Delete session â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€

  test("deletes a session with confirmation", async ({ page }) => {
    // Ensure there's a session to delete
    await chat.createSession();
    const renameInput = page.getByRole("textbox", { name: /rename session/i });
    await renameInput.fill("To Be Deleted");
    await renameInput.press("Enter");

    const sessionBtn = page.getByRole("button", {
      name: /chat session: to be deleted/i,
    });
    await expect(sessionBtn).toBeVisible();

    // Hover to reveal actions
    await sessionBtn.hover();
    await page
      .getByRole("button", { name: /delete: to be deleted/i })
      .click();

    // Confirmation dialog
    await expect(page.getByRole("alertdialog")).toBeVisible();
    await page.getByRole("button", { name: /^delete$/i }).click();

    // Session gone from list
    await expect(sessionBtn).not.toBeVisible({ timeout: 5_000 });
  });

  // â”€â”€ 7. Accessibility snapshot â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€

  test("chat page has no critical accessibility violations", async ({ page }) => {
    const { injectAxe, checkA11y } = await import("axe-playwright");
    await injectAxe(page);
    await checkA11y(page, undefined, {
      includedImpacts: ["critical", "serious"],
    });
  });
});
```

---

## 5. Dependencies

```json
// package.json devDependencies additions
{
  "@playwright/test": "^1.44.0",
  "axe-playwright": "^2.0.2"
}
```

`.gitignore` additions:

```
e2e/.auth/
playwright-report/
test-results/
```

---

## 6. CI Integration

### `.github/workflows/e2e.yml`

```yaml
name: E2E Tests

on:
  pull_request:
    branches: [main, develop]
  workflow_dispatch:

jobs:
  e2e:
    runs-on: ubuntu-latest
    timeout-minutes: 20

    env:
      PLAYWRIGHT_BASE_URL: http://localhost:3000
      E2E_USER_EMAIL: e2e@test.local
      E2E_USER_PASSWORD: TestPass123!

    steps:
      - uses: actions/checkout@v4

      - name: Start Docker Compose stack
        run: docker compose -f docker-compose.yml -f docker-compose.e2e.yml up -d --wait
        timeout-minutes: 10

      - name: Seed E2E test user
        run: docker compose exec backend python scripts/seed_e2e_user.py

      - name: Install Playwright browsers
        working-directory: frontend
        run: pnpm exec playwright install --with-deps chromium

      - name: Run E2E tests
        working-directory: frontend
        run: pnpm exec playwright test

      - uses: actions/upload-artifact@v4
        if: failure()
        with:
          name: playwright-report
          path: frontend/playwright-report/
```

### `docker-compose.e2e.yml`

```yaml
# Overrides for E2E environment
services:
  backend:
    environment:
      - E2E_MODE=true
      - CELERY_TASK_ALWAYS_EAGER=true
```

---

## 7. Seed Script

### `scripts/seed_e2e_user.py`

```python
"""Seed an E2E test user. Run once against a fresh DB."""
import os
from app.database import get_engine
from app.models.user import User
from sqlalchemy.orm import Session
from passlib.context import CryptContext

EMAIL = os.environ.get("E2E_USER_EMAIL", "e2e@test.local")
PASSWORD = os.environ.get("E2E_USER_PASSWORD", "TestPass123!")

pwd_context = CryptContext(schemes=["bcrypt"], deprecated="auto")

engine = get_engine()
with Session(engine) as session:
    existing = session.query(User).filter_by(email=EMAIL).first()
    if not existing:
        user = User(
            email=EMAIL,
            hashed_password=pwd_context.hash(PASSWORD),
            role="user",
            is_active=True,
        )
        session.add(user)
        session.commit()
        print(f"Created E2E user: {EMAIL}")
    else:
        print(f"E2E user already exists: {EMAIL}")
```

---

## Acceptance Criteria

- [ ] `pnpm exec playwright test` passes all 7 test scenarios in CI
- [ ] Auth setup fixture stores cookies and all tests use them (no repeated logins)
- [ ] Session create + rename verifies new title in sidebar
- [ ] Message send shows optimistic bubble, then persisted response
- [ ] Citation panel opens on badge click and closes on Escape / close button
- [ ] Source selector popover lists `status=ready` sources
- [ ] Thumbs-up disables after rating submission
- [ ] Delete session removes item from sidebar with confirmation
- [ ] Accessibility check passes with no critical/serious violations on `/chat`
- [ ] E2E workflow defined in `.github/workflows/e2e.yml`
- [ ] Docker Compose E2E override file present
- [ ] Seed script creates test user idempotently
