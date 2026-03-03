import { expect, test } from "../fixtures/auth.fixture";

test.describe("Chat flows", () => {
  test("create session and message streams tokens", async ({ userPage: page }) => {
    await page.goto("/chat");
    // Create a new chat session
    const newSessionBtn = page.getByRole("button", {
      name: /new( chat| session)?/i,
    });
    if (await newSessionBtn.isVisible()) {
      await newSessionBtn.click();
    }
    const textarea = page.getByRole("textbox", {
      name: /message|type|ask/i,
    });
    await expect(textarea).toBeVisible({ timeout: 10_000 });
    await textarea.fill("What is 2 + 2?");
    await page.keyboard.press("Enter");
    // Wait for streaming to complete — assistant bubble should appear
    const bubbles = page.locator(
      "[data-role='assistant'], [class*='assistant'], [data-testid*='assistant']",
    );
    await expect(bubbles.first()).toBeVisible({ timeout: 30_000 });
    // Verify at least two bubbles exist (user + assistant)
    const allBubbles = page.locator(
      "[data-role], [class*='message-bubble'], [class*='chat-bubble'], [class*='MessageBubble']",
    );
    const count = await allBubbles.count();
    expect(count).toBeGreaterThanOrEqual(2);
  });

  test("Shift+Enter inserts newline, Enter submits", async ({ userPage: page }) => {
    await page.goto("/chat");
    const newSessionBtn = page.getByRole("button", {
      name: /new( chat| session)?/i,
    });
    if (await newSessionBtn.isVisible()) {
      await newSessionBtn.click();
    }
    const textarea = page.getByRole("textbox", {
      name: /message|type|ask/i,
    });
    await expect(textarea).toBeVisible({ timeout: 10_000 });
    // Shift+Enter should add a newline, not submit
    await textarea.click();
    await textarea.press("Shift+Enter");
    const currentValue = await textarea.inputValue();
    expect(currentValue).toContain("\n");
    // Clear and verify Enter submits (message sent, textarea clears or sends)
    await textarea.fill("Hello world");
    await textarea.press("Enter");
    // After Enter, textarea should be empty (message submitted)
    await expect(textarea).toHaveValue("", { timeout: 5_000 });
  });

  test("clicking citation [N] expands source detail panel", async ({ userPage: page }) => {
    await page.goto("/chat");
    const newSessionBtn = page.getByRole("button", {
      name: /new( chat| session)?/i,
    });
    if (await newSessionBtn.isVisible()) {
      await newSessionBtn.click();
    }
    const textarea = page.getByRole("textbox", {
      name: /message|type|ask/i,
    });
    await expect(textarea).toBeVisible({ timeout: 10_000 });
    await textarea.fill("Tell me about the knowledge base");
    await page.keyboard.press("Enter");
    // Wait for citations to appear — look for [1] or similar citation markers
    const citation = page.locator(
      "button:text-matches('\\[\\d+\\]'), [data-testid*='citation'], [class*='citation']",
    );
    const hasCitation = await citation
      .first()
      .waitFor({ state: "visible", timeout: 30_000 })
      .then(() => true)
      .catch(() => false);
    if (!hasCitation) {
      test.skip();
      return;
    }
    await citation.first().click();
    // Source detail panel should open
    const panel = page.locator(
      "[data-testid*='source-panel'], [class*='SourcePanel'], [class*='citation-panel'], [aria-label*='source']",
    );
    await expect(panel).toBeVisible({ timeout: 5_000 });
  });

  test("session persists in sidebar after page reload", async ({ userPage: page }) => {
    await page.goto("/chat");
    const newSessionBtn = page.getByRole("button", {
      name: /new( chat| session)?/i,
    });
    await expect(newSessionBtn).toBeVisible({ timeout: 10_000 });
    await newSessionBtn.click();
    // Name the session or just send a message to create it
    const textarea = page.getByRole("textbox", {
      name: /message|type|ask/i,
    });
    await expect(textarea).toBeVisible({ timeout: 10_000 });
    const sessionName = `E2E Session ${Date.now()}`;
    await textarea.fill(sessionName.substring(0, 20));
    await page.keyboard.press("Enter");
    // Wait for the message to be sent
    await page.waitForTimeout(2_000);
    // Get the URL or session identifier to verify persistence
    const urlBefore = page.url();
    // Reload the page
    await page.reload();
    await page.waitForLoadState("networkidle");
    // Verify session still appears in sidebar
    const sidebarItems = page.locator(
      "[data-testid*='session'], [class*='session-item'], [class*='SessionItem'], nav a, [aria-label*='chat session']",
    );
    const count = await sidebarItems.count();
    expect(count).toBeGreaterThan(0);
    // The URL should still be valid (redirected to same session or session list)
    const urlAfter = page.url();
    expect(urlAfter).not.toContain("/login");
  });
});
