import type { SchemaStatus, SourceListItem, StudyState, SyncJob } from '@/lib/api/sources'
import { render, screen } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { describe, expect, it, vi } from 'vitest'
import { SourceActionCell } from '../SourceActionCell'

const NOW = '2026-05-09T12:00:00Z'

function fileSource(overrides: Partial<SourceListItem> = {}): SourceListItem {
  return {
    id: 'src-file',
    name: 'Q4 plan.pdf',
    source_type: 'pdf',
    is_active: false,
    created_at: NOW,
    source_mode: 'snapshot',
    sync_mode: 'manual',
    last_synced_at: null,
    description: null,
    latest_job: null,
    ...overrides,
  }
}

function dbSource(overrides: Partial<SourceListItem> = {}): SourceListItem {
  return {
    id: 'src-db',
    name: 'Sales replica',
    source_type: 'postgresql',
    is_active: false,
    created_at: NOW,
    source_mode: 'live',
    sync_mode: 'scheduled',
    last_synced_at: null,
    description: null,
    latest_job: null,
    schema_status: null,
    study_state: null,
    tables_documented: null,
    tables_partial: null,
    last_error_phase: null,
    last_error_message: null,
    ...overrides,
  }
}

function makeJob(overrides: Partial<SyncJob>): SyncJob {
  return {
    id: 'j1',
    source_id: 'src-file',
    status: 'pending',
    started_at: null,
    finished_at: null,
    completed_at: null,
    error_message: null,
    documents_synced: 0,
    documents_indexed: 0,
    chunks_created: 0,
    created_at: NOW,
    updated_at: NOW,
    ...overrides,
  }
}

describe('SourceActionCell — file source verbs', () => {
  it('renders "Approve & ingest" when not active and no latest_job', () => {
    const onApprove = vi.fn()
    render(<SourceActionCell source={fileSource()} onApprove={onApprove} />)
    const button = screen.getByRole('button', { name: /Approve and ingest Q4 plan\.pdf/i })
    expect(button).toBeInTheDocument()
  })

  it('renders "Run now" when active and latest_job is pending', async () => {
    const onSync = vi.fn()
    render(
      <SourceActionCell
        source={fileSource({ is_active: true, latest_job: makeJob({ status: 'pending' }) })}
        onSync={onSync}
      />
    )
    const button = screen.getByRole('button', { name: /Run sync now/i })
    expect(button).toBeInTheDocument()
    expect(screen.getByText(/Will run on next 30-min cycle/i)).toBeInTheDocument()
    await userEvent.click(button)
    expect(onSync).toHaveBeenCalledWith('src-file')
  })

  it('renders italic "Working on it…" when latest_job.status==="running"', () => {
    render(
      <SourceActionCell
        source={fileSource({ is_active: true, latest_job: makeJob({ status: 'running' }) })}
      />
    )
    expect(screen.getByRole('status', { name: /ingestion running/i })).toBeInTheDocument()
    expect(screen.getByText(/Working on it/i)).toBeInTheDocument()
  })

  it('renders "Ready for chat" with a check when success and chunks exist', () => {
    render(
      <SourceActionCell
        source={fileSource({
          is_active: true,
          latest_job: makeJob({ status: 'success', chunks_created: 12 }),
        })}
      />
    )
    expect(screen.getByText(/Ready for chat/i)).toBeInTheDocument()
  })

  it('renders "View error" link when latest_job.status==="failed"', async () => {
    const onViewError = vi.fn()
    render(
      <SourceActionCell
        source={fileSource({
          is_active: true,
          latest_job: makeJob({ status: 'failed', error_message: 'oops' }),
        })}
        onViewError={onViewError}
      />
    )
    const link = screen.getByRole('button', { name: /View error/i })
    await userEvent.click(link)
    expect(onViewError).toHaveBeenCalledWith('src-file', 'oops')
  })

  it('renders amber "Re-run · 0 chunks" when success but chunks==0', () => {
    render(
      <SourceActionCell
        source={fileSource({
          is_active: true,
          latest_job: makeJob({ status: 'success', chunks_created: 0 }),
        })}
      />
    )
    expect(screen.getByText(/Re-run · 0 chunks/i)).toBeInTheDocument()
  })
})

