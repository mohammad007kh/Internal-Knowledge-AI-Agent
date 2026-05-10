/**
 * Sticky always-visible save bar.
 *
 * Replaces the old dirty-conditional reveal. The bar is always rendered;
 * Save is disabled until at least one field is dirty. The "N unsaved
 * changes" count drives off `formState.dirtyFields`. Discard restores
 * pristine state without leaving the bar in a stuck "dirty" appearance.
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
    updateSourceApi: (id: string, body: UpdateSourceRequest) => updateSourceMock(id, body),
    triggerSyncApi: vi.fn(),
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

function makeSource(overrides: Partial<SourceDetail> = {}): SourceDetail {
  return {
    id: 'src-1',
    name: 'Wiki',
    // Use a web source so all editable fields (including sync_mode dropdown)
    // are visible — gives the test the most surface to dirty.
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
  getSourceMock.mockReset()
  getStatsMock.mockReset()
  listSyncJobsMock.mockReset()
  listDocumentsMock.mockReset()

  getSourceMock.mockResolvedValue(makeSource())
  getStatsMock.mockResolvedValue({
    document_count: 0,
    chunk_count: 0,
    last_synced_at: null,
    sync_job_count: 0,
  })
  listSyncJobsMock.mockResolvedValue({ items: [], total: 0, limit: 20, offset: 0 })
  listDocumentsMock.mockResolvedValue({ items: [], total: 0, limit: 50, offset: 0 })
  updateSourceMock.mockImplementation(async (id, body) => ({
    ...makeSource({ id }),
    ...body,
  } as SourceDetail))
})

afterEach(() => {
  vi.clearAllMocks()
})

describe('SettingsSaveBar', () => {
  it('is always rendered, even on initial load with a pristine form', async () => {
    renderPage()
    await openSettings()

    const bar = await screen.findByTestId('settings-save-bar')
    expect(bar).toBeInTheDocument()
    expect(bar).toHaveAttribute('data-dirty', 'false')
    expect(screen.getByTestId('settings-save')).toBeInTheDocument()
    expect(screen.getByTestId('settings-discard')).toBeInTheDocument()
  })

  it('disables Save and reads "No unsaved changes" when pristine', async () => {
    renderPage()
    await openSettings()

    expect(screen.getByTestId('settings-save')).toBeDisabled()
    expect(screen.getByTestId('settings-discard')).toBeDisabled()
    expect(screen.getByTestId('settings-save-bar-summary')).toHaveTextContent(
      /no unsaved changes/i
    )
  })

  it('enables Save and shows "1 unsaved change" when one field is dirty', async () => {
    renderPage()
    const user = await openSettings()

    const form = await screen.findByRole('form', { name: /edit source settings/i })
    const nameField = within(form).getByLabelText('Name')
    await user.type(nameField, ' (v2)')

    await waitFor(() => expect(screen.getByTestId('settings-save')).not.toBeDisabled())
    await waitFor(() =>
      expect(screen.getByTestId('settings-save-bar-summary')).toHaveTextContent(
        /1 unsaved change/i
      )
    )
    expect(screen.getByTestId('settings-save-bar')).toHaveAttribute('data-dirty', 'true')
  })

  it('shows plural "N unsaved changes" when multiple fields are dirty', async () => {
    renderPage()
    const user = await openSettings()

    const form = await screen.findByRole('form', { name: /edit source settings/i })
    await user.type(within(form).getByLabelText('Name'), ' (v2)')
    await user.clear(within(form).getByLabelText('Description'))
    await user.type(within(form).getByLabelText('Description'), 'New description')

    await waitFor(() =>
      expect(screen.getByTestId('settings-save-bar-summary')).toHaveTextContent(
        /2 unsaved changes/i
      )
    )
  })

  it('Discard restores pristine state and re-disables Save', async () => {
    renderPage()
    const user = await openSettings()

    const form = await screen.findByRole('form', { name: /edit source settings/i })
    const nameField = within(form).getByLabelText('Name') as HTMLInputElement
    const original = nameField.value
    await user.type(nameField, ' (v2)')

    await waitFor(() => expect(screen.getByTestId('settings-save')).not.toBeDisabled())

    await user.click(screen.getByTestId('settings-discard'))

    await waitFor(() => expect(nameField.value).toBe(original))
    expect(screen.getByTestId('settings-save')).toBeDisabled()
    expect(screen.getByTestId('settings-save-bar-summary')).toHaveTextContent(
      /no unsaved changes/i
    )
  })
})
