/**
 * Test tab — admin-only sandbox chat surface.
 *
 * Validates:
 *   - Banner copy is present.
 *   - Empty state lists per-source-type starter prompts.
 *   - Source-state warnings render with correct tone.
 *   - Non-admin users see the "admin-only" gate.
 *   - Schema-failed DB sources disable the input.
 */
import type {
  PaginatedDocuments,
  PaginatedSyncJobs,
  SourceDetail,
  SourceStats,
  SyncJob,
  TestConnectionResponse,
  UpdateSourceRequest,
} from '@/lib/api/sources'
import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import { render, screen, waitFor } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import type { ReactNode } from 'react'
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'

// ---------------------------------------------------------------------------
// Mocks
// ---------------------------------------------------------------------------

const useAuthMock = vi.fn()

vi.mock('@/features/auth/context/AuthContext', () => ({
  useAuth: () => useAuthMock(),
  AuthProvider: ({ children }: { children: ReactNode }) => <>{children}</>,
}))

const getSourceMock = vi.fn<(id: string) => Promise<SourceDetail>>()
const getStatsMock = vi.fn<(id: string) => Promise<SourceStats>>()
const listSyncJobsMock =
  vi.fn<(id: string, limit?: number, offset?: number) => Promise<PaginatedSyncJobs>>()
const listDocumentsMock =
  vi.fn<(id: string, limit?: number, offset?: number) => Promise<PaginatedDocuments>>()

vi.mock('@/lib/api/sources', async (importOriginal) => {
  const actual = await importOriginal<typeof import('@/lib/api/sources')>()
  return {
    ...actual,
    getSourceApi: (id: string) => getSourceMock(id),
    getSourceStatsApi: (id: string) => getStatsMock(id),
    listSyncJobsApi: (id: string, limit?: number, offset?: number) =>
      listSyncJobsMock(id, limit, offset),
    listSourceDocumentsApi: (id: string, limit?: number, offset?: number) =>
      listDocumentsMock(id, limit, offset),
    updateSourceApi: vi.fn<(id: string, body: UpdateSourceRequest) => Promise<SourceDetail>>(),
    triggerSyncApi: vi.fn<(id: string) => Promise<SyncJob>>(),
    testConnectionApi: vi.fn<(id: string) => Promise<TestConnectionResponse>>(),
    deleteSourceApi: vi.fn(),
    refreshDescriptionApi: vi.fn(),
    autoNameApi: vi.fn(),
  }
})

vi.mock('next/navigation', () => ({
  useRouter: () => ({
    push: vi.fn(),
    replace: vi.fn(),
    back: vi.fn(),
    forward: vi.fn(),
    refresh: vi.fn(),
    prefetch: vi.fn(),
  }),
  useParams: () => ({ id: 'src-1' }),
  usePathname: () => '/admin/sources/src-1',
  useSearchParams: () => new URLSearchParams(),
}))

vi.mock('sonner', () => ({
  toast: { success: vi.fn(), error: vi.fn() },
}))

import SourceDetailPage from '../page'

// ---------------------------------------------------------------------------
// Fixtures
// ---------------------------------------------------------------------------

function makeSource(overrides: Partial<SourceDetail> = {}): SourceDetail {
  return {
    id: 'src-1',
    name: 'Wiki',
    source_type: 'web_url',
    is_active: true,
    created_at: '2026-01-01T00:00:00Z',
    source_mode: 'snapshot',
    retrieval_mode: 'vector_only',
    description: 'Internal wiki',
    sync_mode: 'manual',
    sync_schedule: null,
    last_synced_at: null,
    status: 'ready',
    citations_enabled: true,
    updated_at: '2026-01-01T00:00:00Z',
    owner_email: null,
    schema_summary: null,
    ...overrides,
  } satisfies SourceDetail
}

function renderPage(): ReturnType<typeof render> {
  const client = new QueryClient({
    defaultOptions: { queries: { retry: false }, mutations: { retry: false } },
  })
  function Wrapper({ children }: { children: ReactNode }) {
    return <QueryClientProvider client={client}>{children}</QueryClientProvider>
  }
  return render(<SourceDetailPage />, { wrapper: Wrapper })
}

async function openTestTab() {
  const user = userEvent.setup()
  await waitFor(() => expect(screen.getByRole('tab', { name: 'Test' })).toBeInTheDocument())
  await user.click(screen.getByRole('tab', { name: 'Test' }))
  return user
}

// ---------------------------------------------------------------------------
// Setup
// ---------------------------------------------------------------------------

beforeEach(() => {
  useAuthMock.mockReset()
  getSourceMock.mockReset()
  getStatsMock.mockReset()
  listSyncJobsMock.mockReset()
  listDocumentsMock.mockReset()

  // Default: admin user.
  useAuthMock.mockReturnValue({
    user: { id: 'u-1', email: 'admin@example.com', role: 'admin', must_change_password: false },
    accessToken: 'tok',
    isLoading: false,
    setAccessToken: vi.fn(),
    clearAccessToken: vi.fn(),
  })

  getSourceMock.mockResolvedValue(makeSource())
  getStatsMock.mockResolvedValue({
    document_count: 0,
    chunk_count: 0,
    last_synced_at: null,
    sync_job_count: 0,
  })
  listSyncJobsMock.mockResolvedValue({ items: [], total: 0, limit: 20, offset: 0 })
  listDocumentsMock.mockResolvedValue({ items: [], total: 0, limit: 50, offset: 0 })
})

