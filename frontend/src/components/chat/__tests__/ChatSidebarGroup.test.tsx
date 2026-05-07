import { SidebarProvider } from '@/components/dashboard/SidebarProvider'
import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import { render, screen } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
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
