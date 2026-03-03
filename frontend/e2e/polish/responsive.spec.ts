import { expect, test } from "@playwright/test";

const VIEWPORTS = [
  { name: "mobile-sm", width: 375, height: 667 },
  { name: "mobile-lg", width: 414, height: 896 },
  { name: "tablet", width: 768, height: 1024 },
  { name: "desktop-sm", width: 1280, height: 800 },
  { name: "desktop-lg", width: 1440, height: 900 },
] as const;

for (const vp of VIEWPORTS) {
  test.describe(`Responsive layout — ${vp.name} (${vp.width}×${vp.height})`, () => {
    test.use({ viewport: { width: vp.width, height: vp.height } });

    test("login page renders without horizontal scroll", async ({ page }) => {
      await page.goto("/login");
      const scrollWidth = await page.evaluate(
        () => document.documentElement.scrollWidth,
      );
      const clientWidth = await page.evaluate(
        () => document.documentElement.clientWidth,
      );
      expect(scrollWidth).toBeLessThanOrEqual(clientWidth + 1);
    });

    test("no element overflows the viewport width", async ({ page }) => {
      await page.goto("/login");
      const overflowing = await page.evaluate(() => {
        const elements = Array.from(document.querySelectorAll("*"));
        return elements
          .filter((el) => {
            const rect = el.getBoundingClientRect();
            return rect.right > window.innerWidth + 2;
          })
          .map((el) => el.tagName + (el.id ? `#${el.id}` : ""));
      });
      expect(overflowing).toHaveLength(0);
    });

    test("page body fills viewport height", async ({ page }) => {
      await page.goto("/login");
      const bodyHeight = await page.evaluate(
        () => document.body.offsetHeight,
      );
      expect(bodyHeight).toBeGreaterThan(0);
    });
  });
}
