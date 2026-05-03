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

  it('keeps textarea and send button enabled when sessionId is null so the parent can auto-create on send', () => {
    const onSend = vi.fn()

    render(<ChatInputBar onSend={onSend} sessionId={null} />, { wrapper })

    const textarea = screen.getByRole('textbox', { name: 'Chat message input' })
    const button = screen.getByRole('button', { name: 'Send message' })

    // The previous behaviour silently disabled the input when no session was
    // selected, which made typing-to-start-a-chat a dead end. The parent
    // (ChatLayout) now auto-creates a session on submit, so the input must
    // stay interactive while no session is selected.
    expect(textarea).not.toBeDisabled()
    expect(button).not.toBeDisabled()
  })

  it('forwards the typed text to onSend even when sessionId is null (auto-create path)', async () => {
    const user = userEvent.setup()
    const onSend = vi.fn()

    render(<ChatInputBar onSend={onSend} sessionId={null} />, { wrapper })

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
})
