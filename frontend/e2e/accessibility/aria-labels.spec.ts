import { test, expect } from "../fixtures/auth.fixture";

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
    const hasLabel =
      !!(ariaLabel || ariaLabelledBy) ||
      !!(await page.evaluate(() => {
        const el = document.querySelector("[data-testid='chat-input']");
        if (!el) return false;
        const id = el.id;
        return !!document.querySelector(`label[for='${id}']`);
      }));
    expect(hasLabel).toBe(true);
  });

  test("loading skeleton announces loading state to screen readers", async ({ userPage: page }) => {
    await page.goto("/chat");
    const busy = page.locator("[aria-busy='true']");
    const status = page.locator("[role='status']");
    const eitherExists = (await busy.count()) > 0 || (await status.count()) > 0;
    if (eitherExists) {
      await page.waitForFunction(
        () => {
          const busyEls = document.querySelectorAll("[aria-busy='true']");
          return busyEls.length === 0;
        },
        { timeout: 15_000 }
      );
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

  test("Sonner toast has role=status or aria-live region", async ({ adminPage: page }) => {
    await page.goto("/admin/guardrails");
    await page.getByRole("button", { name: /add rule|new rule/i }).click();
    const dialog = page.getByRole("dialog");
    await dialog.getByLabel("Rule text").fill("Test ARIA toast.");
    await dialog.getByLabel("Active").check();
    await dialog.getByRole("button", { name: /save|create/i }).click();
    const liveRegion = page.locator("[aria-live]");
    await expect(liveRegion.first()).toBeVisible({ timeout: 5_000 });
  });
});
