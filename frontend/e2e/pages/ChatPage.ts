import type { Locator, Page } from '@playwright/test'

export class ChatPage {
  readonly page: Page
  readonly newSessionBtn: Locator
  readonly searchInput: Locator
  readonly sessionList: Locator
  readonly chatTextarea: Locator
  readonly sendBtn: Locator
  readonly sourceSelector: Locator
  readonly thread: Locator

  constructor(page: Page) {
    this.page = page
    this.newSessionBtn = page.getByRole('button', { name: /new chat session/i })
    this.searchInput = page.getByRole('textbox', { name: /search sessions/i })
    this.sessionList = page
      .getByRole('list')
      .filter({ hasText: /session/i })
      .first()
    this.chatTextarea = page.getByRole('textbox', { name: /chat message input/i })
    this.sendBtn = page.getByRole('button', { name: /send message/i })
    this.sourceSelector = page.getByRole('button', { name: /all sources|source/i })
    this.thread = page.getByRole('log', { name: /conversation/i })
  }

  async goto() {
    await this.page.goto('/chat')
  }

  async createSession() {
    await this.newSessionBtn.click()
  }

  async getSessionItem(title: string): Promise<Locator> {
    return this.page.getByRole('button', { name: new RegExp(`chat session: ${title}`, 'i') })
  }

  async sendMessage(text: string) {
    await this.chatTextarea.fill(text)
    await this.sendBtn.click()
  }

  async waitForStreamingComplete() {
    await this.page.waitForSelector('[aria-live="polite"] [aria-hidden="true"]', {
      state: 'detached',
      timeout: 30_000,
    })
  }
}
