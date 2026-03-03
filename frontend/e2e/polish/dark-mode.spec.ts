import { expect, test } from "@playwright/test";

test.describe("Dark mode", () => {
  test("html element gets .dark class when dark theme set", async ({
    page,
  }) => {
    await page.goto("/");
    // Force dark mode via localStorage / next-themes mechanism
    await page.evaluate(() => {
      localStorage.setItem("theme", "dark");
    });
    await page.reload();
    await expect(page.locator("html")).toHaveClass(/dark/);
  });

  test("html element does NOT have .dark class in light theme", async ({
    page,
  }) => {
    await page.goto("/");
    await page.evaluate(() => {
      localStorage.setItem("theme", "light");
    });
    await page.reload();
    const htmlClass = await page.locator("html").getAttribute("class");
    expect(htmlClass ?? "").not.toContain("dark");
  });

  test("theme-toggle button is present on page", async ({ page }) => {
    await page.goto("/login");
    await expect(page.getByTestId("theme-toggle")).toBeVisible();
  });

  test("no CSS transition attribute on html element after toggle", async ({
    page,
  }) => {
    await page.goto("/login");
    await page.evaluate(() => {
      localStorage.setItem("theme", "light");
    });
    await page.reload();
    const toggle = page.getByTestId("theme-toggle");
    await toggle.click();
    // disableTransitionOnChange means next-themes briefly adds and removes
    // a style tag — but the html element itself should never get a
    // `style="transition: none"` permanently attached.
    const style = await page.locator("html").getAttribute("style");
    // After the click settles the inline style should be empty / null
    expect(style ?? "").not.toMatch(/transition/);
  });
});
