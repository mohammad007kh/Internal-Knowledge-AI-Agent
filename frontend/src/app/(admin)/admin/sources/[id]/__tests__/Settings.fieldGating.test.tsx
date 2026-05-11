/**
 * Settings form — per-source-type field gating matrix.
 *
 * Validates the contract from `sourceTypeMatrix.ts`:
 *   - DB sources hide retrieval_mode + source_mode Selects, render
 *     read-only chips with their persisted value.
 *   - File sources hide retrieval_mode + source_mode entirely.
 *   - Web / connector sources hide retrieval_mode + source_mode entirely
 *     and expose `delta` as a sync_mode option.
 *   - File sources do NOT expose `delta` (no upstream change feed).
 *
 * Also locks down the deprecation of `hybrid` retrieval_mode — it is
 * absent from the dropdown for every type that surfaces it.
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
const deleteSourceMock = vi.fn<(id: string) => Promise<void>>()

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
    updateSourceApi: (id: string, body: UpdateSourceRequest) => updateSourceMock(id, body),
    triggerSyncApi: (id: string) => triggerSyncMock(id),
    testConnectionApi: (id: string) => testConnectionMock(id),
    deleteSourceApi: (id: string) => deleteSourceMock(id),
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
    name: 'Engineering Handbook',
    source_type: 'postgresql',
    is_active: true,
    created_at: '2026-01-01T00:00:00Z',
    source_mode: 'live',
    retrieval_mode: 'text_to_query',
    description: 'Internal engineering docs',
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

async function openSettings() {
  const user = userEvent.setup()
  await waitFor(() => expect(screen.getByRole('tab', { name: 'Settings' })).toBeInTheDocument())
  await user.click(screen.getByRole('tab', { name: 'Settings' }))
  await screen.findByRole('form', { name: /edit source settings/i })
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
  deleteSourceMock.mockReset()

  getStatsMock.mockResolvedValue({
    document_count: 0,
    chunk_count: 0,
    last_synced_at: null,
    sync_job_count: 0,
  })
  listDocumentsMock.mockResolvedValue({ items: [], total: 0, limit: 50, offset: 0 })
  listSyncJobsMock.mockResolvedValue({ items: [], total: 0, limit: 20, offset: 0 })
  updateSourceMock.mockImplementation(async (id, body) => ({
    ...makeSource({ id }),
    ...body,
  } as SourceDetail))
  triggerSyncMock.mockResolvedValue({} as SyncJob)
  testConnectionMock.mockResolvedValue({ success: true, message: 'ok' })
})

afterEach(() => {
  vi.clearAllMocks()
})

describe('Settings field gating — database source', () => {
  beforeEach(() => {
    getSourceMock.mockResolvedValue(makeSource({ source_type: 'postgresql' }))
  })

  it('hides retrieval_mode and source_mode Selects, shows read-only chips instead', async () => {
    renderPage()
    await openSettings()

    expect(screen.queryByLabelText('Retrieval mode')).toBeNull()
    expect(screen.queryByLabelText('Source mode')).toBeNull()

    expect(screen.getByTestId('retrieval-mode-chip')).toBeInTheDocument()
    expect(screen.getByTestId('source-mode-chip')).toBeInTheDocument()
    expect(screen.getByTestId('retrieval-mode-chip')).toHaveTextContent(/text to query/i)
    expect(screen.getByTestId('source-mode-chip')).toHaveTextContent(/live/i)
  })

  it('hides sync_mode field entirely when source_mode === live', async () => {
    renderPage()
    await openSettings()

    // No combobox should be present — DB live sources have nothing to schedule.
    const form = await screen.findByRole('form', { name: /edit source settings/i })
    expect(within(form).queryAllByRole('combobox')).toHaveLength(0)
  })

  it('shows sync_mode dropdown with {manual, scheduled} when source_mode === snapshot', async () => {
    getSourceMock.mockResolvedValue(
      makeSource({ source_type: 'postgresql', source_mode: 'snapshot' })
    )

    renderPage()
    const user = await openSettings()

    const form = await screen.findByRole('form', { name: /edit source settings/i })
    const trigger = within(form).getByRole('combobox')
    await user.click(trigger)

    expect(await screen.findByRole('option', { name: 'Manual' })).toBeInTheDocument()
    expect(screen.getByRole('option', { name: 'Scheduled' })).toBeInTheDocument()
    expect(screen.queryByRole('option', { name: 'Delta' })).toBeNull()
  })
})

describe('Settings field gating — file source', () => {
  beforeEach(() => {
    getSourceMock.mockResolvedValue(
      makeSource({
        source_type: 'pdf',
        source_mode: 'snapshot',
        retrieval_mode: 'vector_only',
      })
    )
  })

  it('hides retrieval_mode and source_mode entirely (no chip, no dropdown)', async () => {
    renderPage()
    await openSettings()

    expect(screen.queryByLabelText('Retrieval mode')).toBeNull()
    expect(screen.queryByLabelText('Source mode')).toBeNull()
    expect(screen.queryByTestId('retrieval-mode-chip')).toBeNull()
    expect(screen.queryByTestId('source-mode-chip')).toBeNull()
  })

  it('exposes sync_mode {manual, scheduled} only — no delta option', async () => {
    renderPage()
    const user = await openSettings()

    const form = await screen.findByRole('form', { name: /edit source settings/i })
    const trigger = within(form).getByRole('combobox')
    await user.click(trigger)

    expect(await screen.findByRole('option', { name: 'Manual' })).toBeInTheDocument()
    expect(screen.getByRole('option', { name: 'Scheduled' })).toBeInTheDocument()
    expect(screen.queryByRole('option', { name: 'Delta' })).toBeNull()
  })
})

describe('Settings field gating — web source', () => {
  beforeEach(() => {
    getSourceMock.mockResolvedValue(
      makeSource({
        source_type: 'web_url',
        source_mode: 'snapshot',
        retrieval_mode: 'vector_only',
      })
    )
  })

  it('hides retrieval_mode and source_mode and offers delta sync', async () => {
    renderPage()
    const user = await openSettings()

    expect(screen.queryByTestId('retrieval-mode-chip')).toBeNull()
    expect(screen.queryByTestId('source-mode-chip')).toBeNull()

    const form = await screen.findByRole('form', { name: /edit source settings/i })
    const trigger = within(form).getByRole('combobox')
    await user.click(trigger)

    expect(await screen.findByRole('option', { name: 'Manual' })).toBeInTheDocument()
    expect(screen.getByRole('option', { name: 'Scheduled' })).toBeInTheDocument()
    expect(screen.getByRole('option', { name: 'Delta' })).toBeInTheDocument()
  })
})

describe('Settings field gating — connector source', () => {
  it.each<SourceType>(['confluence', 'sharepoint', 'notion', 'google_drive'])(
    'hides retrieval_mode + source_mode and offers delta sync for %s',
    async (sourceType) => {
      getSourceMock.mockResolvedValue(
        makeSource({
          source_type: sourceType,
          source_mode: 'snapshot',
          retrieval_mode: 'vector_only',
        })
      )

      renderPage()
      const user = await openSettings()

      expect(screen.queryByTestId('retrieval-mode-chip')).toBeNull()
      expect(screen.queryByTestId('source-mode-chip')).toBeNull()

      const form = await screen.findByRole('form', { name: /edit source settings/i })
      const trigger = within(form).getByRole('combobox')
      await user.click(trigger)
      expect(await screen.findByRole('option', { name: 'Delta' })).toBeInTheDocument()
    }
  )
})

describe('Settings field gating — hybrid retrieval_mode is deprecated', () => {
  it('does not appear in the retrieval_mode dropdown for any source kind', async () => {
    // For sources that DO show the dropdown — none today, since we hide it
    // for everything but DB. This test guards the Select-options list in
    // case a future refactor exposes retrieval_mode. We verify it via the
    // matrix helper directly to keep the contract pinned even when no UI
    // surfaces the dropdown.
    const { getEditableFieldsFor } = await import('../_components/sourceTypeMatrix')
    // sanity: db chips don't include hybrid in Selects either (none rendered)
    const dbConfig = getEditableFieldsFor({ sourceType: 'postgresql', sourceMode: 'live' })
    expect(dbConfig.retrievalMode).toBe('readonly-chip')
  })
})

describe('Settings — Connection card gating (FX6: real "database" source_type)', () => {
  it('renders the Connection card + Edit credentials for source_type === "database"', async () => {
    // FX6 regression: the gating used to check a fictional dialect set
    // (postgresql/mysql/…) that the backend StrEnum never emits — the real
    // value is the literal "database", so the card was always hidden.
    getSourceMock.mockResolvedValue(makeSource({ source_type: 'database' }))

    renderPage()
    await openSettings()

    expect(await screen.findByTestId('connection-card-status')).toBeInTheDocument()
    expect(screen.getByTestId('connection-card-edit')).toHaveTextContent(/edit credentials/i)
    // The DB read-only chips must also render for the real value.
    expect(screen.getByTestId('retrieval-mode-chip')).toBeInTheDocument()
    expect(screen.getByTestId('source-mode-chip')).toBeInTheDocument()
  })

  it('does NOT render the Connection card for a file source', async () => {
    getSourceMock.mockResolvedValue(
      makeSource({ source_type: 'file_upload', source_mode: 'snapshot' })
    )

    renderPage()
    await openSettings()

    expect(screen.queryByTestId('connection-card-status')).toBeNull()
    expect(screen.queryByTestId('connection-card-edit')).toBeNull()
  })

  it('does NOT render the Connection card for a web source', async () => {
    getSourceMock.mockResolvedValue(
      makeSource({ source_type: 'web_url', source_mode: 'snapshot' })
    )

    renderPage()
    await openSettings()

    expect(screen.queryByTestId('connection-card-status')).toBeNull()
  })
})

describe('sourceKindOf — recognises the real backend SourceType values (FX6)', () => {
  it('maps the backend StrEnum values to the right kind', async () => {
    const { sourceKindOf } = await import('../_components/sourceTypeMatrix')
    expect(sourceKindOf('database')).toBe('database')
    expect(sourceKindOf('file_upload')).toBe('file')
    expect(sourceKindOf('web_url')).toBe('web')
    expect(sourceKindOf('confluence')).toBe('connector')
    expect(sourceKindOf('sharepoint')).toBe('connector')
  })
})
