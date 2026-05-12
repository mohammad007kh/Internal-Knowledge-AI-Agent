/**
 * U10 — enriched DB-source Overview tab.
 *
 * Covers the new <DatabaseOverview> block rendered for database sources:
 * the AI-description hero (prose / shimmer / empty-state + provenance),
 * the schema stat + "View schema →" tab-jump, the "what the agent sees"
 * teaser (not-studied / failed branches + Re-study button → sync mutation),
 * the Access stat (0-users vs n-users copy), the meta footer (owner_email
 * gated "by …" clause), and the non-DB negative case (file source still
 * gets FileTypeOverview, none of the new DB cards render).
 *
 * The hooks are mocked at the API-client boundary so the production React
 * Query semantics run; `next/navigation` + `sonner` are stubbed as in the
 * sibling page tests.
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

const getSourceMock = vi.fn<(id: string) => Promise<SourceDetail>>()
const getStatsMock = vi.fn<(id: string) => Promise<SourceStats>>()
const listSyncJobsMock =
  vi.fn<(id: string, limit?: number, offset?: number) => Promise<PaginatedSyncJobs>>()
const listDocumentsMock =
  vi.fn<(id: string, limit?: number, offset?: number) => Promise<PaginatedDocuments>>()
const triggerSyncMock = vi.fn<(id: string) => Promise<SyncJob>>()
const listPermissionsMock = vi.fn<(id: string) => Promise<string[]>>()

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
    triggerSyncApi: (id: string) => triggerSyncMock(id),
    listSourcePermissionsApi: (id: string) => listPermissionsMock(id),
    updateSourceApi: vi.fn<(id: string, body: UpdateSourceRequest) => Promise<SourceDetail>>(),
    testConnectionApi: vi.fn<(id: string) => Promise<TestConnectionResponse>>(),
    deleteSourceApi: vi.fn(),
    refreshDescriptionApi: vi.fn(),
    autoNameApi: vi.fn(),
    // SchemaViewer mounts on the Schema tab; default to its empty-state path
    // so the "click View schema → Schema tab visible" assertion is stable.
    getSchemaDocumentApi: () => Promise.reject(new actual.SchemaDocumentNotFoundError()),
    emitSamplesRevealedApi: vi.fn(),
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

function makeSource(overrides: Partial<SourceDetail> = {}): SourceDetail {
  return {
    id: 'src-1',
    name: 'Reporting DB',
    source_type: 'postgresql',
    is_active: true,
    created_at: '2026-01-01T00:00:00Z',
    source_mode: 'live',
    retrieval_mode: 'text_to_query',
    description: 'Sales reporting warehouse with order, customer and product tables.',
    sync_mode: 'manual',
    sync_schedule: null,
    last_synced_at: null,
    status: 'ready',
    citations_enabled: true,
    updated_at: '2026-01-01T00:00:00Z',
    owner_email: null,
    schema_summary: null,
    description_status: 'ai_set',
    schema_status: 'READY',
    tables_documented: 12,
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

beforeEach(() => {
  getSourceMock.mockReset()
  getStatsMock.mockReset()
  listSyncJobsMock.mockReset()
  listDocumentsMock.mockReset()
  triggerSyncMock.mockReset()
  listPermissionsMock.mockReset()

  getSourceMock.mockResolvedValue(makeSource())
  getStatsMock.mockResolvedValue({
    document_count: 0,
    chunk_count: 0,
    last_synced_at: null,
    sync_job_count: 0,
  })
  listSyncJobsMock.mockResolvedValue({ items: [], total: 0, limit: 20, offset: 0 })
  listDocumentsMock.mockResolvedValue({ items: [], total: 0, limit: 50, offset: 0 })
  listPermissionsMock.mockResolvedValue([])
  triggerSyncMock.mockResolvedValue({
    id: 'job-new',
    source_id: 'src-1',
    status: 'pending',
    started_at: null,
    finished_at: null,
    completed_at: null,
    error_message: null,
    documents_synced: 0,
    documents_indexed: 0,
    chunks_created: 0,
    created_at: '2026-05-09T00:00:00Z',
    updated_at: '2026-05-09T00:00:00Z',
  })
})

afterEach(() => {
  vi.clearAllMocks()
})

async function waitForOverview() {
  await waitFor(() =>
    expect(screen.getByRole('tab', { name: 'Overview' })).toHaveAttribute('data-state', 'active')
  )
}

describe('DB Overview — hero card', () => {
  it('shows the AI description prose, the Documented schema stat and a working "View schema →" link', async () => {
    getSourceMock.mockResolvedValue(makeSource({ schema_status: 'READY', tables_documented: 12 }))
    const user = userEvent.setup()
    renderPage()
    await waitForOverview()

    expect(await screen.findByTestId('db-overview')).toBeInTheDocument()
    expect(screen.getByTestId('overview-description')).toHaveTextContent(
      /Sales reporting warehouse/i
    )
    expect(screen.getByTestId('overview-schema-stat')).toHaveTextContent(/Documented/i)

    const link = screen.getByTestId('overview-schema-view-link')
    await user.click(link)

    // The Schema tab content (SchemaViewer empty state) becomes visible.
    expect(await screen.findByTestId('schema-empty-state')).toBeInTheDocument()
    expect(screen.getByRole('tab', { name: /^Schema/i })).toHaveAttribute('data-state', 'active')
  })

  it('renders a shimmer placeholder (no prose) while description_status is pending_ai', async () => {
    getSourceMock.mockResolvedValue(
      makeSource({ description: '', description_status: 'pending_ai' })
    )
    renderPage()
    await waitForOverview()

    expect(await screen.findByTestId('overview-description-pending')).toBeInTheDocument()
    expect(screen.queryByTestId('overview-description')).toBeNull()
  })

  it('shows the "No description yet" copy + Settings link when description is empty and not pending', async () => {
    getSourceMock.mockResolvedValue(
      makeSource({ description: '', description_status: 'user_set' })
    )
    renderPage()
    await waitForOverview()

    expect(await screen.findByTestId('overview-description-empty')).toHaveTextContent(
      /No description yet/i
    )
    expect(screen.getByTestId('overview-description-empty')).toHaveTextContent(/Settings/i)
  })

  it('shows the schema_summary line when present', async () => {
    getSourceMock.mockResolvedValue(
      makeSource({ schema_summary: 'Star schema: 4 dimensions, 1 fact table.' })
    )
    renderPage()
    await waitForOverview()

    expect(await screen.findByTestId('overview-schema-summary')).toHaveTextContent(
      /Star schema: 4 dimensions/i
    )
  })
})

describe('DB Overview — sync schedule (snapshot mode)', () => {
  it('shows the cron schedule for a snapshot-mode DB source', async () => {
    getSourceMock.mockResolvedValue(
      makeSource({ source_mode: 'snapshot', sync_schedule: '0 3 * * *' })
    )
    renderPage()
    await waitForOverview()

    const line = await screen.findByTestId('overview-sync-schedule')
    expect(line).toHaveTextContent(/Synced on schedule/i)
    expect(line).toHaveTextContent('0 3 * * *')
  })

  it('does not show the schedule line for a live DB source', async () => {
    getSourceMock.mockResolvedValue(
      makeSource({ source_mode: 'live', sync_schedule: '0 3 * * *' })
    )
    renderPage()
    await waitForOverview()

    expect(await screen.findByTestId('db-overview')).toBeInTheDocument()
    expect(screen.queryByTestId('overview-sync-schedule')).toBeNull()
  })

  it('does not show the schedule line for a snapshot DB source with no schedule', async () => {
    getSourceMock.mockResolvedValue(
      makeSource({ source_mode: 'snapshot', sync_schedule: null })
    )
    renderPage()
    await waitForOverview()

    expect(await screen.findByTestId('db-overview')).toBeInTheDocument()
    expect(screen.queryByTestId('overview-sync-schedule')).toBeNull()
  })
})

describe('DB Overview — "what the agent sees" teaser', () => {
  it('schema_status null → "not studied yet" copy + Re-study button that calls triggerSyncApi once', async () => {
    getSourceMock.mockResolvedValue(makeSource({ schema_status: null, tables_documented: null }))
    const user = userEvent.setup()
    renderPage()
    await waitForOverview()

    const teaser = await screen.findByTestId('overview-agent-teaser')
    expect(teaser).toHaveTextContent(/not studied yet/i)

    const button = screen.getByTestId('overview-restudy-button')
    await user.click(button)
    await waitFor(() => expect(triggerSyncMock).toHaveBeenCalledTimes(1))
    expect(triggerSyncMock).toHaveBeenCalledWith('src-1')
  })

  it('schema_status FAILED → failure copy + Re-study button', async () => {
    getSourceMock.mockResolvedValue(
      makeSource({
        schema_status: 'FAILED',
        last_error_phase: 'CONNECTING',
        last_error_message: 'auth failed',
        tables_documented: null,
      })
    )
    renderPage()
    await waitForOverview()

    const teaser = await screen.findByTestId('overview-agent-teaser')
    expect(teaser).toHaveTextContent(/Schema study failed/i)
    expect(teaser).toHaveTextContent(/CONNECTING/i)
    expect(screen.getByTestId('overview-restudy-button')).toBeInTheDocument()
  })
})

describe('DB Overview — Access stat', () => {
  it('renders "No users granted — queryable by no one" when zero users', async () => {
    listPermissionsMock.mockResolvedValue([])
    renderPage()
    await waitForOverview()

    await waitFor(() =>
      expect(screen.getByTestId('overview-access-stat')).toHaveTextContent(
        /No users granted — queryable by no one/i
      )
    )
  })

  it('renders "{n} users granted" when there are granted users', async () => {
    listPermissionsMock.mockResolvedValue(['u1', 'u2', 'u3'])
    renderPage()
    await waitForOverview()

    await waitFor(() =>
      expect(screen.getByTestId('overview-access-stat')).toHaveTextContent(/3 users granted/i)
    )
  })
})

describe('DB Overview — meta footer', () => {
  it('includes "by {email}" when owner_email is set', async () => {
    getSourceMock.mockResolvedValue(makeSource({ owner_email: 'alice@example.com' }))
    renderPage()
    await waitForOverview()

    expect(await screen.findByTestId('overview-meta-footer')).toHaveTextContent(
      /by alice@example\.com/i
    )
  })

  it('omits the "by …" clause when owner_email is null', async () => {
    getSourceMock.mockResolvedValue(makeSource({ owner_email: null }))
    renderPage()
    await waitForOverview()

    const footer = await screen.findByTestId('overview-meta-footer')
    expect(footer).toHaveTextContent(/Created/i)
    expect(footer.textContent ?? '').not.toMatch(/ by /i)
  })
})

describe('DB Overview — non-DB source', () => {
  it('does not render any of the new DB cards for a file source; FileTypeOverview is shown', async () => {
    getSourceMock.mockResolvedValue(
      makeSource({
        source_type: 'pdf',
        source_mode: 'snapshot',
        retrieval_mode: 'vector_only',
        schema_status: null,
        tables_documented: null,
      })
    )
    renderPage()
    await waitForOverview()

    // Existing file overview is present…
    expect(await screen.findByText(/Files in this source/i)).toBeInTheDocument()
    // …and none of the new DB-only blocks render.
    expect(screen.queryByTestId('db-overview')).toBeNull()
    expect(screen.queryByTestId('overview-hero')).toBeNull()
    expect(screen.queryByTestId('overview-agent-teaser')).toBeNull()
    expect(screen.queryByTestId('overview-meta-footer')).toBeNull()
  })
})

describe('Data tab value (U10 rename: documents → schema)', () => {
  it('the data tab activates on value "schema" and keeps the "Schema" label for DB sources', async () => {
    getSourceMock.mockResolvedValue(makeSource())
    const user = userEvent.setup()
    renderPage()
    await waitForOverview()

    const schemaTab = screen.getByRole('tab', { name: /^Schema/i })
    await user.click(schemaTab)
    expect(schemaTab).toHaveAttribute('data-state', 'active')
    // SchemaViewer mounted under the renamed value.
    expect(await screen.findByTestId('schema-empty-state')).toBeInTheDocument()
  })
})
