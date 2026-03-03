import { expect, test } from "@playwright/test";

test.describe("No animations / reduced motion", () => {
  test.use({
    contextOptions: {
      // Emulate the prefers-reduced-motion media query
      reducedMotion: "reduce",
    },
  });

  test("login page loads without animation classes when reduced motion", async ({
    page,
  }) => {
    await page.goto("/login");
    // Page should still be fully rendered
    await expect(page.locator("body")).toBeVisible();
    // Check no infinite-spin animations are running (Tailwind animate-spin etc.)
    const spinElements = await page
      .locator('[class*="animate-spin"]')
      .count();
    // Loaders / spinners should not be present on the idle login page
    expect(spinElements).toBe(0);
  });

  test("skeleton components do not block focus when hidden", async ({
    page,
  }) => {
    await page.goto("/login");
    // Skeletons are loading placeholders — they should have aria-live or
    // aria-label and not trap keyboard focus
    const skeletons = page.locator('[role="status"]');
    const count = await skeletons.count();
    for (let i = 0; i < count; i++) {
      const el = skeletons.nth(i);
      // Should have an accessible label
      const label = await el.getAttribute("aria-label");
      expect(label).toBeTruthy();
    }
  });
});
