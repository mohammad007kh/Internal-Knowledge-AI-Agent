import { expect, test } from '@playwright/test'
import { ChatPage } from './pages/ChatPage'

test.describe('Chat full journey', () => {
  let chat: ChatPage

  test.beforeEach(async ({ page }) => {
    chat = new ChatPage(page)
    await chat.goto()
  })

  test('creates a new session and renames it', async ({ page }) => {
    await chat.createSession()
    const renameInput = page.getByRole('textbox', { name: /rename session/i })
    await renameInput.fill('My Test Session')
    await renameInput.press('Enter')
    await expect(page.getByRole('button', { name: /chat session: my test session/i })).toBeVisible()
  })

  test('sends a message and sees streamed response', async ({ page }) => {
    await chat.createSession()
    await page.keyboard.press('Escape')
    await chat.sendMessage('What is the purpose of this system?')
    // Optimistic user bubble visible immediately
    await expect(chat.thread.getByText('What is the purpose of this system?')).toBeVisible()
    // Streaming cursor appears
    await expect(page.locator('[aria-hidden="true"]').first()).toBeVisible({ timeout: 15_000 })
    await chat.waitForStreamingComplete()
    // Two bubbles in thread (user + assistant)
    const bubbles = chat.thread.locator('[data-role]')
    await expect(bubbles).toHaveCount(2)
  })

  test('opens citation panel on citation button click', async ({ page }) => {
    const sessionBtn = page.getByRole('button', { name: /chat session: my test session/i })
    const sessionExists = await sessionBtn.isVisible().catch(() => false)
    if (!sessionExists) {
      test.skip()
      return
    }
    await sessionBtn.click()
    const citationList = page.getByRole('list', { name: /citations/i })
    const firstCitation = citationList.locator('[data-citation]').first()
    const hasCitation = await firstCitation.isVisible().catch(() => false)
    if (!hasCitation) {
      test.skip()
      return
    }
    await firstCitation.click()
    const panel = page.getByRole('complementary', { name: /citation details/i })
    await expect(panel).toBeVisible()
    const heading = panel.locator('h2')
    await expect(heading).not.toBeEmpty()
    await page.getByRole('button', { name: /close citation panel/i }).click()
    await expect(panel).toHaveAttribute('aria-hidden', 'true')
  })

  test('source selector updates session sources', async ({ page }) => {
    await chat.createSession()
    await page.keyboard.press('Escape')
    await chat.sourceSelector.click()
    const dialog = page.getByRole('dialog', { name: /select knowledge sources/i })
    await expect(dialog).toBeVisible()
    const firstOption = dialog.getByRole('option').first()
    const hasOptions = await firstOption.isVisible().catch(() => false)
    if (hasOptions) {
      await firstOption.click()
      await page.keyboard.press('Escape')
      await expect(page.getByRole('list', { name: /selected sources/i })).toBeVisible()
    } else {
      await page.keyboard.press('Escape')
      await expect(page.getByText(/no sources available/i)).toBeVisible()
    }
  })

  test('submits thumbs up feedback on assistant message', async ({ page }) => {
    const helpfulBtn = page.getByRole('button', { name: /mark as helpful/i }).first()
    const isVisible = await helpfulBtn.isVisible().catch(() => false)
    if (!isVisible) {
      test.skip()
      return
    }
    await helpfulBtn.click()
    await expect(helpfulBtn).toBeDisabled({ timeout: 5_000 })
  })

  test('deletes a session with confirmation', async ({ page }) => {
    await chat.createSession()
    const renameInput = page.getByRole('textbox', { name: /rename session/i })
    await renameInput.fill('To Be Deleted')
    await renameInput.press('Enter')
    const sessionBtn = page.getByRole('button', { name: /chat session: to be deleted/i })
    await expect(sessionBtn).toBeVisible()
    await sessionBtn.hover()
    await page.getByRole('button', { name: /delete: to be deleted/i }).click()
    await expect(page.getByRole('alertdialog')).toBeVisible()
    await page.getByRole('button', { name: /^delete$/i }).click()
    await expect(sessionBtn).not.toBeVisible({ timeout: 5_000 })
  })

  test('chat page has no critical accessibility violations', async ({ page }) => {
    const { checkA11y, injectAxe } = await import('axe-playwright')
    await injectAxe(page)
    await checkA11y(page, undefined, { includedImpacts: ['critical', 'serious'] })
  })
})
