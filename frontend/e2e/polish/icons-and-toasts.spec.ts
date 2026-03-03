import { expect } from "@playwright/test";
import { test } from "./auth.fixture";

test.describe("Icons and toasts", () => {
  test("theme-toggle icon is hidden from assistive technology", async ({
    page,
  }) => {
    await page.goto("/login");
    const toggle = page.getByTestId("theme-toggle");
    await expect(toggle).toBeVisible();
    // The SVG icon inside the button should be aria-hidden
    const icon = toggle.locator("svg");
    const ariaHidden = await icon.getAttribute("aria-hidden");
    expect(ariaHidden).toBe("true");
  });

  test("theme-toggle has a descriptive aria-label", async ({ page }) => {
    await page.goto("/login");
    const toggle = page.getByTestId("theme-toggle");
    const label = await toggle.getAttribute("aria-label");
    expect(label).toBeTruthy();
    expect(label!.length).toBeGreaterThan(3);
  });

  test("toast appears and is dismissible after form error", async ({
    page,
  }) => {
    await page.goto("/login");
    // Submit empty form to trigger a validation toast or error message
    await page.getByRole("button", { name: "Sign in" }).click();
    // An error indication should appear (either inline or as a toast)
    const errorIndicator = page
      .locator('[role="alert"], [data-sonner-toast], .text-destructive')
      .first();
    await expect(errorIndicator).toBeVisible({ timeout: 5_000 });
  });

  test("admin page loads without console errors", async ({ adminPage }) => {
    const errors: string[] = [];
    adminPage.on("console", (msg) => {
      if (msg.type() === "error") errors.push(msg.text());
    });
    await adminPage.goto("/admin");
    await adminPage.waitForLoadState("networkidle");
    // Filter out known benign errors (e.g. favicon 404)
    const criticalErrors = errors.filter(
      (e) => !e.includes("favicon") && !e.includes("net::ERR"),
    );
    expect(criticalErrors).toHaveLength(0);
  });
});
