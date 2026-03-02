import path from 'node:path'
import { expect, test as setup } from '@playwright/test'

const AUTH_FILE = path.join(__dirname, '.auth/user.json')

setup('authenticate', async ({ page }) => {
  await page.goto('/login')
  await page.getByLabel('Email').fill(process.env.E2E_USER_EMAIL ?? 'user@example.com')
  await page.getByLabel('Password').fill(process.env.E2E_USER_PASSWORD ?? 'TestPass123!')
  await page.getByRole('button', { name: /sign in/i }).click()
  await expect(page).toHaveURL(/\/(dashboard|chat)/, { timeout: 10_000 })
  await page.context().storageState({ path: AUTH_FILE })
})
