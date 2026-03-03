import { test as base, type Page } from "@playwright/test";

const ADMIN_EMAIL = process.env.E2E_ADMIN_EMAIL ?? "admin@example.com";
const ADMIN_PASSWORD = process.env.E2E_ADMIN_PASSWORD ?? "Bootstrap1!";

async function loginAs(page: Page, email: string, password: string) {
  await page.goto("/login");
  await page.getByLabel("Email").fill(email);
  await page.getByLabel("Password").fill(password);
  await page.getByRole("button", { name: "Sign in" }).click();
  await page.waitForURL(
    (url) => !url.pathname.startsWith("/login"),
    { timeout: 15_000 },
  );
}

export const test = base.extend<{ adminPage: Page; userPage: Page }>({
  adminPage: async ({ browser }, use) => {
    const context = await browser.newContext();
    const page = await context.newPage();
    await loginAs(page, ADMIN_EMAIL, ADMIN_PASSWORD);
    // Handle forced-password-change on first boot
    if (page.url().includes("/setup")) {
      await page.getByLabel("New password").fill("AdminNew1!");
      await page.getByLabel("Confirm password").fill("AdminNew1!");
      await page.getByRole("button", { name: "Set password" }).click();
      await page.waitForURL((url) => !url.pathname.includes("/setup"));
    }
    await use(page);
    await context.close();
  },

  userPage: async ({ browser }, use) => {
    const context = await browser.newContext();
    const page = await context.newPage();
    await loginAs(page, "e2e-user@example.com", "E2eUser1!");
    await use(page);
    await context.close();
  },
});

export { expect } from "@playwright/test";
