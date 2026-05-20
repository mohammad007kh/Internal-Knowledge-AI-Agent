/**
 * Documents tab → per-type relabel.
 *
 *   File source     → "Files"
 *   Web source      → "Pages"
 *   Connector       → "Pages"
 *   Database source → "Schema"
 */
import type {
  PaginatedDocuments,
  PaginatedSyncJobs,
  SourceDetail,
  SourceStats,
  SourceType,
  SyncJob,
  TestConnectionResponse,
  UpdateSourceRequest,
} from '@/lib/api/sources'
import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import { render, screen, waitFor } from '@testing-library/react'
import type { ReactNode } from 'react'
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'

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
    // U7 — SchemaViewer is mounted by the data-tab body for DB sources.
    // Default to the empty-state path so the relabel test stays focused
    // on the tab-label assertions and doesn't make real network calls.
    getSchemaDocumentApi: () =>
      Promise.reject(new actual.SchemaDocumentNotFoundError()),
    emitSamplesRevealedApi: vi.fn(),
    // U10 — the enriched DB Overview calls useSourcePermissions → this API.
    listSourcePermissionsApi: vi.fn(async () => [] as string[]),
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
    name: 'Some source',
    source_type: 'pdf',
    is_active: true,
    created_at: '2026-01-01T00:00:00Z',
    source_mode: 'snapshot',
    retrieval_mode: 'vector_only',
    description: '',
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

beforeEach(() => {
  getSourceMock.mockReset()
  getStatsMock.mockReset()
  listSyncJobsMock.mockReset()
  listDocumentsMock.mockReset()

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

describe('Documents tab — per-type label', () => {
  const cases: Array<{ type: SourceType; expected: string }> = [
    { type: 'pdf', expected: 'Files' },
    { type: 'docx', expected: 'Files' },
    { type: 'file_upload', expected: 'Files' },
    { type: 'web_url', expected: 'Pages' },
    { type: 'confluence', expected: 'Pages' },
    { type: 'notion', expected: 'Pages' },
    { type: 'postgresql', expected: 'Schema' },
    { type: 'mysql', expected: 'Schema' },
  ]

  for (const { type, expected } of cases) {
    it(`renders "${expected}" as the data tab label for ${type}`, async () => {
      getSourceMock.mockResolvedValue(makeSource({ source_type: type }))
      renderPage()

      // Tab labels include trailing badges/counters — match using a regex
      // that anchors at the start of the accessible name.
      await waitFor(() => {
        expect(
          screen.getByRole('tab', { name: new RegExp(`^${expected}`, 'i') })
        ).toBeInTheDocument()
      })
    })
  }
})

describe('Documents tab — empty-state copy per type', () => {
  it('shows "No files uploaded yet." for file sources', async () => {
    getSourceMock.mockResolvedValue(makeSource({ source_type: 'pdf' }))
    listDocumentsMock.mockResolvedValue({ items: [], total: 0, limit: 50, offset: 0 })

    const user = (await import('@testing-library/user-event')).default.setup()
    renderPage()

    await waitFor(() => expect(screen.getByRole('tab', { name: /^Files/i })).toBeInTheDocument())
    await user.click(screen.getByRole('tab', { name: /^Files/i }))

    expect(await screen.findByTestId('data-tab-empty')).toHaveTextContent(/No files uploaded yet/i)
  })

  it('shows "No pages crawled yet." for web sources', async () => {
    getSourceMock.mockResolvedValue(makeSource({ source_type: 'web_url' }))
    listDocumentsMock.mockResolvedValue({ items: [], total: 0, limit: 50, offset: 0 })

    const user = (await import('@testing-library/user-event')).default.setup()
    renderPage()

    await waitFor(() => expect(screen.getByRole('tab', { name: /^Pages/i })).toBeInTheDocument())
    await user.click(screen.getByRole('tab', { name: /^Pages/i }))

    expect(await screen.findByTestId('data-tab-empty')).toHaveTextContent(/No pages crawled yet/i)
  })

  it('mounts the SchemaViewer for database sources (U7)', async () => {
    // U7 replaced the placeholder with the live SchemaViewer. The viewer
    // calls `getSchemaDocumentApi` on mount; the file-scope mock above
    // returns SchemaDocumentNotFoundError so the viewer falls into its
    // empty-state branch (admin-readable copy that mirrors the spirit of
    // the old placeholder). Full viewer behaviour lives in
    // _components/__tests__/SchemaViewer.test.tsx.
    getSourceMock.mockResolvedValue(
      makeSource({
        source_type: 'postgresql',
        source_mode: 'live',
        retrieval_mode: 'text_to_query',
      })
    )

    const user = (await import('@testing-library/user-event')).default.setup()
    renderPage()

    await waitFor(() => expect(screen.getByRole('tab', { name: /^Schema/i })).toBeInTheDocument())
    await user.click(screen.getByRole('tab', { name: /^Schema/i }))

    // Empty state copy from the SchemaViewer's not-yet-documented branch.
    expect(await screen.findByTestId('schema-empty-state')).toHaveTextContent(
      /Schema not yet documented/i
    )
    // Old placeholder copy must NOT come back.
    expect(screen.queryByText(/Schema details require the studying agent/i)).toBeNull()
  })
})
