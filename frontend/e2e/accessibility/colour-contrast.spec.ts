import { test, expect } from "../fixtures/auth.fixture";
import AxeBuilder from "@axe-core/playwright";

const PAGES = [
  { path: "/login", auth: null },
  { path: "/chat", auth: "user" },
  { path: "/admin", auth: "admin" },
] as const;

async function setTheme(page: import("@playwright/test").Page, theme: "light" | "dark") {
  const currentHtml = (await page.locator("html").getAttribute("class")) ?? "";
  const inDark = currentHtml.includes("dark");
  if ((theme === "dark" && !inDark) || (theme === "light" && inDark)) {
    await page.getByRole("button", { name: /toggle theme|dark mode|light mode/i }).click();
    await page.waitForTimeout(200);
  }
}

for (const { path, auth } of PAGES) {
  for (const theme of ["light", "dark"] as const) {
    test(`contrast: ${path} in ${theme} mode — no violation`, async ({ page, browser }) => {
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
            .map(
              (v) =>
                `${v.id}: ${v.nodes.map((n) => n.html.slice(0, 100)).join("; ")}`
            )
            .join("\n");
          throw new Error(`Colour-contrast violations on ${path} (${theme}):\n${detail}`);
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
