import type { SourceListItem, SyncJob } from '@/lib/api/sources'
import { describe, expect, it } from 'vitest'
import { derivePhase } from '../sourcePhase'

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

describe('derivePhase', () => {
  it('returns awaiting_approval when inactive and no job', () => {
    const source = makeSource({ is_active: false, latest_job: null })
    expect(derivePhase(source)).toBe('awaiting_approval')
  })

  it('returns awaiting_approval when inactive and job is pending', () => {
    const source = makeSource({
      is_active: false,
      latest_job: makeJob({ status: 'pending' }),
    })
    expect(derivePhase(source)).toBe('awaiting_approval')
  })

  it('returns queued when active and no job', () => {
    const source = makeSource({ is_active: true, latest_job: null })
    expect(derivePhase(source)).toBe('queued')
  })

  it('returns queued when active and job is pending', () => {
    const source = makeSource({
      is_active: true,
      latest_job: makeJob({ status: 'pending' }),
    })
    expect(derivePhase(source)).toBe('queued')
  })

  it('returns running when latest job is running', () => {
    const source = makeSource({
      is_active: true,
      latest_job: makeJob({ status: 'running' }),
    })
    expect(derivePhase(source)).toBe('running')
  })

  it('returns running even when source is inactive but job is running', () => {
    // Defensive: a job that started before deactivation should still show running.
    const source = makeSource({
      is_active: false,
      latest_job: makeJob({ status: 'running' }),
    })
    expect(derivePhase(source)).toBe('running')
  })

  it('returns ready when job succeeded and chunks_created > 0', () => {
    const source = makeSource({
      is_active: true,
      latest_job: makeJob({ status: 'success', chunks_created: 42 }),
    })
    expect(derivePhase(source)).toBe('ready')
  })

  it('returns ready for completed status with chunks_created > 0', () => {
    const source = makeSource({
      is_active: true,
      latest_job: makeJob({ status: 'completed', chunks_created: 7 }),
    })
    expect(derivePhase(source)).toBe('ready')
  })

  it('returns failed when latest job failed', () => {
    const source = makeSource({
      is_active: true,
      latest_job: makeJob({ status: 'failed', error_message: 'boom' }),
    })
    expect(derivePhase(source)).toBe('failed')
  })

  it('returns empty when job succeeded but produced 0 chunks', () => {
    const source = makeSource({
      is_active: true,
      latest_job: makeJob({ status: 'success', chunks_created: 0 }),
    })
    expect(derivePhase(source)).toBe('empty')
  })
})
