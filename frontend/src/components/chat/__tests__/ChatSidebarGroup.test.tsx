import { SidebarProvider } from '@/components/dashboard/SidebarProvider'
import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import { render, screen } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { type ReactNode } from 'react'
import { beforeAll, vi } from 'vitest'
import { ChatSidebarGroup } from '../ChatSidebarGroup'
import { SelectedSessionProvider } from '../SelectedSessionContext'

vi.mock('next/navigation', () => ({
  usePathname: () => '/chat',
  useRouter: () => ({ push: vi.fn(), replace: vi.fn(), prefetch: vi.fn() }),
  useParams: () => ({}),
}))

// jsdom does not implement window.matchMedia (used by SidebarProvider's
// useIsMobile hook). Stub it to a desktop-shaped MediaQueryList so the
// sidebar renders the expanded view we want to assert against.
beforeAll(() => {
  Object.defineProperty(window, 'matchMedia', {
    writable: true,
    value: (query: string) => ({
      matches: false,
      media: query,
      onchange: null,
      addListener: vi.fn(),
      removeListener: vi.fn(),
      addEventListener: vi.fn(),
      removeEventListener: vi.fn(),
      dispatchEvent: vi.fn(),
    }),
  })
})

vi.mock('@/lib/api-client', () => ({
  apiClient: {
    get: vi.fn().mockResolvedValue({
      // Backend chat-sessions envelope is `{sessions, total}` — see
      // backend/src/schemas/chat.py::ChatSessionListResponse. The lone
      // outlier among paginated responses in this codebase.
      data: {
        sessions: [
          {
            id: 's1',
            title: 'Onboarding plan',
            created_at: '2024-01-01T00:00:00Z',
            updated_at: '2024-01-02T00:00:00Z',
            message_count: 4,
          },
          {
            id: 's2',
            title: 'Quarterly review',
            created_at: '2024-01-03T00:00:00Z',
            updated_at: '2024-01-04T00:00:00Z',
            message_count: 1,
          },
        ],
        total: 2,
      },
    }),
    post: vi.fn(),
    patch: vi.fn(),
    delete: vi.fn(),
  },
}))

function wrapper({ children }: { children: React.ReactNode }) {
  const qc = new QueryClient({ defaultOptions: { queries: { retry: false } } })
  return (
    <QueryClientProvider client={qc}>
      <SidebarProvider>
        <SelectedSessionProvider>{children}</SelectedSessionProvider>
      </SidebarProvider>
    </QueryClientProvider>
  )
}

test('renders kebab menu with Rename and Delete on each recent-chat row', async () => {
  render(<ChatSidebarGroup />, { wrapper })

  // Both sessions should render in the disclosure (it's open by default
  // when on /chat — see ChatSidebarGroup.onChatRoute).
  expect(await screen.findByText('Quarterly review')).toBeInTheDocument()
  expect(screen.getByText('Onboarding plan')).toBeInTheDocument()

  // The kebab on the most-recently-updated row (Quarterly review) should
  // open a popover with Rename and Delete menuitems.
  const kebab = await screen.findByRole('button', { name: /open menu: quarterly review/i })
  await userEvent.click(kebab)

  expect(
    await screen.findByRole('menuitem', { name: /rename: quarterly review/i })
  ).toBeInTheDocument()
  expect(screen.getByRole('menuitem', { name: /delete: quarterly review/i })).toBeInTheDocument()
})

// U15 lazy creation: clicking the sidebar "+" must NOT fire POST /sessions.
// The row is created server-side on the first user message, not on the
// click of the "+".
test('"+" button does not POST /api/v1/chat/sessions (U15 lazy creation)', async () => {
  const { apiClient } = await import('@/lib/api-client')
  // Reset any spies set by other suites.
  ;(apiClient.post as ReturnType<typeof vi.fn>).mockClear()

  render(<ChatSidebarGroup />, { wrapper })

  // Wait for the disclosure to render so the "+" is in the DOM.
  await screen.findByText('Onboarding plan')
  const newChatBtn = screen.getByRole('button', { name: /^new chat$/i })
  await userEvent.click(newChatBtn)

  expect(apiClient.post).not.toHaveBeenCalled()
})

// U15: when a session has a null title (freshly-created, titler hasn't
// landed yet), the row renders a first-message preview from the cached
// messages query, or the generic "New chat" placeholder when nothing is
// cached.
test('renders first-user-message preview as fallback when title is null', async () => {
  const qc = new QueryClient({ defaultOptions: { queries: { retry: false } } })
  // Pre-seed the chat-sessions cache so the in-flight `useQuery` resolves
  // immediately (the mocked `apiClient.get` in the file-level mock returns
  // the two titled sessions — overriding with a setQueryData adds one
  // null-title row at the top by `updated_at`).
  qc.setQueryData(['chat-sessions'], {
    sessions: [
      {
        id: 's3',
        title: null,
        created_at: '2024-02-01T00:00:00Z',
        updated_at: '2024-02-02T00:00:00Z',
        message_count: 1,
      },
    ],
    total: 1,
  })
  qc.setQueryData(['chat-session-messages', 's3'], {
    session: { id: 's3', title: null, source_ids: [] },
    messages: [
      {
        id: 'm1',
        role: 'user',
        content: 'How do I migrate the database?',
        created_at: '2024-02-01T00:00:00Z',
      },
    ],
  })

  function clientWrapper({ children }: { children: ReactNode }) {
    return (
      <QueryClientProvider client={qc}>
        <SidebarProvider>
          <SelectedSessionProvider>{children}</SelectedSessionProvider>
        </SidebarProvider>
      </QueryClientProvider>
    )
  }

  render(<ChatSidebarGroup />, { wrapper: clientWrapper })
  // The cached first-user-message content (truncated to 30 chars) is
  // surfaced as the row's label.
  expect(await screen.findByText(/How do I migrate the database/)).toBeInTheDocument()
})
