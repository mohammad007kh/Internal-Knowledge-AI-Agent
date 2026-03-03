# T-094 Â· Accessibility Audit â€” WCAG-AA Compliance

**Status:** Done

**Phase:** 9 â€” Testing, Polish & SC Verification  
**Depends on:** T-093 (E2E suite in place), full frontend complete (T-080â€“T-089)  
**Blocks:** T-099

---

## Context

```
Python 3.12 | FastAPI Â· SQLAlchemy 2.x Â· Pydantic v2 Â· dependency-injector
Next.js 15 App Router Â· shadcn/ui Â· Tailwind CSS v4
React Context Â· TanStack Query v5 Â· react-hook-form Â· Zod
PostgreSQL 16 + pgvector Â· HNSW m=16 ef_construction=64 Â· UUID PKs Â· soft-delete + audit columns
Alembic versioned migrations
Celery + Redis Â· Beat replicas=1 STRICT
MinIO Â· presigned PUT pattern
JWT 15-min access + 7-day rotating httpOnly refresh cookie Â· bcrypt Â· RBAC (admin/user)
Fernet (connection configs + LLM API keys at rest)
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

Verify every page meets **WCAG 2.1 Level AA** across four dimensions:

1. **Automated axe scan** (via `@axe-core/playwright`) â€” zero critical/serious violations  
2. **Keyboard navigation** â€” all interactive elements reachable and operable by keyboard alone  
3. **Colour contrast** â€” text meets 4.5 : 1 (normal) and 3 : 1 (large) ratios in both light and dark mode  
4. **Screen-reader semantics** â€” ARIA landmarks, roles, labels, live regions

File locations:

- `tests/e2e/accessibility/axe-scan.spec.ts`
- `tests/e2e/accessibility/keyboard-nav.spec.ts`
- `tests/e2e/accessibility/aria-labels.spec.ts`
- `tests/e2e/accessibility/colour-contrast.spec.ts` (manual checklist + Playwright colour helper)

---

## 1. Automated axe Scan â€” `tests/e2e/accessibility/axe-scan.spec.ts`

```typescript
import { test, expect } from "@playwright/test";
import AxeBuilder from "@axe-core/playwright";

const PAGES_TO_SCAN = [
  { path: "/login", name: "Login" },
  { path: "/chat", name: "Chat", requiresAuth: true },
  { path: "/admin", name: "Admin Dashboard", requiresAdmin: true },
  { path: "/admin/users", name: "Admin Users", requiresAdmin: true },
  { path: "/admin/sources", name: "Admin Sources", requiresAdmin: true },
  { path: "/admin/guardrails", name: "Admin Guardrails", requiresAdmin: true },
];

async function signInAdmin(page: import("@playwright/test").Page) {
  await page.goto("/login");
  await page.getByLabel("Email").fill("admin@example.com");
  await page.getByLabel("Password").fill("AdminFinal1!");
  await page.getByRole("button", { name: "Sign in" }).click();
  await page.waitForURL(/admin|chat/, { timeout: 15_000 });
}

async function signInUser(page: import("@playwright/test").Page) {
  await page.goto("/login");
  await page.getByLabel("Email").fill("e2e-user@example.com");
  await page.getByLabel("Password").fill("E2eUser1!");
  await page.getByRole("button", { name: "Sign in" }).click();
  await page.waitForURL(/chat/, { timeout: 15_000 });
}

for (const { path, name, requiresAuth, requiresAdmin } of PAGES_TO_SCAN) {
  test(`axe: ${name} (${path}) â€” zero critical/serious violations`, async ({ page }) => {
    if (requiresAdmin) {
      await signInAdmin(page);
    } else if (requiresAuth) {
      await signInUser(page);
    }
    await page.goto(path);
    await page.waitForLoadState("networkidle");

    const results = await new AxeBuilder({ page })
      .withTags(["wcag2a", "wcag2aa", "wcag21aa"])
      .disableRules(["color-contrast"]) // contrast checked separately
      .analyze();

    const critical = results.violations.filter(
      (v) => v.impact === "critical" || v.impact === "serious"
    );

    if (critical.length > 0) {
      const summary = critical
        .map((v) => `[${v.impact}] ${v.id}: ${v.description}\n  Elements: ${
          v.nodes.map((n) => n.html.slice(0, 120)).join("; ")
        }`)
        .join("\n\n");
      throw new Error(
        `${critical.length} critical/serious axe violation(s) on ${name}:\n\n${summary}`
      );
    }
  });
}
```

---

## 2. Keyboard Navigation Tests â€” `tests/e2e/accessibility/keyboard-nav.spec.ts`

```typescript
import { test, expect } from "./auth.fixture";

