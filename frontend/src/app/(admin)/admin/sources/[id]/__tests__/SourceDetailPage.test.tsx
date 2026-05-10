/**
 * Source detail page — covers the three fixes shipped together:
 *
 *   1. Sync history pagination (Previous / Next, boundary disabling).
 *   2. Sync-now + Test-connection buttons on the Sync tab (with the
 *      file-upload predicate hiding Test connection).
 *   3. Editable Settings tab — react-hook-form + zod + diff-on-submit.
 *
 * The hooks are mocked at the import boundary (matching the pattern used by
 * neighboring tests in this folder). The page itself drives a real react-hook-
 * form + zodResolver pipeline, so form validation paths are exercised end-to-
 * end against the production schema.
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

// ---------------------------------------------------------------------------
// Hook mocks — mock at the API client boundary so the production hooks (with
// React Query semantics) actually run. listSyncJobsApi is a vi.fn so we can
// assert the (limit, offset) it was called with on each page.
// ---------------------------------------------------------------------------

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

// Import AFTER mocks so the page picks them up.
import SourceDetailPage from '../page'

// ---------------------------------------------------------------------------
// Fixtures
// ---------------------------------------------------------------------------

function makeSource(overrides: Partial<SourceDetail> = {}): SourceDetail {
  return {
    id: 'src-1',
    name: 'Engineering Handbook',
    source_type: 'postgresql',
    is_active: true,
    created_at: '2026-01-01T00:00:00Z',
    source_mode: 'snapshot',
    retrieval_mode: 'hybrid',
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

function makeJob(idx: number): SyncJob {
  return {
    id: `job-${idx}`,
    source_id: 'src-1',
    status: 'success',
    started_at: `2026-05-09T${String(idx % 24).padStart(2, '0')}:00:00Z`,
    finished_at: null,
    completed_at: null,
    error_message: null,
    documents_synced: 0,
    documents_indexed: idx,
    chunks_created: idx * 5,
    created_at: '2026-05-09T00:00:00Z',
    updated_at: '2026-05-09T00:00:00Z',
  }
}

function jobsPage(total: number, limit: number, offset: number): PaginatedSyncJobs {
  const items: SyncJob[] = []
  for (let i = 0; i < limit && offset + i < total; i += 1) {
    items.push(makeJob(offset + i + 1))
  }
  return { items, total, limit, offset }
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

// ---------------------------------------------------------------------------
// Test setup
// ---------------------------------------------------------------------------

beforeEach(() => {
  updateSourceMock.mockReset()
  triggerSyncMock.mockReset()
  testConnectionMock.mockReset()
  listSyncJobsMock.mockReset()
  listDocumentsMock.mockReset()
  getSourceMock.mockReset()
  getStatsMock.mockReset()
  deleteSourceMock.mockReset()

  // Sensible defaults that individual tests override.
  getSourceMock.mockResolvedValue(makeSource())
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
  testConnectionMock.mockResolvedValue({ success: true, message: 'Connection succeeded' })
})

afterEach(() => {
  vi.clearAllMocks()
})

// ---------------------------------------------------------------------------
// Tests
// ---------------------------------------------------------------------------

describe('SourceDetailPage — sync history pagination', () => {
  it('starts on page 0 with limit=20, offset=0', async () => {
    listSyncJobsMock.mockImplementation(async (_id, limit = 20, offset = 0) =>
      jobsPage(45, limit, offset)
    )

    renderPage()

    // Switch to the Sync tab.
    const user = userEvent.setup()
    await waitFor(() => expect(screen.getByRole('tab', { name: 'Sync' })).toBeInTheDocument())
    await user.click(screen.getByRole('tab', { name: 'Sync' }))

    await waitFor(() => {
      expect(screen.getByTestId('sync-jobs-page-summary')).toHaveTextContent('Showing 1–20 of 45')
    })

    // First call should have been with offset=0.
    expect(listSyncJobsMock).toHaveBeenCalledWith('src-1', 20, 0)

    // Previous is disabled on page 0; Next is enabled.
    expect(screen.getByTestId('sync-jobs-prev')).toBeDisabled()
    expect(screen.getByTestId('sync-jobs-next')).not.toBeDisabled()
  })

  it('Next advances offset; Previous goes back; boundaries disable buttons', async () => {
    listSyncJobsMock.mockImplementation(async (_id, limit = 20, offset = 0) =>
      jobsPage(45, limit, offset)
    )

    const user = userEvent.setup()
    renderPage()

    await waitFor(() => expect(screen.getByRole('tab', { name: 'Sync' })).toBeInTheDocument())
    await user.click(screen.getByRole('tab', { name: 'Sync' }))

    await waitFor(() =>
      expect(screen.getByTestId('sync-jobs-page-summary')).toHaveTextContent('1–20 of 45')
    )

    // Advance to page 1.
    await user.click(screen.getByTestId('sync-jobs-next'))
    await waitFor(() =>
      expect(screen.getByTestId('sync-jobs-page-summary')).toHaveTextContent('21–40 of 45')
    )
    expect(listSyncJobsMock).toHaveBeenCalledWith('src-1', 20, 20)
    expect(screen.getByTestId('sync-jobs-prev')).not.toBeDisabled()
    expect(screen.getByTestId('sync-jobs-next')).not.toBeDisabled()

    // Advance to the final page (45 total → page 2 has 5 items, 41–45).
    await user.click(screen.getByTestId('sync-jobs-next'))
    await waitFor(() =>
      expect(screen.getByTestId('sync-jobs-page-summary')).toHaveTextContent('41–45 of 45')
    )
    expect(listSyncJobsMock).toHaveBeenCalledWith('src-1', 20, 40)
    expect(screen.getByTestId('sync-jobs-next')).toBeDisabled()
    expect(screen.getByTestId('sync-jobs-prev')).not.toBeDisabled()

    // Step back via Previous.
    await user.click(screen.getByTestId('sync-jobs-prev'))
    await waitFor(() =>
      expect(screen.getByTestId('sync-jobs-page-summary')).toHaveTextContent('21–40 of 45')
    )
  })

  it('renders empty-state copy when there are zero jobs', async () => {
    listSyncJobsMock.mockResolvedValue({ items: [], total: 0, limit: 20, offset: 0 })

    const user = userEvent.setup()
    renderPage()

    await waitFor(() => expect(screen.getByRole('tab', { name: 'Sync' })).toBeInTheDocument())
    await user.click(screen.getByRole('tab', { name: 'Sync' }))

    expect(await screen.findByText(/no sync runs yet/i)).toBeInTheDocument()
    expect(screen.queryByTestId('sync-jobs-page-summary')).toBeNull()
  })
})

describe('SourceDetailPage — Sync-now button on Sync tab', () => {
  it('calls triggerSyncApi exactly once', async () => {
    listSyncJobsMock.mockResolvedValue({ items: [], total: 0, limit: 20, offset: 0 })

    const user = userEvent.setup()
    renderPage()

    await waitFor(() => expect(screen.getByRole('tab', { name: 'Sync' })).toBeInTheDocument())
    await user.click(screen.getByRole('tab', { name: 'Sync' }))

    // The Sync tab's "Actions" card has its own scoped Sync now button (the
    // page header also has one — we want the tab-scoped one).
    const button = await screen.findByRole('button', {
      name: /sync source engineering handbook now/i,
    })
    await user.click(button)

    await waitFor(() => expect(triggerSyncMock).toHaveBeenCalledTimes(1))
    expect(triggerSyncMock).toHaveBeenCalledWith('src-1')
  })
})

describe('SourceDetailPage — Test-connection button visibility', () => {
  it('is hidden for file_upload sources', async () => {
    getSourceMock.mockResolvedValue(makeSource({ source_type: 'file_upload' }))

    const user = userEvent.setup()
    renderPage()

    await waitFor(() => expect(screen.getByRole('tab', { name: 'Sync' })).toBeInTheDocument())
    await user.click(screen.getByRole('tab', { name: 'Sync' }))

    // Wait for the actions card to render.
    await waitFor(() =>
      expect(
        screen.getByRole('button', { name: /sync source engineering handbook now/i })
      ).toBeInTheDocument()
    )

    expect(screen.queryByRole('button', { name: /test connection/i })).toBeNull()
  })

  const testableTypes: SourceType[] = ['postgresql', 'mysql', 'web_url', 'notion']

  it.each(testableTypes)('is visible and functional for %s sources', async (sourceType) => {
    getSourceMock.mockResolvedValue(makeSource({ source_type: sourceType }))

    const user = userEvent.setup()
    renderPage()

    await waitFor(() => expect(screen.getByRole('tab', { name: 'Sync' })).toBeInTheDocument())
    await user.click(screen.getByRole('tab', { name: 'Sync' }))

    const button = await screen.findByRole('button', { name: /test connection/i })
    expect(button).toBeInTheDocument()

    await user.click(button)

    await waitFor(() => expect(testConnectionMock).toHaveBeenCalledTimes(1))
    expect(testConnectionMock).toHaveBeenCalledWith('src-1')

    // Result region should appear with the success message.
    expect(await screen.findByTestId('test-connection-result')).toHaveTextContent(
      /connection succeeded/i
    )
  })

  it('renders a failure message when the test fails', async () => {
    getSourceMock.mockResolvedValue(makeSource({ source_type: 'postgresql' }))
    testConnectionMock.mockResolvedValue({ success: false, message: 'authentication failed' })

    const user = userEvent.setup()
    renderPage()

    await waitFor(() => expect(screen.getByRole('tab', { name: 'Sync' })).toBeInTheDocument())
    await user.click(screen.getByRole('tab', { name: 'Sync' }))

    const button = await screen.findByRole('button', { name: /test connection/i })
    await user.click(button)

    const result = await screen.findByTestId('test-connection-result')
    expect(result).toHaveTextContent(/authentication failed/i)
    expect(result).toHaveAttribute('role', 'alert')
  })
})

describe('SourceDetailPage — editable Settings form', () => {
  async function openSettings() {
    const user = userEvent.setup()
    await waitFor(() => expect(screen.getByRole('tab', { name: 'Settings' })).toBeInTheDocument())
    await user.click(screen.getByRole('tab', { name: 'Settings' }))
    await screen.findByRole('form', { name: /edit source settings/i })
    return user
  }

  it('submits ONLY changed fields when only description is edited', async () => {
    const user = await (async () => {
      renderPage()
      return openSettings()
    })()

    const form = await screen.findByRole('form', { name: /edit source settings/i })
    const descriptionField = within(form).getByLabelText('Description')

    await user.clear(descriptionField)
    await user.type(descriptionField, 'New description text')

    const saveButton = await screen.findByTestId('settings-save')
    await user.click(saveButton)

    await waitFor(() => expect(updateSourceMock).toHaveBeenCalledTimes(1))
    const [calledId, calledBody] = updateSourceMock.mock.calls[0]
    expect(calledId).toBe('src-1')
    // Critical: only `description` should be in the patch — not `name` or
    // any other field that the user did not touch.
    expect(calledBody).toEqual({ description: 'New description text' })
    expect(calledBody).not.toHaveProperty('name')
    expect(calledBody).not.toHaveProperty('retrieval_mode')
    expect(calledBody).not.toHaveProperty('sync_mode')
  })

  it('blocks submit and shows error when sync_mode=scheduled but sync_schedule is empty', async () => {
    renderPage()
    const user = await openSettings()

    const form = await screen.findByRole('form', { name: /edit source settings/i })

    // Open the Sync mode select and pick "Scheduled". The radix Select uses
    // a combobox role for the trigger.
    const syncModeTrigger = within(form).getAllByRole('combobox')[2]
    // (Layout: 0 = retrieval_mode, 1 = source_mode, 2 = sync_mode in DOM order.)
    expect(syncModeTrigger).toBeInTheDocument()
    await user.click(syncModeTrigger)
    const scheduledOption = await screen.findByRole('option', { name: 'Scheduled' })
    await user.click(scheduledOption)

    // Submit without filling the schedule — zod must block and show an error.
    const saveButton = await screen.findByTestId('settings-save')
    await user.click(saveButton)

    await waitFor(() => {
      expect(
        within(form).getByText(/cron schedule is required when sync mode is "scheduled"/i)
      ).toBeInTheDocument()
    })

    // PATCH must NOT have fired.
    expect(updateSourceMock).not.toHaveBeenCalled()
  })

  it('Save button is hidden when the form is pristine and appears once dirty', async () => {
    renderPage()
    const user = await openSettings()

    expect(screen.queryByTestId('settings-save')).toBeNull()

    const form = await screen.findByRole('form', { name: /edit source settings/i })
    const nameField = within(form).getByLabelText('Name')
    await user.type(nameField, ' (edited)')

    expect(await screen.findByTestId('settings-save')).toBeInTheDocument()
    expect(screen.getByTestId('settings-discard')).toBeInTheDocument()
  })

  it('Discard restores the original values and hides the Save bar', async () => {
    renderPage()
    const user = await openSettings()

    const form = await screen.findByRole('form', { name: /edit source settings/i })
    const nameField = within(form).getByLabelText('Name') as HTMLInputElement
    const originalName = nameField.value

    await user.type(nameField, ' (edited)')
    expect(nameField.value).toBe(`${originalName} (edited)`)

    await user.click(await screen.findByTestId('settings-discard'))

    await waitFor(() => expect(nameField.value).toBe(originalName))
    expect(screen.queryByTestId('settings-save')).toBeNull()
  })

  it('renders the "Naming…" hint when name_status === "pending_ai" but keeps the field editable', async () => {
    getSourceMock.mockResolvedValue(makeSource({ name_status: 'pending_ai' }))

    renderPage()
    const user = await openSettings()

    const hint = await screen.findByTestId('naming-hint')
    expect(hint).toHaveTextContent(/Naming…/)

    const form = await screen.findByRole('form', { name: /edit source settings/i })
    const nameField = within(form).getByLabelText('Name') as HTMLInputElement
    expect(nameField).not.toBeDisabled()
    await user.type(nameField, ' (mine)')
    expect(nameField.value).toMatch(/\(mine\)$/)
  })
})