describe('SourceActionCell — DB source verbs', () => {
  it('renders "Approve" when schema_status is null and not active', async () => {
    const onApprove = vi.fn()
    render(<SourceActionCell source={dbSource()} onApprove={onApprove} />)
    const button = screen.getByRole('button', { name: /Approve Sales replica/i })
    expect(button).toBeInTheDocument()
    expect(button).toHaveTextContent(/^Approve$/)
    await userEvent.click(button)
    expect(onApprove).toHaveBeenCalledWith('src-db')
  })

  it('renders "Queued for study" when schema_status is QUEUED', () => {
    render(
      <SourceActionCell
        source={dbSource({
          is_active: true,
          schema_status: 'QUEUED' as SchemaStatus,
          study_state: 'QUEUED' as StudyState,
        })}
      />
    )
    expect(screen.getByText(/Queued for study/i)).toBeInTheDocument()
  })

  it('renders the "Listing tables…" phase label during INVENTORY', () => {
    render(
      <SourceActionCell
        source={dbSource({
          is_active: true,
          schema_status: 'STUDYING' as SchemaStatus,
          study_state: 'INVENTORY' as StudyState,
        })}
      />
    )
    expect(screen.getByText(/Listing tables/i)).toBeInTheDocument()
  })

  it('renders "Sampling rows…" during SAMPLING', () => {
    render(
      <SourceActionCell
        source={dbSource({
          is_active: true,
          schema_status: 'STUDYING' as SchemaStatus,
          study_state: 'SAMPLING' as StudyState,
        })}
      />
    )
    expect(screen.getByText(/Sampling rows/i)).toBeInTheDocument()
  })

  it('renders "Describing tables with AI…" during DESCRIBING', () => {
    render(
      <SourceActionCell
        source={dbSource({
          is_active: true,
          schema_status: 'STUDYING' as SchemaStatus,
          study_state: 'DESCRIBING' as StudyState,
        })}
      />
    )
    expect(screen.getByText(/Describing tables with AI/i)).toBeInTheDocument()
  })

  it('renders an Approve button when READY and not yet approved', async () => {
    const onApprove = vi.fn()
    render(
      <SourceActionCell
        source={dbSource({
          is_active: false,
          schema_status: 'READY' as SchemaStatus,
          study_state: 'READY' as StudyState,
          tables_documented: 12,
        })}
        onApprove={onApprove}
      />
    )
    const button = screen.getByRole('button', { name: /Approve Sales replica/i })
    expect(button).toHaveTextContent(/12 tables/)
    expect(button).toHaveTextContent(/Approve to enable/)
    await userEvent.click(button)
    expect(onApprove).toHaveBeenCalledWith('src-db')
  })

  it('renders green "Ready" check when READY and approved', () => {
    render(
      <SourceActionCell
        source={dbSource({
          is_active: true,
          schema_status: 'READY' as SchemaStatus,
          study_state: 'READY' as StudyState,
          tables_documented: 12,
        })}
      />
    )
    expect(screen.getByText(/^Ready$/)).toBeInTheDocument()
  })

  it('renders amber "review" CTA on READY_PARTIAL', () => {
    // schema_status stays "READY" — the studying agent shipped a usable doc;
    // READY_PARTIAL is a study_state value indicating at least one table
    // failed AI description. SourceActionCell branches on study_state for
    // this case (see SourceActionCell.tsx:351).
    render(
      <SourceActionCell
        source={dbSource({
          is_active: true,
          schema_status: 'READY' as SchemaStatus,
          study_state: 'READY_PARTIAL' as StudyState,
          tables_documented: 30,
          tables_partial: 4,
        })}
      />
    )
    expect(screen.getByRole('button', { name: /partial schema documentation/i })).toBeInTheDocument()
    expect(screen.getByText(/30 tables/)).toBeInTheDocument()
    expect(screen.getByText(/4 partial/)).toBeInTheDocument()
  })

  it('renders "Re-study" CTA on STALE', () => {
    render(
      <SourceActionCell
        source={dbSource({
          is_active: true,
          schema_status: 'STALE' as SchemaStatus,
          study_state: 'READY' as StudyState,
          tables_documented: 22,
        })}
      />
    )
    expect(screen.getByRole('button', { name: /Re-study/i })).toBeInTheDocument()
    expect(screen.getByText(/Schema drift detected/i)).toBeInTheDocument()
  })

  it('renders red "Connection failed" link on FAILED, calls onViewError', async () => {
    const onViewError = vi.fn()
    render(
      <SourceActionCell
        source={dbSource({
          is_active: false,
          schema_status: 'FAILED' as SchemaStatus,
          study_state: 'CONNECT_FAILED' as StudyState,
          last_error_phase: 'CONNECT',
          last_error_message: 'Timed out',
        })}
        onViewError={onViewError}
      />
    )
    const link = screen.getByRole('button', { name: /View connection error/i })
    expect(link).toHaveTextContent(/Connection failed · Edit credentials/i)
    await userEvent.click(link)
    expect(onViewError).toHaveBeenCalledWith('src-db', 'Timed out')
  })

  it('renders a graceful fallback when schema_status is missing on a DB source', () => {
    render(
      <SourceActionCell
        source={dbSource({
          // schema_status remains null → Wave 3 not yet wired.
          is_active: true,
        })}
      />
    )
    expect(screen.getByText(/pending wiring/i)).toBeInTheDocument()
  })
})