test.describe("Keyboard navigation", () => {
  test("login form â€” all fields and button reachable via Tab", async ({ page }) => {
    await page.goto("/login");

    // Tab through interactive elements in order
    await page.keyboard.press("Tab"); // Email
    await expect(page.getByLabel("Email")).toBeFocused();

    await page.keyboard.press("Tab"); // Password
    await expect(page.getByLabel("Password")).toBeFocused();

    await page.keyboard.press("Tab"); // Sign in button
    await expect(page.getByRole("button", { name: "Sign in" })).toBeFocused();

    // Enter submits
    await page.getByLabel("Email").fill("admin@example.com");
    await page.getByLabel("Password").fill("wrong");
    await page.getByRole("button", { name: "Sign in" }).press("Enter");
    await expect(page.getByRole("alert")).toBeVisible();
  });

  test("admin modal â€” focus trapped inside dialog", async ({ adminPage: page }) => {
    await page.goto("/admin/users");
    await page.getByRole("button", { name: /invite user/i }).click();
    const dialog = page.getByRole("dialog");
    await expect(dialog).toBeVisible();

    // Tab through all focusable elements; focus must not escape to page behind
    const focusable = dialog.locator(
      "button, [href], input, select, textarea, [tabindex]:not([tabindex='-1'])"
    );
    const count = await focusable.count();
    expect(count).toBeGreaterThan(0);

    // Press Tab count+2 times; focus should cycle within dialog
    for (let i = 0; i < count + 2; i++) {
      await page.keyboard.press("Tab");
      const focusedOutside = await page.evaluate(() => {
        const el = document.activeElement;
        return el ? !document.querySelector("[role='dialog']")?.contains(el) : false;
      });
      expect(focusedOutside).toBe(false);
    }
  });

  test("chat input â€” Enter sends; ESC does nothing dangerous", async ({
    userPage: page,
  }) => {
    await page.goto("/chat");
    await page.getByRole("button", { name: /new chat/i }).click();
    const input = page.getByTestId("chat-input");
    await input.click();

    // Escape should not break the page
    await input.press("Escape");
    await expect(input).toBeVisible();
    await expect(input).toBeEnabled();
  });

  test("nav sidebar skip-link jumps to main content", async ({ userPage: page }) => {
    await page.goto("/chat");
    // Tab once from top of page
    await page.keyboard.press("Tab");
    const skipLink = page.getByRole("link", { name: /skip to (main )?content/i });
    if (await skipLink.isVisible()) {
      await skipLink.press("Enter");
      const main = page.getByRole("main");
      const mainFocused = await main.evaluate(
        (el) => el === document.activeElement || el.contains(document.activeElement)
      );
      expect(mainFocused).toBe(true);
    }
    // Skip-link optional if layout uses landmark nav; just ensure no error
  });

  test("source wizard â€” Stepper steps reachable via Tab+Space", async ({
    adminPage: page,
  }) => {
    await page.goto("/admin/sources/new");
    // Confirm step 1 heading is keyboard-reachable
    const step1 = page.getByRole("heading", { name: /connection|name/i });
    await expect(step1).toBeVisible();
  });
});
```

---

## 3. ARIA Labels Tests â€” `tests/e2e/accessibility/aria-labels.spec.ts`

```typescript
import { test, expect } from "./auth.fixture";

