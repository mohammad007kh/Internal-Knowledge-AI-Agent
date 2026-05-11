/**
 * Locks down the U3 contract: the "AI Description" Card no longer lives on
 * the Overview tab. The Regenerate-description / Regenerate-name+description
 * buttons are gone from Overview entirely; the new flow lives on the Settings
 * tab via the AI naming assistant card.
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
})

afterEach(() => {
  vi.clearAllMocks()
})

describe('Overview tab — AI Description card removed', () => {
  it('does NOT render an "AI Description" CardTitle on the Overview tab', async () => {
    renderPage()

    // Overview is the default active tab.
    await waitFor(() =>
      expect(screen.getByRole('tab', { name: 'Overview' })).toHaveAttribute(
        'data-state',
        'active'
      )
    )

    expect(screen.queryByText(/^AI Description$/i)).toBeNull()
  })

  it('does NOT render the legacy Refresh-description / Regenerate-name+description buttons on Overview', async () => {
    renderPage()
    await waitFor(() =>
      expect(screen.getByRole('tab', { name: 'Overview' })).toBeInTheDocument()
    )

    expect(
      screen.queryByRole('button', { name: /^refresh description$/i })
    ).toBeNull()
    expect(
      screen.queryByRole('button', { name: /regenerate name \+ description/i })
    ).toBeNull()
  })

  it('renders the AI naming assistant card on the Settings tab instead', async () => {
    const user = userEvent.setup()
    renderPage()

    await waitFor(() =>
      expect(screen.getByRole('tab', { name: 'Settings' })).toBeInTheDocument()
    )
    await user.click(screen.getByRole('tab', { name: 'Settings' }))

    expect(await screen.findByTestId('ai-naming-card')).toBeInTheDocument()
    expect(
      screen.getByTestId('ai-naming-regenerate-description')
    ).toBeInTheDocument()
    expect(screen.getByTestId('ai-naming-regenerate-both')).toBeInTheDocument()
  })
})
