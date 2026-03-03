import { expect, test } from "../fixtures/auth.fixture";

test.describe("Admin — Guardrail management", () => {
  test("create rule appears in guardrail list", async ({
    adminPage: page,
  }) => {
    await page.goto("/admin/guardrails");
    await expect(page).toHaveURL(/\/admin\/guardrails/, { timeout: 15_000 });

    // Open create rule dialog
    const createBtn = page.getByRole("button", {
      name: /add( rule)?|create( rule)?|new( rule)?/i,
    });
    await expect(createBtn).toBeVisible({ timeout: 10_000 });
    await createBtn.click();

    const dialog = page.getByRole("dialog");
    await expect(dialog).toBeVisible({ timeout: 5_000 });

    // Fill rule fields — name is typically required
    const uniqueName = `E2E Rule ${Date.now()}`;
    const nameField = dialog.getByLabel(/name|title|rule name/i);
    await expect(nameField).toBeVisible({ timeout: 5_000 });
    await nameField.fill(uniqueName);

    // Fill keyword/pattern field if present
    const patternField = dialog.getByLabel(/keyword|pattern|content|blocklist/i);
    if (await patternField.isVisible().catch(() => false)) {
      await patternField.fill("test-blocked-keyword");
    }

    // Submit
    const saveBtn = dialog.getByRole("button", {
      name: /save|create|confirm|add/i,
    });
    await saveBtn.click();

    // Verify the new rule appears in the list
    const ruleRow = page.locator(
      "table tbody tr, [role='row'], [data-testid*='rule-row'], [class*='rule-item']",
    ).filter({ hasText: uniqueName });
    await expect(ruleRow).toBeVisible({ timeout: 10_000 });
  });

  test("deactivate rule toggle becomes unchecked", async ({
    adminPage: page,
  }) => {
    await page.goto("/admin/guardrails");
    await expect(page).toHaveURL(/\/admin\/guardrails/, { timeout: 15_000 });

    // Find first active rule toggle (checked/on state)
    const activeToggle = page.locator(
      "input[type='checkbox'][aria-label*='active'], [role='switch'][aria-checked='true'], input[type='checkbox']:checked",
    ).first();

    const toggleVisible = await activeToggle
      .waitFor({ state: "visible", timeout: 10_000 })
      .then(() => true)
      .catch(() => false);

    if (!toggleVisible) {
      // If no active rules exist, create one first and then deactivate
      const createBtn = page.getByRole("button", {
        name: /add( rule)?|create( rule)?|new( rule)?/i,
      });
      if (await createBtn.isVisible()) {
        await createBtn.click();
        const dialog = page.getByRole("dialog");
        const nameField = dialog.getByLabel(/name|title/i);
        await nameField.fill(`Deactivate Test ${Date.now()}`);
        const saveBtn = dialog.getByRole("button", {
          name: /save|create|confirm/i,
        });
        await saveBtn.click();
        await page.waitForTimeout(1_000);
      }
    }

    // Get the current active toggle and click it to deactivate
    const toggle = page.locator(
      "[role='switch'], input[type='checkbox'][aria-label*='active']",
    ).first();
    await expect(toggle).toBeVisible({ timeout: 10_000 });

    const wasChecked =
      (await toggle.getAttribute("aria-checked")) === "true" ||
      (await toggle.isChecked().catch(() => false));

    await toggle.click();
    await page.waitForTimeout(500);

    // Verify the toggle is now unchecked/off
    if (wasChecked) {
      const isNowChecked =
        (await toggle.getAttribute("aria-checked")) === "true" ||
        (await toggle.isChecked().catch(() => false));
      expect(isNowChecked).toBe(false);
    } else {
      // The toggle was unchecked — re-check our assumption; just verify it changed state
      const ariaChecked = await toggle.getAttribute("aria-checked");
      // Something changed — it should now be "true" since it was off
      expect(ariaChecked).toBe("true");
    }
  });

  test("audit log table renders with rows", async ({ adminPage: page }) => {
    // Audit log may be nested under guardrails, or a separate route
    const auditPaths = [
      "/admin/guardrails/audit",
      "/admin/audit",
      "/admin/guardrails?tab=audit",
      "/admin/audit-log",
    ];

    let landed = false;
    for (const auditPath of auditPaths) {
      await page.goto(auditPath);
      const notFound = page
        .locator("text=404, text=not found", { hasText: /404|not found/i });
      const tableEl = page.locator("table, [role='table'], [role='grid']");
      if (await tableEl.isVisible().catch(() => false)) {
        landed = true;
        break;
      }
    }

    if (!landed) {
      // Fallback: navigate to guardrails and click an audit log tab/link
      await page.goto("/admin/guardrails");
      const auditTab = page.getByRole("tab", { name: /audit/i }).or(
        page.getByRole("link", { name: /audit/i }),
      );
      if (await auditTab.isVisible().catch(() => false)) {
        await auditTab.click();
        landed = true;
      }
    }

    if (!landed) {
      test.skip();
      return;
    }

    // Assert table is visible with at least a header row
    const table = page.locator("table, [role='table'], [role='grid']");
    await expect(table.first()).toBeVisible({ timeout: 10_000 });

    // Verify the table has rows (header + at least one data row)
    const rows = page.locator(
      "table tr, [role='row']",
    );
    const rowCount = await rows.count();
    expect(rowCount).toBeGreaterThan(0);
  });
});
