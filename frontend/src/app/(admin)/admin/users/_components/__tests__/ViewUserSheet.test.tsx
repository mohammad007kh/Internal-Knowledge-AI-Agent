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
  useSearchParams: () => new URLSearchParams('user=u1'),
}))

const { mockUser } = vi.hoisted(() => ({
  mockUser: {
    id: 'u1',
    email: 'alice@company.com',
    full_name: 'Alice Martin',
    role: 'admin' as const,
    is_active: true,
    last_login_at: new Date(Date.now() - 2 * 60 * 60 * 1000).toISOString(),
    created_at: '2026-03-04T12:00:00Z',
  },
}))

vi.mock('@/lib/api-client', () => ({
  apiClient: {
    get: vi.fn().mockResolvedValue({ data: mockUser }),
    patch: vi.fn().mockResolvedValue({ data: { ...mockUser } }),
    post: vi.fn().mockResolvedValue({ data: {} }),
    delete: vi.fn().mockResolvedValue({ data: {} }),
  },
}))

vi.mock('sonner', () => ({
  toast: { success: vi.fn(), error: vi.fn() },
}))

import { ViewUserSheet } from '../ViewUserSheet'

function wrapper({ children }: { children: ReactNode }) {
  const qc = new QueryClient({ defaultOptions: { queries: { retry: false } } })
  return <QueryClientProvider client={qc}>{children}</QueryClientProvider>
}

describe('ViewUserSheet', () => {
  beforeEach(() => {
    replaceMock.mockClear()
  })
  afterEach(() => {
    vi.clearAllMocks()
  })

  it('opens when ?user=<id> is set and renders all four sections', async () => {
    render(<ViewUserSheet />, { wrapper })

    // The Sheet title shows the user's full name (heading role).
    expect(
      await screen.findByRole('heading', { level: 2, name: 'Alice Martin' })
    ).toBeInTheDocument()

    // Section headings
    expect(screen.getByRole('heading', { name: /^profile$/i })).toBeInTheDocument()
    expect(screen.getByRole('heading', { name: /role.*access/i })).toBeInTheDocument()
    expect(screen.getByRole('heading', { name: /^security$/i })).toBeInTheDocument()
    expect(screen.getByRole('heading', { name: /danger zone/i })).toBeInTheDocument()

    // State chips ("Admin" appears both in the header badge and in the role
    // Select trigger — at least one is fine for this assertion).
    expect(screen.getByText('Active')).toBeInTheDocument()
    expect(screen.getAllByText('Admin').length).toBeGreaterThan(0)
    expect(screen.getByText(/last seen/i)).toBeInTheDocument()
  })

  it('per-field Edit reveals input and PATCHes /users/{id} on save', async () => {
    const { apiClient } = await import('@/lib/api-client')
    render(<ViewUserSheet />, { wrapper })
    const user = userEvent.setup()

    await screen.findByRole('heading', { level: 2, name: 'Alice Martin' })

    // Click the "Edit" chip on the Full name row.
    await user.click(screen.getByRole('button', { name: /edit full name/i }))
    // Narrow to the form-control label (excludes aria-label="Edit ...").
    const input = (await screen.findByLabelText('Full name', {
      selector: 'input',
    })) as HTMLInputElement
    expect(input.value).toBe('Alice Martin')

    await user.clear(input)
    await user.type(input, 'Alice M.')
    await user.click(screen.getByRole('button', { name: /save full name/i }))

    await waitFor(() => {
      expect(apiClient.patch).toHaveBeenCalledWith('/api/v1/users/u1', {
        full_name: 'Alice M.',
      })
    })
  })

  it('Role section saves via PATCH /role (separate endpoint)', async () => {
    const { apiClient } = await import('@/lib/api-client')
    render(<ViewUserSheet />, { wrapper })
    const user = userEvent.setup()

    await screen.findByRole('heading', { level: 2, name: 'Alice Martin' })

    // Open the role select and pick Member.
    const roleTrigger = screen.getByRole('combobox')
    await user.click(roleTrigger)
    await user.click(await screen.findByRole('option', { name: 'Member' }))

    // Now the Save button should fire PATCH /role.
    await user.click(screen.getByRole('button', { name: /save role/i }))
    await waitFor(() => {
      expect(apiClient.patch).toHaveBeenCalledWith('/api/v1/users/u1/role', {
        role: 'user',
      })
    })
  })

  it('Delete is gated by typing the email and calls DELETE /users/{id}', async () => {
    const { apiClient } = await import('@/lib/api-client')
    render(<ViewUserSheet />, { wrapper })
    const user = userEvent.setup()

    await screen.findByRole('heading', { level: 2, name: 'Alice Martin' })

    // Open the danger-zone delete confirm.
    await user.click(screen.getByRole('button', { name: /^delete$/i }))

    const confirmInput = await screen.findByLabelText(
      /type the email address to confirm/i
    )
    const deleteBtn = screen.getByRole('button', { name: /delete user/i })
    expect(deleteBtn).toBeDisabled()

    // Wrong text keeps it disabled.
    await user.type(confirmInput, 'nope@company.com')
    expect(deleteBtn).toBeDisabled()

    // Correct email enables it.
    await user.clear(confirmInput)
    await user.type(confirmInput, 'alice@company.com')
    expect(deleteBtn).not.toBeDisabled()

    await user.click(deleteBtn)
    await waitFor(() => {
      expect(apiClient.delete).toHaveBeenCalledWith('/api/v1/users/u1')
    })
    // Sheet auto-closes after delete (URL cleared).
    await waitFor(() => {
      expect(replaceMock).toHaveBeenCalledWith('/admin/users')
    })
  })
})
