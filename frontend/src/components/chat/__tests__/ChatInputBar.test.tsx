import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import { render, screen } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { describe, expect, it, vi } from 'vitest'
import { ChatInputBar } from '../ChatInputBar'

function wrapper({ children }: { children: React.ReactNode }) {
  const qc = new QueryClient({ defaultOptions: { queries: { retry: false } } })
  return <QueryClientProvider client={qc}>{children}</QueryClientProvider>
}

describe('ChatInputBar', () => {
  it('calls onSend with trimmed text when Enter is pressed', async () => {
    const user = userEvent.setup()
    const onSend = vi.fn()

    render(<ChatInputBar onSend={onSend} sessionId="session-1" />, { wrapper })

    const textarea = screen.getByRole('textbox', { name: 'Chat message input' })
    await user.click(textarea)
    await user.type(textarea, 'Hello world')
    await user.keyboard('{Enter}')

    expect(onSend).toHaveBeenCalledWith('Hello world')
    expect(onSend).toHaveBeenCalledTimes(1)
  })

  it('does NOT call onSend when Shift+Enter is pressed', async () => {
    const user = userEvent.setup()
    const onSend = vi.fn()

    render(<ChatInputBar onSend={onSend} sessionId="session-1" />, { wrapper })

    const textarea = screen.getByRole('textbox', { name: 'Chat message input' })
    await user.click(textarea)
    await user.type(textarea, 'Hello')
    await user.keyboard('{Shift>}{Enter}{/Shift}')

    expect(onSend).not.toHaveBeenCalled()
  })

  it('keeps textarea and send button enabled when sessionId is null + allowEmptySession (U15 lazy-create path)', () => {
    const onSend = vi.fn()

    render(
      <ChatInputBar onSend={onSend} sessionId={null} allowEmptySession />,
      { wrapper }
    )

    const textarea = screen.getByRole('textbox', { name: 'Chat message input' })
    const button = screen.getByRole('button', { name: 'Send message' })

    // ChatLayout passes allowEmptySession on the lazy-create path so the
    // input is usable before a session id exists; the first send routes
    // through the `'new'` sentinel and the backend creates the row inline.
    expect(textarea).not.toBeDisabled()
    expect(button).not.toBeDisabled()
  })

  it('forwards the typed text to onSend when sessionId is null + allowEmptySession', async () => {
    const user = userEvent.setup()
    const onSend = vi.fn()

    render(
      <ChatInputBar onSend={onSend} sessionId={null} allowEmptySession />,
      { wrapper }
    )

    const textarea = screen.getByRole('textbox', { name: 'Chat message input' })
    await user.click(textarea)
    await user.type(textarea, 'first message')
    await user.keyboard('{Enter}')

    expect(onSend).toHaveBeenCalledWith('first message')
  })

  it('disables the send button while the parent is creating a session', () => {
    const onSend = vi.fn()

    render(<ChatInputBar onSend={onSend} sessionId={null} isCreatingSession />, { wrapper })

    const button = screen.getByRole('button', { name: 'Send message' })
    expect(button).toBeDisabled()
  })

  // FX15 — keep the three controls on the input row at the same baseline
  // height (40px). h-7 on the source-selector trigger and min-h-[2.75rem]
  // (44px) on the textarea both produced visibly uneven rows; this test
  // locks the contract so a future refactor of any single control flags it.
  it('aligns the source-selector, textarea, and send button to the same baseline height (h-10)', () => {
    render(<ChatInputBar onSend={vi.fn()} sessionId="session-1" />, { wrapper })

    const sourceTrigger = screen.getByRole('button', { name: /all sources/i })
    const textarea = screen.getByRole('textbox', { name: 'Chat message input' })
    const sendButton = screen.getByRole('button', { name: 'Send message' })

    expect(sourceTrigger.className).toContain('h-10')
    expect(textarea.className).toContain('min-h-10')
    // The send button uses size="icon" which is h-10 w-10 — verify the rendered
    // class survives so the row stays in lock-step.
    expect(sendButton.className).toContain('h-10')
  })
})