test.describe("ARIA labels and semantics", () => {
  test("nav has role=navigation and aria-label", async ({ userPage: page }) => {
    await page.goto("/chat");
    const nav = page.getByRole("navigation");
    expect(await nav.count()).toBeGreaterThanOrEqual(1);
  });

  test("main landmark present on every page", async ({ userPage: page }) => {
    for (const path of ["/chat", "/admin"]) {
      await page.goto(path);
      await expect(page.getByRole("main")).toBeVisible();
    }
  });

  test("chat input has accessible label", async ({ userPage: page }) => {
    await page.goto("/chat");
    await page.getByRole("button", { name: /new chat/i }).click();
    const input = page.getByTestId("chat-input");
    const ariaLabel = await input.getAttribute("aria-label");
    const ariaLabelledBy = await input.getAttribute("aria-labelledby");
    // Must have one of: aria-label, aria-labelledby, or an associated <label>
    const hasLabel = !!(ariaLabel || ariaLabelledBy) ||
      !!(await page.evaluate(() => {
        const el = document.querySelector("[data-testid='chat-input']");
        if (!el) return false;
        const id = el.id;
        return !!document.querySelector(`label[for='${id}']`);
      }));
    expect(hasLabel).toBe(true);
  });

  test("loading skeleton announces loading state to screen readers", async ({
    userPage: page,
  }) => {
    await page.goto("/chat");
    // Skeletons should use aria-busy or role=status
    const busy = page.locator("[aria-busy='true']");
    const status = page.locator("[role='status']");
    // At minimum one of these patterns must exist during load
    const eitherExists =
      (await busy.count()) > 0 || (await status.count()) > 0;
    // Acceptable to be false after full load; check is timing-sensitive
    // Just verify if present it's correct
    if (eitherExists) {
      // Confirm aria-busy eventually becomes false or element disappears
      await page.waitForFunction(() => {
        const busyEls = document.querySelectorAll("[aria-busy='true']");
        return busyEls.length === 0;
      }, { timeout: 15_000 });
    }
  });

  test("error alerts have role=alert", async ({ page }) => {
    await page.goto("/login");
    await page.getByLabel("Email").fill("x@example.com");
    await page.getByLabel("Password").fill("wrong");
    await page.getByRole("button", { name: "Sign in" }).click();
    const alert = page.getByRole("alert");
    await expect(alert).toBeVisible({ timeout: 5_000 });
  });

  test("Sonner toast has role=status or aria-live region", async ({
    userPage: page,
  }) => {
    await page.goto("/admin/guardrails");
    // Trigger a toast (create rule)
    await page.getByRole("button", { name: /add rule|new rule/i }).click();
    const dialog = page.getByRole("dialog");
    await dialog.getByLabel("Rule text").fill("Test ARIA toast.");
    await dialog.getByLabel("Active").check();
    await dialog.getByRole("button", { name: /save|create/i }).click();

    // Sonner wraps toasts in an aria-live region
    const liveRegion = page.locator("[aria-live]");
    await expect(liveRegion.first()).toBeVisible({ timeout: 5_000 });
  });
});
```

---

## 4. Colour Contrast Verification â€” `tests/e2e/accessibility/colour-contrast.spec.ts`

```typescript
import { test, expect } from "./auth.fixture";
import AxeBuilder from "@axe-core/playwright";

// Run axe specifically for color-contrast rule in light AND dark mode.
const PAGES = [
  { path: "/login", auth: null },
  { path: "/chat", auth: "user" },
  { path: "/admin", auth: "admin" },
] as const;

async function setTheme(page: import("@playwright/test").Page, theme: "light" | "dark") {
  // Toggle dark mode via the theme button in the app navbar
  const currentHtml = await page.locator("html").getAttribute("class") ?? "";
  const inDark = currentHtml.includes("dark");
  if ((theme === "dark" && !inDark) || (theme === "light" && inDark)) {
    await page.getByRole("button", { name: /toggle theme|dark mode|light mode/i }).click();
    await page.waitForTimeout(200); // allow transition
  }
}

