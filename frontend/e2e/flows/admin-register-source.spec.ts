import path from "path";

import { expect, test } from "../fixtures/auth.fixture";

test.describe("Admin — Register Source", () => {
  test("source wizard shows connection step UI", async ({
    adminPage: page,
  }) => {
    await page.goto("/admin/sources/new");
    await expect(page).toHaveURL(/\/admin\/sources\/new/, { timeout: 15_000 });

    // Connection step should be visible as the first wizard step
    const connectionStep = page.locator(
      "[data-testid*='connection'], [data-step='connection'], [class*='wizard-step'], [aria-label*='connection'], h1, h2, h3",
    ).filter({ hasText: /connect(ion)?|source|type|provider/i });
    await expect(connectionStep.first()).toBeVisible({ timeout: 10_000 });

    // Verify there's a stepper / breadcrumb showing wizard navigation
    const stepper = page.locator(
      "[role='progressbar'], [data-testid*='stepper'], [class*='stepper'], [class*='wizard'], ol[aria-label], [aria-label*='step']",
    );
    const hasStepperVisible = await stepper.first().isVisible().catch(() => false);
    if (hasStepperVisible) {
      await expect(stepper.first()).toBeVisible();
    } else {
      // At minimum, verify we're on a form/wizard page with connection-related inputs
      const formEl = page.locator("form, [role='form']");
      await expect(formEl.first()).toBeVisible({ timeout: 5_000 });
    }
  });

  test("file larger than 50 MB is rejected client-side (FR-035)", async ({
    adminPage: page,
  }) => {
    await page.goto("/admin/sources/new");
    await expect(page).toHaveURL(/\/admin\/sources\/new/, { timeout: 15_000 });

    // Navigate to file upload step (may need to choose "file upload" source type first)
    const fileTypeOption = page.getByRole("option", {
      name: /file|upload|document/i,
    });
    const hasFileTypeOption = await fileTypeOption.isVisible().catch(() => false);
    if (hasFileTypeOption) {
      await fileTypeOption.click();
    } else {
      // Try a button or card with file/upload label
      const fileCard = page.getByRole("button", {
        name: /file|upload|document/i,
      });
      if (await fileCard.isVisible().catch(() => false)) {
        await fileCard.click();
      }
    }

    // Find the file input
    const fileInput = page.locator("input[type='file']");
    const hasFileInput = await fileInput.isVisible().catch(() => false);
    if (!hasFileInput) {
      // Try to trigger the file input via the upload area button
      const uploadArea = page.locator(
        "[data-testid*='upload'], [class*='upload'], [class*='dropzone'], [aria-label*='upload']",
      );
      if (await uploadArea.isVisible().catch(() => false)) {
        await uploadArea.click();
      }
    }

    // Create a buffer representing a 51 MB file using the File API
    // We use page.evaluate to trigger a synthetic file that exceeds the limit
    await page.evaluate(() => {
      const fakeFile = new File(
        [new ArrayBuffer(51 * 1024 * 1024)],
        "large-file.pdf",
        { type: "application/pdf" },
      );
      const dt = new DataTransfer();
      dt.items.add(fakeFile);
      const input = document.querySelector("input[type='file']") as HTMLInputElement;
      if (input) {
        Object.defineProperty(input, "files", { value: dt.files });
        input.dispatchEvent(new Event("change", { bubbles: true }));
        input.dispatchEvent(new Event("input", { bubbles: true }));
      }
    });

    // Assert a client-side file-too-large error
    const sizeError = page.locator(
      "[role='alert'], [data-testid*='error'], [class*='error'], [class*='validation']",
    ).filter({ hasText: /too large|size|50\s*mb|maximum|limit/i });
    await expect(sizeError.first()).toBeVisible({ timeout: 10_000 });
  });

  test("unsupported file type (.exe) is rejected with error", async ({
    adminPage: page,
  }) => {
    await page.goto("/admin/sources/new");
    await expect(page).toHaveURL(/\/admin\/sources\/new/, { timeout: 15_000 });

    // Navigate to file upload step
    const fileTypeOption = page.getByRole("option", {
      name: /file|upload|document/i,
    });
    if (await fileTypeOption.isVisible().catch(() => false)) {
      await fileTypeOption.click();
    } else {
      const fileCard = page.getByRole("button", {
        name: /file|upload|document/i,
      });
      if (await fileCard.isVisible().catch(() => false)) {
        await fileCard.click();
      }
    }

    // Inject a fake .exe file via evaluate
    await page.evaluate(() => {
      const fakeFile = new File(
        ["MZ\x90\x00"],
        "malware.exe",
        { type: "application/x-msdownload" },
      );
      const dt = new DataTransfer();
      dt.items.add(fakeFile);
      const input = document.querySelector("input[type='file']") as HTMLInputElement;
      if (input) {
        Object.defineProperty(input, "files", { value: dt.files });
        input.dispatchEvent(new Event("change", { bubbles: true }));
        input.dispatchEvent(new Event("input", { bubbles: true }));
      }
    });

    // Assert an unsupported file type error
    const typeError = page.locator(
      "[role='alert'], [data-testid*='error'], [class*='error'], [class*='validation']",
    ).filter({ hasText: /unsupported|not allowed|invalid.*type|file type/i });
    await expect(typeError.first()).toBeVisible({ timeout: 10_000 });
  });
});
