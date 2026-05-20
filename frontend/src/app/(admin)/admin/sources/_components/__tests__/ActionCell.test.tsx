import type { SourceDetail, SourceListItem, SyncJob } from '@/lib/api/sources'
import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import { render, screen } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import type { ReactNode } from 'react'
import { beforeEach, describe, expect, it, vi } from 'vitest'

// ---------------------------------------------------------------------------
// Mocks
// ---------------------------------------------------------------------------

const updateSourceMock = vi.fn(
  async (_id: string, body: { is_active?: boolean }): Promise<SourceDetail> =>
    ({
      id: 'src-1',
      name: 'Test source',
      source_type: 'pdf',
      is_active: body.is_active ?? true,
      created_at: '2024-01-01T00:00:00Z',
      source_mode: 'snapshot',
      retrieval_mode: 'vector_only',
      description: null,
      sync_mode: 'manual',
      sync_schedule: null,
      last_synced_at: null,
      status: 'pending',
      citations_enabled: true,
      updated_at: '2024-01-01T00:00:00Z',
    }) as SourceDetail
)

const triggerSyncMock = vi.fn(
  async (id: string): Promise<SyncJob> => ({
    id: 'job-new',
    source_id: id,
    status: 'pending',
    started_at: null,
    finished_at: null,
    completed_at: null,
    error_message: null,
    documents_synced: 0,
    documents_indexed: 0,
    chunks_created: 0,
    created_at: '2024-01-01T00:00:00Z',
    updated_at: '2024-01-01T00:00:00Z',
  })
)

vi.mock('@/lib/api/sources', async (importOriginal) => {
  const actual = await importOriginal<typeof import('@/lib/api/sources')>()
  return {
    ...actual,
    updateSourceApi: (id: string, body: { is_active?: boolean }) => updateSourceMock(id, body),
    triggerSyncApi: (id: string) => triggerSyncMock(id),
  }
})

vi.mock('sonner', () => ({
  toast: { success: vi.fn(), error: vi.fn() },
}))

// Import AFTER the mocks are registered so the component picks them up.
import { ActionCell } from '../ActionCell'

// ---------------------------------------------------------------------------
// Helpers
// ---------------------------------------------------------------------------

function makeJob(overrides: Partial<SyncJob>): SyncJob {
  return {
    id: 'job-1',
    source_id: 'src-1',
    status: 'pending',
    started_at: null,
    finished_at: null,
    completed_at: null,
    error_message: null,
    documents_synced: 0,
    documents_indexed: 0,
    chunks_created: 0,
    created_at: '2024-01-01T00:00:00Z',
    updated_at: '2024-01-01T00:00:00Z',
    ...overrides,
  }
}

function makeSource(overrides: Partial<SourceListItem>): SourceListItem {
  return {
    id: 'src-1',
    name: 'Test source',
    source_type: 'pdf',
    is_active: true,
    created_at: '2024-01-01T00:00:00Z',
    latest_job: null,
    ...overrides,
  }
}

function renderActionCell(source: SourceListItem) {
  const client = new QueryClient({
    defaultOptions: { queries: { retry: false }, mutations: { retry: false } },
  })
  function Wrapper({ children }: { children: ReactNode }) {
    return <QueryClientProvider client={client}>{children}</QueryClientProvider>
  }
  return render(<ActionCell source={source} />, { wrapper: Wrapper })
}

// ---------------------------------------------------------------------------
// Tests
// ---------------------------------------------------------------------------

describe('ActionCell', () => {
  beforeEach(() => {
    updateSourceMock.mockClear()
    triggerSyncMock.mockClear()
  })

  it('renders Approve & ingest for awaiting_approval phase', () => {
    renderActionCell(makeSource({ is_active: false, latest_job: null }))
    expect(screen.getByRole('button', { name: /approve and ingest/i })).toBeInTheDocument()
    expect(screen.getByText(/sits idle until you approve/i)).toBeInTheDocument()
  })

  it('renders Run now for queued phase', () => {
    renderActionCell(makeSource({ is_active: true, latest_job: null }))
    expect(screen.getByRole('button', { name: /run sync now/i })).toBeInTheDocument()
    expect(screen.getByText(/will run on next 30-min cycle/i)).toBeInTheDocument()
  })

  it('renders working-on-it status for running phase', () => {
    renderActionCell(makeSource({ is_active: true, latest_job: makeJob({ status: 'running' }) }))
    expect(screen.getByRole('status', { name: /currently ingesting/i })).toBeInTheDocument()
    expect(screen.getByText(/working on it/i)).toBeInTheDocument()
  })

  it('renders Ready for chat for ready phase', () => {
    renderActionCell(
      makeSource({
        is_active: true,
        latest_job: makeJob({ status: 'success', chunks_created: 12 }),
      })
    )
    expect(screen.getByText(/ready for chat/i)).toBeInTheDocument()
  })

  it('renders View error link for failed phase', () => {
    renderActionCell(
      makeSource({
        is_active: true,
        latest_job: makeJob({ status: 'failed', error_message: 'connection timeout' }),
      })
    )
    expect(screen.getByRole('button', { name: /view error/i })).toBeInTheDocument()
  })

  it('renders Re-run for empty phase with 0-chunks microcopy', () => {
    renderActionCell(
      makeSource({
        is_active: true,
        latest_job: makeJob({ status: 'success', chunks_created: 0 }),
      })
    )
    expect(screen.getByRole('button', { name: /re-run sync/i })).toBeInTheDocument()
    expect(screen.getByText(/produced 0 chunks/i)).toBeInTheDocument()
  })

  it('fires PATCH is_active=true when Approve & ingest is clicked', async () => {
    const user = userEvent.setup()
    renderActionCell(makeSource({ is_active: false, latest_job: null }))

    const button = screen.getByRole('button', { name: /approve and ingest/i })
    await user.click(button)

    expect(updateSourceMock).toHaveBeenCalledTimes(1)
    expect(updateSourceMock).toHaveBeenCalledWith('src-1', { is_active: true })
  })

  it('fires sync trigger when Run now is clicked', async () => {
    const user = userEvent.setup()
    renderActionCell(makeSource({ is_active: true, latest_job: null }))

    await user.click(screen.getByRole('button', { name: /run sync now/i }))

    expect(triggerSyncMock).toHaveBeenCalledTimes(1)
    expect(triggerSyncMock).toHaveBeenCalledWith('src-1')
  })
})
