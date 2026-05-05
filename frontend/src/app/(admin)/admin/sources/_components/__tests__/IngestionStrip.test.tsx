import { render, screen } from '@testing-library/react'
import { describe, expect, it } from 'vitest'

import { IngestionStrip } from '../IngestionStrip'
import type { SourceListItem, SyncJob } from '@/lib/api/sources'

function buildSource(overrides: Partial<SourceListItem> = {}): SourceListItem {
  return {
    id: 'src-1',
    name: 'Acme Wiki',
    source_type: 'pdf',
    is_active: false,
    created_at: '2024-01-01T00:00:00Z',
    document_count: 0,
    chunk_count: 0,
    has_upload: false,
    ...overrides,
  }
}

function buildJob(overrides: Partial<SyncJob> = {}): SyncJob {
  return {
    id: 'job-1',
    source_id: 'src-1',
    status: 'completed',
    started_at: '2024-01-01T00:00:00Z',
    finished_at: '2024-01-01T00:01:00Z',
    completed_at: '2024-01-01T00:01:00Z',
    error_message: null,
    documents_synced: 0,
    documents_indexed: 0,
    chunks_created: 0,
    created_at: '2024-01-01T00:00:00Z',
    updated_at: '2024-01-01T00:01:00Z',
    ...overrides,
  }
}

function getPip(stage: 'uploaded' | 'parsed' | 'chunked' | 'approved'): HTMLElement {
  const el = document.querySelector(`[data-stage="${stage}"]`)
  if (!el) {
    throw new Error(`Pip for stage "${stage}" not found`)
  }
  return el as HTMLElement
}

describe('IngestionStrip', () => {
  it('marks all four stages active when ingestion + approval are complete', () => {
    const source = buildSource({
      has_upload: true,
      document_count: 12,
      chunk_count: 240,
      is_active: true,
      latest_job: buildJob({ status: 'completed' }),
    })

    render(<IngestionStrip source={source} />)

    for (const stage of ['uploaded', 'parsed', 'chunked', 'approved'] as const) {
      expect(getPip(stage).getAttribute('data-active')).toBe('true')
      expect(getPip(stage).getAttribute('data-failed')).toBe('false')
      expect(getPip(stage).getAttribute('data-running')).toBe('false')
    }

    // Counts surface in the labels
    expect(screen.getByText(/Parsed \(12\)/)).toBeInTheDocument()
    expect(screen.getByText(/Chunked \(240\)/)).toBeInTheDocument()
    expect(screen.getByText('Approved')).toBeInTheDocument()

    // Strip exposes itself as a status region for screen readers
    const region = screen.getByRole('status')
    expect(region).toBeInTheDocument()
    expect(region.getAttribute('aria-label')).toContain('Acme Wiki')
  })

  it('shows partial progress: only uploaded + parsed are active', () => {
    const source = buildSource({
      has_upload: true,
      document_count: 3,
      chunk_count: 0,
      is_active: false,
    })

    render(<IngestionStrip source={source} />)

    expect(getPip('uploaded').getAttribute('data-active')).toBe('true')
    expect(getPip('parsed').getAttribute('data-active')).toBe('true')
    expect(getPip('chunked').getAttribute('data-active')).toBe('false')
    expect(getPip('approved').getAttribute('data-active')).toBe('false')

    // Stage with zero count drops the parenthetical
    expect(screen.getByText('Chunked')).toBeInTheDocument()
  })

  it('paints the in-flight stage red when latest_job.status is "failed"', () => {
    const source = buildSource({
      has_upload: true,
      document_count: 5,
      chunk_count: 0,
      is_active: false,
      latest_job: buildJob({
        status: 'failed',
        error_message: 'Embedding model rate limited',
      }),
    })

    render(<IngestionStrip source={source} />)

    // First inactive stage in pipeline order is "chunked" (uploaded+parsed are
    // active).  That's where the red dot anchors.
    const failed = getPip('chunked')
    expect(failed.getAttribute('data-failed')).toBe('true')
    expect(failed.getAttribute('data-running')).toBe('false')

    // Other stages must NOT be flagged as failed.
    expect(getPip('uploaded').getAttribute('data-failed')).toBe('false')
    expect(getPip('parsed').getAttribute('data-failed')).toBe('false')
    expect(getPip('approved').getAttribute('data-failed')).toBe('false')

    // Region announces the failure to assistive tech.
    expect(screen.getByRole('status').getAttribute('aria-label')).toContain('sync failed')
  })

  it('places the running spinner on the next-incomplete stage', () => {
    const source = buildSource({
      has_upload: true,
      document_count: 0,
      chunk_count: 0,
      is_active: false,
      latest_job: buildJob({ status: 'running' }),
    })

    render(<IngestionStrip source={source} />)

    // Uploaded is already active, so the spinner rides on "parsed".
    const running = getPip('parsed')
    expect(running.getAttribute('data-running')).toBe('true')
    expect(running.getAttribute('data-failed')).toBe('false')

    // Other stages don't show the spinner.
    expect(getPip('uploaded').getAttribute('data-running')).toBe('false')
    expect(getPip('chunked').getAttribute('data-running')).toBe('false')
    expect(getPip('approved').getAttribute('data-running')).toBe('false')

    expect(screen.getByRole('status').getAttribute('aria-label')).toContain('sync in progress')
  })

  it('falls back gracefully when ingestion fields are absent (legacy rows)', () => {
    // No has_upload / document_count / chunk_count / latest_job — server may
    // omit them on older rows. Component must still render four pips.
    const source = buildSource({
      has_upload: undefined,
      document_count: undefined,
      chunk_count: undefined,
      is_active: false,
    })

    render(<IngestionStrip source={source} />)

    for (const stage of ['uploaded', 'parsed', 'chunked', 'approved'] as const) {
      expect(getPip(stage).getAttribute('data-active')).toBe('false')
    }
  })
})
