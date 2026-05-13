import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import { render, screen } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { vi } from 'vitest'
import { SelectedSessionProvider } from '../SelectedSessionContext'
import { SessionList } from '../SessionList'

vi.mock('@/lib/api-client', () => ({
  apiClient: {
    get: vi.fn().mockResolvedValue({
      // Backend envelope is `{sessions, total}` (see
      // backend/src/schemas/chat.py::ChatSessionListResponse). The previous
      // mock used `items` which silently returned undefined — fixed alongside
      // the U15 lazy-creation work.
      data: {
        sessions: [
          {
            id: 's1',
            title: 'Project alpha',
            created_at: '2024-01-01T00:00:00Z',
            updated_at: '2024-01-01T00:00:00Z',
            message_count: 3,
          },
          {
            id: 's2',
            title: 'Security review',
            created_at: '2024-01-02T00:00:00Z',
            updated_at: '2024-01-02T00:00:00Z',
            message_count: 0,
          },
        ],
        total: 2,
      },
    }),
    post: vi.fn().mockResolvedValue({
      data: {
        id: 's3',
        title: 'New chat',
        message_count: 0,
        created_at: '2024-01-03T00:00:00Z',
        updated_at: '2024-01-03T00:00:00Z',
      },
    }),
    patch: vi.fn().mockResolvedValue({
      data: {
        id: 's1',
        title: 'Renamed',
        message_count: 3,
        created_at: '2024-01-01T00:00:00Z',
        updated_at: '2024-01-01T00:00:00Z',
      },
    }),
    delete: vi.fn().mockResolvedValue({ data: {} }),
  },
}))

const _mockSessions = [
  {
    id: 's1',
    title: 'Project alpha',
    created_at: '2024-01-01T00:00:00Z',
    updated_at: '2024-01-01T00:00:00Z',
    message_count: 3,
  },
  {
    id: 's2',
    title: 'Security review',
    created_at: '2024-01-02T00:00:00Z',
    updated_at: '2024-01-02T00:00:00Z',
    message_count: 0,
  },
]

function wrapper({ children }: { children: React.ReactNode }) {
  const qc = new QueryClient({ defaultOptions: { queries: { retry: false } } })
  return (
    <QueryClientProvider client={qc}>
      <SelectedSessionProvider>{children}</SelectedSessionProvider>
    </QueryClientProvider>
  )
}

test('renders session list', async () => {
  render(<SessionList />, { wrapper })
  expect(await screen.findByText('Project alpha')).toBeInTheDocument()
  expect(screen.getByText('Security review')).toBeInTheDocument()
})

test('filters sessions by search', async () => {
  render(<SessionList />, { wrapper })
  await screen.findByText('Project alpha')
  await userEvent.type(screen.getByRole('textbox', { name: /search/i }), 'security')
  expect(screen.queryByText('Project alpha')).not.toBeInTheDocument()
  expect(screen.getByText('Security review')).toBeInTheDocument()
})

// U15 lazy creation: the "+" button no longer fires POST /sessions. The
// row is created server-side on the first user message, so clicking the
// "+" is now a pure navigation (clear active selection → `/chat`).
test('new session button does not POST /api/v1/chat/sessions (U15 lazy creation)', async () => {
  const { apiClient } = await import('@/lib/api-client')
  ;(apiClient.post as ReturnType<typeof vi.fn>).mockClear()
  render(<SessionList />, { wrapper })
  await screen.findByText('Project alpha')
  await userEvent.click(screen.getByRole('button', { name: /new chat session/i }))
  expect(apiClient.post).not.toHaveBeenCalled()
})

test('shows delete confirmation dialog', async () => {
  render(<SessionList />, { wrapper })
  await screen.findByText('Project alpha')
  // Open the kebab menu, then click Delete in the popover.
  const kebab = await screen.findByRole('button', { name: /open menu: project alpha/i })
  await userEvent.click(kebab)
  const deleteBtn = await screen.findByRole('menuitem', { name: /delete: project alpha/i })
  await userEvent.click(deleteBtn)
  expect(
    screen.getByText(/all messages in this session will be permanently deleted/i)
  ).toBeInTheDocument()
})

test('Escape closes rename mode', async () => {
  render(<SessionList />, { wrapper })
  await screen.findByText('Project alpha')
  const kebab = await screen.findByRole('button', { name: /open menu: project alpha/i })
  await userEvent.click(kebab)
  await userEvent.click(await screen.findByRole('menuitem', { name: /rename: project alpha/i }))
  expect(screen.getByRole('textbox', { name: /rename session/i })).toBeInTheDocument()
  await userEvent.keyboard('{Escape}')
  expect(screen.queryByRole('textbox', { name: /rename session/i })).not.toBeInTheDocument()
})
