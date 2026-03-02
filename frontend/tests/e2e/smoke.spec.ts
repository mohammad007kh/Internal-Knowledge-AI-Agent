import { expect, test } from '@playwright/test'

test('login page loads', async ({ page }) => {
  await page.goto('/login')
  await expect(page).toHaveTitle(/Knowledge AI Agent/)
  await expect(page.getByRole('heading', { name: /Sign in/i })).toBeVisible()
})

test('unauthenticated access to /chat redirects to /login', async ({ page }) => {
  await page.goto('/chat')
  await expect(page).toHaveURL(/\/login/)
})
