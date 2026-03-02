import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import { render, screen, waitFor } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { vi } from 'vitest'
import { UsersTable } from '../UsersTable'

const { mockUsers } = vi.hoisted(() => {
  const mockUsers = [
    {
      id: 'u1',
      email: 'admin@example.com',
      full_name: 'Admin User',
      role: 'admin',
      is_active: true,
      last_login_at: new Date().toISOString(),
      created_at: new Date().toISOString(),
    },
    {
      id: 'u2',
      email: 'user@example.com',
      full_name: null,
      role: 'user',
      is_active: false,
      last_login_at: null,
      created_at: new Date().toISOString(),
    },
  ]
  return { mockUsers }
})

vi.mock('@/lib/api-client', () => ({
  apiClient: {
    get: vi.fn().mockResolvedValue({
      data: { items: mockUsers, total: 2, page: 1, page_size: 25 },
    }),
    patch: vi.fn().mockResolvedValue({ data: {} }),
  },
}))

vi.mock('@/features/auth/context/AuthContext', () => ({
  useAuth: vi.fn().mockReturnValue({ user: { id: 'current-user-not-in-list' } }),
}))

function wrapper({ children }: { children: React.ReactNode }) {
  const qc = new QueryClient({ defaultOptions: { queries: { retry: false } } })
  return <QueryClientProvider client={qc}>{children}</QueryClientProvider>
}

test('renders user list with role and status badges', async () => {
  render(<UsersTable />, { wrapper })
  expect(await screen.findByText('admin@example.com')).toBeInTheDocument()
  expect(screen.getByText('user@example.com')).toBeInTheDocument()
  expect(screen.getByText('admin')).toBeInTheDocument()
  expect(screen.getByText('Active')).toBeInTheDocument()
  expect(screen.getByText('Inactive')).toBeInTheDocument()
})

test('search filters users', async () => {
  render(<UsersTable />, { wrapper })
  await screen.findByText('admin@example.com')
  await userEvent.type(screen.getByRole('textbox', { name: /search users/i }), 'admin')
  expect(screen.getByText('admin@example.com')).toBeInTheDocument()
})

test('deactivate shows confirmation dialog', async () => {
  render(<UsersTable />, { wrapper })
  await screen.findByText('admin@example.com')
  await userEvent.click(screen.getByRole('button', { name: /deactivate admin@example.com/i }))
  expect(screen.getByText(/the user's access will be revoked/i)).toBeInTheDocument()
})

test('reactivate button calls PATCH is_active=true', async () => {
  const { apiClient } = await import('@/lib/api-client')
  render(<UsersTable />, { wrapper })
  await screen.findByText('user@example.com')
  await userEvent.click(screen.getByRole('button', { name: /reactivate user@example.com/i }))
  await waitFor(() => {
    expect(apiClient.patch).toHaveBeenCalledWith('/admin/users/u2', { is_active: true })
  })
})
