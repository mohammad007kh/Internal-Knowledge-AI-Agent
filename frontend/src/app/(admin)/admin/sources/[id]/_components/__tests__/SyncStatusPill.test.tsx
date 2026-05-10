/**
 * SyncStatusPill — header indicator that always reflects `latest_job.status`.
 *
 * The pill is a pure presentational component: parent owns polling, child
 * derives label + tone from the source. We assert via `data-state` rather
 * than label text so the contract isn't pinned to copy that may change.
 */
import { render, screen } from '@testing-library/react'
import { describe, expect, it } from 'vitest'

import type { SourceDetail, SyncJob } from '@/lib/api/sources'
import { SyncStatusPill, formatRelative } from '../SyncStatusPill'

// ---------------------------------------------------------------------------
// Fixtures
// ---------------------------------------------------------------------------

function makeSource(overrides: Partial<SourceDetail> = {}): SourceDetail {
  return {
    id: 'src-1',
    name: 'Engineering wiki',
    source_type: 'web_url',
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
    ...overrides,
  } satisfies SourceDetail
}

function makeJob(overrides: Partial<SyncJob> = {}): SyncJob {
  return {
    id: 'job-1',
    source_id: 'src-1',
    status: 'running',
    started_at: '2026-05-09T11:59:48Z',
    finished_at: null,
    completed_at: null,
    error_message: null,
    documents_synced: 0,
    documents_indexed: 0,
    chunks_created: 0,
    created_at: '2026-05-09T11:59:48Z',
    updated_at: '2026-05-09T11:59:48Z',
    ...overrides,
  }
}

// ---------------------------------------------------------------------------
// Tests
// ---------------------------------------------------------------------------

describe('SyncStatusPill — state derivation', () => {
  it('renders Never synced (state=never) when latest_job is null', () => {
    const source = makeSource({ latest_job: null })
    render(<SyncStatusPill source={source} isDbLiveSource={false} />)
    const pill = screen.getByTestId('sync-status-pill')
    expect(pill).toHaveAttribute('data-state', 'never')
    expect(pill).toHaveTextContent(/never synced/i)
  })

  it('renders Schema not studied for DB-live sources with no job', () => {
    const source = makeSource({ latest_job: null, source_type: 'postgresql' })
    render(<SyncStatusPill source={source} isDbLiveSource={true} />)
    const pill = screen.getByTestId('sync-status-pill')
    expect(pill).toHaveAttribute('data-state', 'never')
    expect(pill).toHaveTextContent(/schema not studied/i)
  })

  it('renders running state with "Syncing… · started …" when status=running', () => {
    const now = new Date('2026-05-09T12:00:00Z').getTime()
    const source = makeSource({
      latest_job: makeJob({ status: 'running', started_at: '2026-05-09T11:59:48Z' }),
    })
    render(<SyncStatusPill source={source} isDbLiveSource={false} now={now} />)
    const pill = screen.getByTestId('sync-status-pill')
    expect(pill).toHaveAttribute('data-state', 'running')
    expect(pill).toHaveTextContent(/syncing/i)
    expect(pill).toHaveTextContent(/started 12s ago/i)
  })

  it('renders running state as "Studying schema…" for DB-live sources', () => {
    const source = makeSource({
      source_type: 'postgresql',
      latest_job: makeJob({ status: 'pending', started_at: '2026-05-09T11:59:48Z' }),
    })
    render(<SyncStatusPill source={source} isDbLiveSource={true} />)
    const pill = screen.getByTestId('sync-status-pill')
    expect(pill).toHaveAttribute('data-state', 'running')
    expect(pill).toHaveTextContent(/studying schema/i)
  })

  it('renders success state as "Last sync succeeded · 2m ago"', () => {
    const now = new Date('2026-05-09T12:00:00Z').getTime()
    const source = makeSource({
      latest_job: makeJob({
        status: 'success',
        finished_at: '2026-05-09T11:58:00Z',
      }),
    })
    render(<SyncStatusPill source={source} isDbLiveSource={false} now={now} />)
    const pill = screen.getByTestId('sync-status-pill')
    expect(pill).toHaveAttribute('data-state', 'success')
    expect(pill).toHaveTextContent(/last sync succeeded/i)
    expect(pill).toHaveTextContent(/2m ago/i)
  })

  it('renders success state as "Schema studied · …" for DB-live sources', () => {
    const source = makeSource({
      source_type: 'postgresql',
      latest_job: makeJob({ status: 'completed', finished_at: '2026-05-09T11:58:00Z' }),
    })
    render(<SyncStatusPill source={source} isDbLiveSource={true} />)
    const pill = screen.getByTestId('sync-status-pill')
    expect(pill).toHaveAttribute('data-state', 'success')
    expect(pill).toHaveTextContent(/schema studied/i)
  })

  it('renders failed state as "Last sync failed"', () => {
    const source = makeSource({
      latest_job: makeJob({
        status: 'failed',
        finished_at: '2026-05-09T11:30:00Z',
        error_message: 'connection refused',
      }),
    })
    render(<SyncStatusPill source={source} isDbLiveSource={false} />)
    const pill = screen.getByTestId('sync-status-pill')
    expect(pill).toHaveAttribute('data-state', 'failed')
    expect(pill).toHaveTextContent(/last sync failed/i)
  })

  it('renders failed state as "Schema study failed" for DB-live sources', () => {
    const source = makeSource({
      source_type: 'postgresql',
      latest_job: makeJob({ status: 'failed' }),
    })
    render(<SyncStatusPill source={source} isDbLiveSource={true} />)
    const pill = screen.getByTestId('sync-status-pill')
    expect(pill).toHaveAttribute('data-state', 'failed')
    expect(pill).toHaveTextContent(/schema study failed/i)
  })

  it('exposes role="status" with aria-live="polite" for screen readers', () => {
    const source = makeSource({ latest_job: null })
    render(<SyncStatusPill source={source} isDbLiveSource={false} />)
    const pill = screen.getByTestId('sync-status-pill')
    expect(pill).toHaveAttribute('role', 'status')
    expect(pill).toHaveAttribute('aria-live', 'polite')
  })
})

describe('formatRelative', () => {
  const now = new Date('2026-05-09T12:00:00Z').getTime()

  it('returns "—" for null/undefined input', () => {
    expect(formatRelative(null)).toBe('—')
    expect(formatRelative(undefined)).toBe('—')
  })

  it('returns "just now" within first 5 seconds', () => {
    expect(formatRelative('2026-05-09T11:59:58Z', now)).toBe('just now')
  })

  it('returns Ns ago within first minute', () => {
    expect(formatRelative('2026-05-09T11:59:48Z', now)).toBe('12s ago')
  })

  it('returns Nm ago within first hour', () => {
    expect(formatRelative('2026-05-09T11:58:00Z', now)).toBe('2m ago')
  })

  it('returns Nh ago within first day', () => {
    expect(formatRelative('2026-05-09T10:00:00Z', now)).toBe('2h ago')
  })

  it('returns Nd ago for recent days', () => {
    expect(formatRelative('2026-05-07T12:00:00Z', now)).toBe('2d ago')
  })
})