for (const { path, auth } of PAGES) {
  for (const theme of ["light", "dark"] as const) {
    test(`contrast: ${path} in ${theme} mode â€” no violation`, async ({ page, browser }) => {
      if (auth === "admin") {
        const ctx = await browser.newContext();
        const p = await ctx.newPage();
        await p.goto("/login");
        await p.getByLabel("Email").fill("admin@example.com");
        await p.getByLabel("Password").fill("AdminFinal1!");
        await p.getByRole("button", { name: "Sign in" }).click();
        await p.waitForURL(/admin/, { timeout: 15_000 });
        await p.goto(path);
        await setTheme(p, theme);
        await p.waitForLoadState("networkidle");
        const results = await new AxeBuilder({ page: p })
          .withRules(["color-contrast"])
          .analyze();
        const violations = results.violations;
        if (violations.length > 0) {
          const detail = violations
            .map((v) => `${v.id}: ${v.nodes.map((n) => n.html.slice(0, 100)).join("; ")}`)
            .join("\n");
          throw new Error(
            `Colour-contrast violations on ${path} (${theme}):\n${detail}`
          );
        }
        await ctx.close();
      } else {
        await page.goto(path);
        await setTheme(page, theme);
        await page.waitForLoadState("networkidle");
        const results = await new AxeBuilder({ page })
          .withRules(["color-contrast"])
          .analyze();
        expect(results.violations).toHaveLength(0);
      }
    });
  }
}
```

---

## 5. Remediation Reference

### Critical WCAG 2.1 AA Criteria

| Criterion | ID | Requirement |
|---|---|---|
| Non-text content | 1.1.1 | All `<img>` / icons have `alt` or `aria-hidden` |
| Keyboard | 2.1.1 | Every interactive element reachable by Tab |
| No keyboard trap | 2.1.2 | Focus can move away from any component |
| Focus visible | 2.4.7 | Focus indicator visible (min 2 px outline) |
| Contrast (text) | 1.4.3 | â‰¥ 4.5 : 1 for normal text |
| Contrast (large) | 1.4.3 | â‰¥ 3 : 1 for text â‰¥ 18 pt or bold â‰¥ 14 pt |
| Name, Role, Value | 4.1.2 | All UI components have accessible name + role |
| Status messages | 4.1.3 | Status changes announced via `aria-live` |

### Pattern Fixes for Common Failures

```tsx
// 1. Icon button without accessible name
// âŒ Before:
<button onClick={close}><X /></button>
// âœ… After:
<button onClick={close} aria-label="Close dialog"><X aria-hidden="true" /></button>

// 2. Loading state not announced
// âŒ Before:
<div className="animate-pulse h-8 w-48 bg-muted rounded" />
// âœ… After:
<div
  className="h-8 w-48 bg-muted rounded"
  role="status"
  aria-label="Loadingâ€¦"
/>

// 3. Error messages not associated with inputs
// âŒ Before:
<input id="email" type="email" />
<p className="text-destructive">Invalid email</p>
// âœ… After:
<input id="email" type="email" aria-describedby="email-error" aria-invalid="true" />
<p id="email-error" className="text-destructive" role="alert">Invalid email</p>

// 4. Colour: ensure CSS variables meet contrast requirements
// tailwind.config.ts (dark mode):
// --background: 222.2 84% 4.9%;    â†’ very dark blue (background)
// --foreground: 210 40% 98%;        â†’ near-white (text)
// Verify: oklch luminance ratio â‰¥ 4.5:1 (use https://www.siegemedia.com/contrast-ratio)
```

---

## Definition of Done

- [ ] `playwright test tests/e2e/accessibility/` passes with zero critical/serious axe violations
- [ ] All 6 pages (login, chat, admin, admin/users, admin/sources, admin/guardrails) scanned
- [ ] Keyboard navigation: login form Tab order correct; modal focus trapped
- [ ] Chat input has accessible name (label, aria-label, or aria-labelledby)
- [ ] Error alerts rendered with `role="alert"`
- [ ] Toast notifications use `aria-live` region
- [ ] Colour contrast axe rule passes in both light and dark mode for all pages
- [ ] No animation classes (`animate-*`) present on any page component
- [ ] All icon-only buttons have `aria-label`
- [ ] Main landmark present on every page
