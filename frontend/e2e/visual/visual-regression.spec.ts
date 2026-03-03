import { expect, test } from "@playwright/test";

test.describe("Visual regression", () => {
  test("login page – light mode", async ({ page }) => {
    await page.emulateMedia({ colorScheme: "light" });
    await page.addInitScript(() => localStorage.setItem("theme", "light"));
    await page.goto("/login");
    await page.waitForLoadState("networkidle");
    await expect(page).toHaveScreenshot("login-light.png", { fullPage: true });
  });

  test("login page – dark mode", async ({ page }) => {
    await page.emulateMedia({ colorScheme: "dark" });
    await page.addInitScript(() => localStorage.setItem("theme", "dark"));
    await page.goto("/login");
    await page.waitForLoadState("networkidle");
    await expect(page).toHaveScreenshot("login-dark.png", { fullPage: true });
  });

  test("theme-toggle button – light", async ({ page }) => {
    await page.emulateMedia({ colorScheme: "light" });
    await page.addInitScript(() => localStorage.setItem("theme", "light"));
    await page.goto("/login");
    await page.waitForLoadState("networkidle");
    const toggle = page.getByTestId("theme-toggle");
    await expect(toggle).toBeVisible();
    await expect(toggle).toHaveScreenshot("theme-toggle-light.png");
  });

  test("theme-toggle button – dark", async ({ page }) => {
    await page.emulateMedia({ colorScheme: "dark" });
    await page.addInitScript(() => localStorage.setItem("theme", "dark"));
    await page.goto("/login");
    await page.waitForLoadState("networkidle");
    const toggle = page.getByTestId("theme-toggle");
    await expect(toggle).toBeVisible();
    await expect(toggle).toHaveScreenshot("theme-toggle-dark.png");
  });
});
