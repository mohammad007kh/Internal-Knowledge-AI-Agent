import { expect, test } from "../fixtures/auth.fixture";

test.describe("Admin — Invite User", () => {
  test("invite modal shows success and new pending row in users table", async ({
    adminPage: page,
  }) => {
    await page.goto("/admin/users");
    await expect(page).toHaveURL(/\/admin\/users/, { timeout: 15_000 });

    // Open invite dialog
    const inviteBtn = page.getByRole("button", { name: /invite( user)?/i });
    await expect(inviteBtn).toBeVisible({ timeout: 10_000 });
    await inviteBtn.click();

    // Fill the invite form with a unique email to avoid duplicates across runs
    const uniqueEmail = `e2e-invite-${Date.now()}@example.com`;
    const dialog = page.getByRole("dialog");
    await expect(dialog).toBeVisible({ timeout: 5_000 });

    const emailField = dialog.getByLabel(/email/i);
    await expect(emailField).toBeVisible({ timeout: 5_000 });
    await emailField.fill(uniqueEmail);

    // Submit the invite
    const submitBtn = dialog.getByRole("button", {
      name: /send( invite)?|invite|confirm/i,
    });
    await submitBtn.click();

    // Assert success toast/notification
    const successToast = page.locator(
      "[role='status'], [role='alert'], [data-testid*='toast'], [class*='toast'], [class*='snackbar']",
    ).filter({ hasText: /success|sent|invited/i });
    await expect(successToast).toBeVisible({ timeout: 10_000 });

    // Assert new row in users table with "pending" status
    const tableRow = page.locator("table tbody tr, [role='row']").filter({
      hasText: uniqueEmail,
    });
    await expect(tableRow).toBeVisible({ timeout: 10_000 });
    await expect(tableRow).toContainText(/pending/i);
  });
});
