import type { UsersPage } from '@/lib/api/users'
import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import { render, screen, waitFor, within } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { beforeEach, expect, test, vi } from 'vitest'
import { UsersTable } from '../UsersTable'

const { activeUser, deactivatedUser } = vi.hoisted(() => ({
  activeUser: {
    id: 'u1',
    email: 'admin@example.com',
    full_name: 'Admin User',
    role: 'admin' as const,
    is_active: true,
    last_login_at: new Date().toISOString(),
    created_at: new Date().toISOString(),
  },
  deactivatedUser: {
    id: 'u2',
    email: 'gone@example.com',
    full_name: null,
    role: 'user' as const,
    is_active: false,
    last_login_at: null,
    created_at: new Date().toISOString(),
  },
}))

const listUsersApi = vi.fn()
const deactivateUserApi = vi.fn().mockResolvedValue(undefined)
const reactivateUserApi = vi.fn().mockResolvedValue({ ...deactivatedUser, is_active: true })

vi.mock('@/lib/api/users', () => ({
  listUsersApi: (...args: unknown[]) => listUsersApi(...args),
  deactivateUserApi: (...args: unknown[]) => deactivateUserApi(...args),
  reactivateUserApi: (...args: unknown[]) => reactivateUserApi(...args),
}))

vi.mock('@/features/auth/context/AuthContext', () => ({
  useAuth: () => ({ user: { id: 'current-user-not-in-list' } }),
}))

vi.mock('sonner', () => ({
  toast: { success: vi.fn(), error: vi.fn() },
}))

type Row = typeof activeUser | typeof deactivatedUser

function page(items: readonly Row[], total = items.length): UsersPage {
  return { items: items as unknown as UsersPage['items'], total, page: 1, page_size: 25 }
}

function wrapper({ children }: { children: React.ReactNode }) {
  const qc = new QueryClient({ defaultOptions: { queries: { retry: false } } })
  return <QueryClientProvider client={qc}>{children}</QueryClientProvider>
}

beforeEach(() => {
  vi.clearAllMocks()
  listUsersApi.mockResolvedValue(page([activeUser, deactivatedUser], 2))
})

test('renders a deactivated user with the Deactivated badge', async () => {
  render(<UsersTable />, { wrapper })
  expect(await screen.findByText('gone@example.com')).toBeInTheDocument()
  expect(screen.getByText('Active')).toBeInTheDocument()
  expect(screen.getByText('Deactivated')).toBeInTheDocument()
})

test('reactivate button calls the reactivate API', async () => {
  render(<UsersTable />, { wrapper })
  await screen.findByText('gone@example.com')
  await userEvent.click(screen.getByRole('button', { name: /reactivate gone@example.com/i }))
  await waitFor(() => {
    expect(reactivateUserApi).toHaveBeenCalledWith('u2')
  })
})

test('status filter narrows the list (server-side)', async () => {
  render(<UsersTable />, { wrapper })
  await screen.findByText('gone@example.com')

  // Switch the segmented control to "Deactivated".
  listUsersApi.mockResolvedValueOnce(page([deactivatedUser], 1))
  const statusGroup = screen.getByRole('group', { name: /status/i })
  await userEvent.click(within(statusGroup).getByRole('button', { name: 'Deactivated' }))

  await waitFor(() => {
    expect(listUsersApi).toHaveBeenLastCalledWith({ page: 1, pageSize: 25, status: 'inactive' })
  })
  await waitFor(() => {
    expect(screen.queryByText('admin@example.com')).not.toBeInTheDocument()
  })
  expect(screen.getByText('gone@example.com')).toBeInTheDocument()
})

test('pagination Next / Previous request the right page', async () => {
  listUsersApi.mockResolvedValue(page([activeUser], 60))
  render(<UsersTable />, { wrapper })
  await screen.findByText('admin@example.com')

  await userEvent.click(screen.getByRole('button', { name: /next page/i }))
  await waitFor(() => {
    expect(listUsersApi).toHaveBeenLastCalledWith({ page: 2, pageSize: 25, status: 'all' })
  })

  await userEvent.click(screen.getByRole('button', { name: /previous page/i }))
  await waitFor(() => {
    expect(listUsersApi).toHaveBeenLastCalledWith({ page: 1, pageSize: 25, status: 'all' })
  })
})

test('deactivate shows a confirmation dialog', async () => {
  render(<UsersTable />, { wrapper })
  await screen.findByText('admin@example.com')
  await userEvent.click(screen.getByRole('button', { name: /deactivate admin@example.com/i }))
  expect(screen.getByText(/the user's access will be revoked/i)).toBeInTheDocument()
})
