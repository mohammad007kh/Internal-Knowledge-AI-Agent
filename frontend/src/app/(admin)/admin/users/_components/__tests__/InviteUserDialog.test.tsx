import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import { render, screen, waitFor } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import type { ReactNode } from 'react'
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'

const replaceMock = vi.fn()

vi.mock('next/navigation', () => ({
  useRouter: () => ({
    push: vi.fn(),
    replace: replaceMock,
    back: vi.fn(),
    forward: vi.fn(),
    refresh: vi.fn(),
    prefetch: vi.fn(),
  }),
  useSearchParams: () => new URLSearchParams('invite=1'),
}))

vi.mock('@/lib/api-client', () => ({
  apiClient: {
    post: vi.fn().mockResolvedValue({ data: {} }),
  },
}))

vi.mock('sonner', () => ({
  toast: { success: vi.fn(), error: vi.fn() },
}))

import { InviteUserDialog } from '../InviteUserDialog'

function wrapper({ children }: { children: ReactNode }) {
  const qc = new QueryClient({ defaultOptions: { queries: { retry: false } } })
  return <QueryClientProvider client={qc}>{children}</QueryClientProvider>
}

describe('InviteUserDialog', () => {
  beforeEach(() => {
    replaceMock.mockClear()
  })
  afterEach(() => {
    vi.clearAllMocks()
  })

  it('opens when ?invite=1 is set, defaults role to Member, and email is autofocused', () => {
    render(<InviteUserDialog />, { wrapper })
    expect(screen.getByText('Invite a teammate')).toBeInTheDocument()
    const memberRadio = screen.getByRole('radio', { name: /member/i })
    const adminRadio = screen.getByRole('radio', { name: /admin/i })
    expect(memberRadio).toHaveAttribute('aria-checked', 'true')
    expect(adminRadio).toHaveAttribute('aria-checked', 'false')

    const email = screen.getByLabelText(/email address/i)
    expect(email).toHaveFocus()
  })

  it('rejects invalid email on submit', async () => {
    render(<InviteUserDialog />, { wrapper })
    const user = userEvent.setup()
    await user.type(screen.getByLabelText(/email address/i), 'not-an-email')
    await user.click(screen.getByRole('button', { name: /^send$/i }))
    expect(await screen.findByText(/valid email/i)).toBeInTheDocument()
  })

  it('Cancel closes the dialog (clears the URL via router.replace)', async () => {
    render(<InviteUserDialog />, { wrapper })
    const user = userEvent.setup()
    await user.click(screen.getByRole('button', { name: /cancel/i }))
    expect(replaceMock).toHaveBeenCalledWith('/admin/users')
  })

  it('"Send another?" keeps the dialog open and resets the email field', async () => {
    const { apiClient } = await import('@/lib/api-client')
    render(<InviteUserDialog />, { wrapper })
    const user = userEvent.setup()

    // Tick the "Send another after this one" checkbox.
    await user.click(screen.getByRole('checkbox', { name: /send another/i }))

    const email = screen.getByLabelText(/email address/i) as HTMLInputElement
    await user.type(email, 'first@example.com')
    await user.click(screen.getByRole('button', { name: /^send$/i }))

    await waitFor(() => {
      expect(apiClient.post).toHaveBeenCalledWith(
        '/api/v1/users/invitations',
        expect.objectContaining({ email: 'first@example.com', role: 'user' })
      )
    })
    // Dialog stays open, email cleared.
    await waitFor(() => {
      expect(
        (screen.getByLabelText(/email address/i) as HTMLInputElement).value
      ).toBe('')
    })
    expect(replaceMock).not.toHaveBeenCalled()
  })

  it('without "Send another", submitting closes the dialog', async () => {
    const { apiClient } = await import('@/lib/api-client')
    render(<InviteUserDialog />, { wrapper })
    const user = userEvent.setup()
    await user.type(screen.getByLabelText(/email address/i), 'second@example.com')
    await user.click(screen.getByRole('button', { name: /^send$/i }))
    await waitFor(() => {
      expect(apiClient.post).toHaveBeenCalled()
    })
    await waitFor(() => {
      expect(replaceMock).toHaveBeenCalledWith('/admin/users')
    })
  })
})
