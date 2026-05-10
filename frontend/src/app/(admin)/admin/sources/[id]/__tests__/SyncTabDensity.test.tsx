/**
 * Sync tab density redesign (U1).
 *
 * Asserts the structural changes:
 *   - The standalone "Actions" Card is gone.
 *   - The inline header band exists with both Sync now + Test connection
 *     buttons (when applicable).
 *   - The collapsed config metadata strip starts collapsed and expands on
 *     click. Edit-in-Settings link is present once expanded.
 *   - Sync history rows use the tighter `py-2.5` padding (smoke check).
 *   - The "Showing X-Y of N" counter renders next to the section h3 (not
 *     in the footer).
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
import { render, screen, waitFor, within } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import type { ReactNode } from 'react'
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'

const updateSourceMock =
  vi.fn<(id: string, body: UpdateSourceRequest) => Promise<SourceDetail>>()
const triggerSyncMock = vi.fn<(id: string) => Promise<SyncJob>>()
const testConnectionMock = vi.fn<(id: string) => Promise<TestConnectionResponse>>()
const listSyncJobsMock =
  vi.fn<(id: string, limit?: number, offset?: number) => Promise<PaginatedSyncJobs>>()
const listDocumentsMock =
  vi.fn<(id: string, limit?: number, offset?: number) => Promise<PaginatedDocuments>>()
const getSourceMock = vi.fn<(id: string) => Promise<SourceDetail>>()
const getStatsMock = vi.fn<(id: string) => Promise<SourceStats>>()

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
    updateSourceApi: (id: string, body: UpdateSourceRequest) =>
      updateSourceMock(id, body),
    triggerSyncApi: (id: string) => triggerSyncMock(id),
    testConnectionApi: (id: string) => testConnectionMock(id),
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

function makeSource(overrides: Partial<SourceDetail> = {}): SourceDetail {
  return {
    id: 'src-1',
    name: 'Web wiki',
    source_type: 'web_url',
    is_active: true,
    created_at: '2026-01-01T00:00:00Z',
    source_mode: 'snapshot',
    retrieval_mode: 'vector_only',
    description: 'Internal docs',
    sync_mode: 'manual',
    sync_schedule: null,
    last_synced_at: null,
    status: 'ready',
    citations_enabled: true,
    updated_at: '2026-01-01T00:00:00Z',
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

async function openSyncTab() {
  const user = userEvent.setup()
  await waitFor(() =>
    expect(screen.getByRole('tab', { name: 'Sync' })).toBeInTheDocument()
  )
  await user.click(screen.getByRole('tab', { name: 'Sync' }))
  await screen.findByTestId('sync-header-band')
  return user
}

beforeEach(() => {
  updateSourceMock.mockReset()
  triggerSyncMock.mockReset()
  testConnectionMock.mockReset()
  listSyncJobsMock.mockReset()
  listDocumentsMock.mockReset()
  getSourceMock.mockReset()
  getStatsMock.mockReset()

  getSourceMock.mockResolvedValue(makeSource())
  getStatsMock.mockResolvedValue({
    document_count: 0,
    chunk_count: 0,
    last_synced_at: null,
    sync_job_count: 0,
  })
  listDocumentsMock.mockResolvedValue({ items: [], total: 0, limit: 50, offset: 0 })
  listSyncJobsMock.mockResolvedValue({ items: [], total: 0, limit: 20, offset: 0 })
  testConnectionMock.mockResolvedValue({ success: true, message: 'ok' })
})

afterEach(() => {
  vi.clearAllMocks()
})

describe('Sync tab — density redesign U1', () => {
  it('does NOT render a CardHeader-titled "Actions" card on the Sync tab', async () => {
    renderPage()
    await openSyncTab()

    // Old layout had `<CardTitle>Actions</CardTitle>` at the top of the
    // Sync tab. Make sure no element on the page renders that exact text.
    expect(screen.queryByText(/^Actions$/i)).toBeNull()
  })

  it('renders the inline header band with Sync now + Test connection', async () => {
    renderPage()
    await openSyncTab()

    const band = await screen.findByTestId('sync-header-band')
    expect(within(band).getByRole('button', { name: /sync source web wiki now/i })).toBeInTheDocument()
    expect(within(band).getByRole('button', { name: /test connection/i })).toBeInTheDocument()
  })

  it('hides Test connection in the band when source is not testable', async () => {
    getSourceMock.mockResolvedValue(makeSource({ source_type: 'file_upload' }))
    renderPage()
    await openSyncTab()

    const band = await screen.findByTestId('sync-header-band')
    expect(
      within(band).queryByRole('button', { name: /test connection/i })
    ).toBeNull()
  })

  it('renders the config metadata strip COLLAPSED by default with a chevron', async () => {
    renderPage()
    await openSyncTab()

    const strip = await screen.findByTestId('sync-config-strip')
    expect(strip).toHaveAttribute('data-expanded', 'false')

    // Body / "Edit in Settings" link should NOT be visible when collapsed.
    expect(screen.queryByTestId('sync-config-edit-in-settings')).toBeNull()

    const toggle = within(strip).getByTestId('sync-config-strip-toggle')
    expect(toggle).toHaveAttribute('aria-expanded', 'false')
  })

  it('expands the config strip when its toggle is clicked', async () => {
    renderPage()
    const user = await openSyncTab()

    const strip = await screen.findByTestId('sync-config-strip')
    const toggle = within(strip).getByTestId('sync-config-strip-toggle')
    await user.click(toggle)

    await waitFor(() => expect(strip).toHaveAttribute('data-expanded', 'true'))
    expect(toggle).toHaveAttribute('aria-expanded', 'true')
    expect(screen.getByTestId('sync-config-edit-in-settings')).toBeInTheDocument()
  })

  it('Edit-in-Settings link switches the active tab to Settings', async () => {
    renderPage()
    const user = await openSyncTab()

    const strip = await screen.findByTestId('sync-config-strip')
    await user.click(within(strip).getByTestId('sync-config-strip-toggle'))

    await user.click(screen.getByTestId('sync-config-edit-in-settings'))

    await waitFor(() =>
      expect(screen.getByRole('tab', { name: 'Settings' })).toHaveAttribute(
        'data-state',
        'active'
      )
    )
  })

  it('renders the "Showing X–Y of N" counter next to the section heading (not in footer)', async () => {
    listSyncJobsMock.mockImplementation(async (_id, limit = 20, offset = 0) => ({
      items: Array.from({ length: Math.min(limit, 25 - offset) }, (_, i) => ({
        id: `job-${offset + i}`,
        source_id: 'src-1',
        status: 'success' as const,
        started_at: '2026-05-09T00:00:00Z',
        finished_at: null,
        completed_at: null,
        error_message: null,
        documents_synced: 0,
        documents_indexed: 0,
        chunks_created: 0,
        created_at: '2026-05-09T00:00:00Z',
        updated_at: '2026-05-09T00:00:00Z',
      })),
      total: 25,
      limit,
      offset,
    }))

    renderPage()
    await openSyncTab()

    const summary = await screen.findByTestId('sync-jobs-page-summary')
    expect(summary).toHaveTextContent('Showing 1–20 of 25')
    // The counter must live alongside the section heading, not inside the
    // pagination footer. Walk the DOM and assert the closest <h3> sibling.
    const heading = summary.parentElement?.querySelector('h3')
    expect(heading?.textContent).toMatch(/sync history/i)
  })

  it('uses the tightened py-2.5 padding on history rows', async () => {
    listSyncJobsMock.mockResolvedValue({
      items: [
        {
          id: 'job-1',
          source_id: 'src-1',
          status: 'success',
          started_at: '2026-05-09T00:00:00Z',
          finished_at: null,
          completed_at: null,
          error_message: null,
          documents_synced: 0,
          documents_indexed: 0,
          chunks_created: 0,
          created_at: '2026-05-09T00:00:00Z',
          updated_at: '2026-05-09T00:00:00Z',
        },
      ],
      total: 1,
      limit: 20,
      offset: 0,
    })

    renderPage()
    await openSyncTab()

    const row = await screen.findByTestId('sync-jobs-row')
    // Tailwind class assertion: the row should carry py-2.5 (tightened from
    // the previous py-3). This locks the density change at the markup level.
    expect(row.className).toMatch(/py-2\.5/)
  })
})