afterEach(() => {
  vi.clearAllMocks()
})

// ---------------------------------------------------------------------------
// Tests
// ---------------------------------------------------------------------------

describe('TestTab — banner + empty state', () => {
  it('renders the "one-off conversation" banner', async () => {
    renderPage()
    await openTestTab()

    const banner = await screen.findByTestId('sandbox-banner')
    expect(banner).toHaveTextContent(/one-off conversation/i)
    expect(banner).toHaveTextContent(/aren't saved to history/i)
  })

  it('shows empty state heading and 3 starter prompts', async () => {
    renderPage()
    await openTestTab()

    const empty = await screen.findByTestId('sandbox-empty-state')
    expect(empty).toHaveTextContent(/Try a question against this source/i)
    expect(screen.getAllByTestId('sandbox-starter')).toHaveLength(3)
  })

  it('starter prompts branch on source type — file source', async () => {
    getSourceMock.mockResolvedValue(makeSource({ source_type: 'pdf' }))
    renderPage()
    await openTestTab()

    const starters = await screen.findAllByTestId('sandbox-starter')
    expect(starters[0]).toHaveTextContent(/most recent document/i)
  })

  it('starter prompts branch on source type — database source', async () => {
    getSourceMock.mockResolvedValue(
      makeSource({ source_type: 'postgresql', source_mode: 'live', retrieval_mode: 'text_to_query' })
    )
    renderPage()
    await openTestTab()

    const starters = await screen.findAllByTestId('sandbox-starter')
    expect(starters[0]).toHaveTextContent(/tables exist/i)
  })

  it('starter prompts branch on source type — web/connector', async () => {
    getSourceMock.mockResolvedValue(makeSource({ source_type: 'web_url' }))
    renderPage()
    await openTestTab()

    const starters = await screen.findAllByTestId('sandbox-starter')
    expect(starters[0]).toHaveTextContent(/most recent page/i)
  })
})

describe('TestTab — source-state warnings', () => {
  it('renders red banner when connection_status === failed', async () => {
    getSourceMock.mockResolvedValue(makeSource({ connection_status: 'failed' }))
    renderPage()
    await openTestTab()

    const warnings = await screen.findByTestId('sandbox-warnings')
    expect(warnings).toHaveTextContent(/marked unavailable/i)
    const red = warnings.querySelector('[data-tone="red"]')
    expect(red).not.toBeNull()
  })

  it('renders amber banner when connection_status === degraded', async () => {
    getSourceMock.mockResolvedValue(makeSource({ connection_status: 'degraded' }))
    renderPage()
    await openTestTab()

    const warnings = await screen.findByTestId('sandbox-warnings')
    expect(warnings).toHaveTextContent(/Recent failures/i)
    const amber = warnings.querySelector('[data-tone="amber"]')
    expect(amber).not.toBeNull()
  })

  it('disables the Test tab when DB schema_status === FAILED (U14 lifecycle gate)', async () => {
    // U14: when the schema study failed the source is not "ready", so the
    // Test tab itself is disabled at the trigger level — the user can't
    // reach the sandbox at all. The richer in-tab "Schema study failed"
    // banner is still rendered when the tab IS reachable (e.g. on a
    // re-study transition), but the lifecycle gate is the user-facing
    // truth: no chat against a broken source.
    getSourceMock.mockResolvedValue(
      makeSource({
        source_type: 'postgresql',
        source_mode: 'live',
        retrieval_mode: 'text_to_query',
        schema_status: 'FAILED',
      })
    )
    renderPage()
    await waitFor(() => expect(screen.getByRole('tab', { name: 'Test' })).toBeInTheDocument())
    const trigger = screen.getByRole('tab', { name: 'Test' })
    expect(trigger).toBeDisabled()
  })

  it('renders neutral info banner when source.is_active === false', async () => {
    getSourceMock.mockResolvedValue(makeSource({ is_active: false }))
    renderPage()
    await openTestTab()

    const warnings = await screen.findByTestId('sandbox-warnings')
    // Rendered copy reads "This source isn't yet approved for users…" so we
    // match the unambiguous "yet approved for users" substring.
    expect(warnings).toHaveTextContent(/yet approved for users/i)
  })
})

describe('TestTab — admin-only gate', () => {
  it('renders the gate when current user is not admin', async () => {
    useAuthMock.mockReturnValue({
      user: { id: 'u-1', email: 'user@example.com', role: 'user', must_change_password: false },
      accessToken: 'tok',
      isLoading: false,
      setAccessToken: vi.fn(),
      clearAccessToken: vi.fn(),
    })

    renderPage()
    await openTestTab()

    expect(await screen.findByText(/Test mode is admin-only/i)).toBeInTheDocument()
    expect(screen.queryByTestId('sandbox-banner')).toBeNull()
    expect(screen.queryByTestId('sandbox-empty-state')).toBeNull()
  })

  it('renders the gate when there is no authenticated user', async () => {
    useAuthMock.mockReturnValue({
      user: null,
      accessToken: null,
      isLoading: false,
      setAccessToken: vi.fn(),
      clearAccessToken: vi.fn(),
    })

    renderPage()
    await openTestTab()

    expect(await screen.findByText(/Test mode is admin-only/i)).toBeInTheDocument()
  })
})
