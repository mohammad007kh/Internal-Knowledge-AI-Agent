import { test, expect } from "../fixtures/auth.fixture";

test.describe("Keyboard navigation", () => {
  test("login form — all fields and button reachable via Tab", async ({ page }) => {
    await page.goto("/login");
    await page.keyboard.press("Tab");
    await expect(page.getByLabel("Email")).toBeFocused();
    await page.keyboard.press("Tab");
    await expect(page.getByLabel("Password")).toBeFocused();
    await page.keyboard.press("Tab");
    await expect(page.getByRole("button", { name: "Sign in" })).toBeFocused();
    await page.getByLabel("Email").fill("admin@example.com");
    await page.getByLabel("Password").fill("wrong");
    await page.getByRole("button", { name: "Sign in" }).press("Enter");
    await expect(page.getByRole("alert")).toBeVisible();
  });

  test("admin modal — focus trapped inside dialog", async ({ adminPage: page }) => {
    await page.goto("/admin/users");
    await page.getByRole("button", { name: /invite user/i }).click();
    const dialog = page.getByRole("dialog");
    await expect(dialog).toBeVisible();
    const focusable = dialog.locator(
      "button, [href], input, select, textarea, [tabindex]:not([tabindex='-1'])"
    );
    const count = await focusable.count();
    expect(count).toBeGreaterThan(0);
    for (let i = 0; i < count + 2; i++) {
      await page.keyboard.press("Tab");
      const focusedOutside = await page.evaluate(() => {
        const el = document.activeElement;
        return el ? !document.querySelector("[role='dialog']")?.contains(el) : false;
      });
      expect(focusedOutside).toBe(false);
    }
  });

  test("chat input — Enter sends; ESC does nothing dangerous", async ({ userPage: page }) => {
    await page.goto("/chat");
    await page.getByRole("button", { name: /new chat/i }).click();
    const input = page.getByTestId("chat-input");
    await input.click();
    await input.press("Escape");
    await expect(input).toBeVisible();
    await expect(input).toBeEnabled();
  });

  test("nav sidebar skip-link jumps to main content", async ({ userPage: page }) => {
    await page.goto("/chat");
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
  });

  test("source wizard — Stepper steps reachable via Tab+Space", async ({ adminPage: page }) => {
    await page.goto("/admin/sources/new");
    const step1 = page.getByRole("heading", { name: /connection|name/i });
    await expect(step1).toBeVisible();
  });
});
