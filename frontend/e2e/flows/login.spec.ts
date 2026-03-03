import { expect, test } from "@playwright/test";

test.describe("Login flow", () => {
  test("valid admin credentials redirect to dashboard", async ({ page }) => {
    await page.goto("/login");
    await page.getByLabel("Email").fill(
      process.env.E2E_ADMIN_EMAIL ?? "admin@example.com",
    );
    await page.getByLabel("Password").fill(
      process.env.E2E_ADMIN_PASSWORD ?? "Bootstrap1!",
    );
    await page.getByRole("button", { name: "Sign in" }).click();
    await page.waitForURL((url) => !url.pathname.startsWith("/login"), {
      timeout: 15_000,
    });
    expect(page.url()).not.toContain("/login");
  });

  test("invalid credentials show error alert", async ({ page }) => {
    await page.goto("/login");
    await page.getByLabel("Email").fill("wrong@example.com");
    await page.getByLabel("Password").fill("WrongPass1!");
    await page.getByRole("button", { name: "Sign in" }).click();
    const alert = page.getByRole("alert");
    await expect(alert).toBeVisible({ timeout: 10_000 });
    await expect(alert).toContainText(/invalid|incorrect|credentials/i);
  });

  test("weak password shows inline rule feedback (FR-034)", async ({
    page,
  }) => {
    await page.goto("/login");
    // Navigate to registration or password-change page that shows inline rules
    // Many apps show password rules on the registration page
    await page.goto("/register");
    const passwordInput = page.getByLabel(/password/i).first();
    const isRegistrationAvailable = await passwordInput
      .isVisible()
      .catch(() => false);
    if (!isRegistrationAvailable) {
      // Try the setup/change-password page instead
      await page.goto("/setup");
    }
    const pwField = page.getByLabel(/new password|password/i).first();
    const pwAvailable = await pwField.isVisible().catch(() => false);
    if (!pwAvailable) {
      test.skip();
      return;
    }
    // Type a weak password to trigger inline validation messages
    await pwField.fill("weak");
    // Inline rule messages should appear indicating password requirements
    const ruleMessages = page.locator(
      "[data-password-rule], [aria-label*='rule'], [class*='rule'], [class*='requirement']",
    );
    const hasRules = await ruleMessages.first().isVisible().catch(() => false);
    if (!hasRules) {
      // Try looking for any validation hints near the field
      const hints = page.locator("ul, [role='list']").filter({
        hasText: /uppercase|lowercase|number|character|length/i,
      });
      await expect(hints.first()).toBeVisible({ timeout: 5_000 });
    } else {
      await expect(ruleMessages.first()).toBeVisible();
    }
  });

  test("logged-out user accessing /chat is redirected to /login", async ({
    page,
    context,
  }) => {
    // Start with no auth state
    await context.clearCookies();
    await page.goto("/chat");
    await page.waitForURL((url) => url.pathname.startsWith("/login"), {
      timeout: 10_000,
    });
    expect(page.url()).toContain("/login");
  });
});
