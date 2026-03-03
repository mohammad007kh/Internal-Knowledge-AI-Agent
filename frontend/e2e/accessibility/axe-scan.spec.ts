import { test } from "@playwright/test";
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
  test(`axe: ${name} (${path}) — zero critical/serious violations`, async ({ page }) => {
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
        .map(
          (v) =>
            `[${v.impact}] ${v.id}: ${v.description}\n  Elements: ${v.nodes
              .map((n) => n.html.slice(0, 120))
              .join("; ")}`
        )
        .join("\n\n");
      throw new Error(
        `${critical.length} critical/serious axe violation(s) on ${name}:\n\n${summary}`
      );
    }
  });
}
