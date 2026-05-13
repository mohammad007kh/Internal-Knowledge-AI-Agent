/**
 * Lifecycle phase + gate matrix coverage.
 *
 * Every cell in the derivePhase table from `lifecycle.ts` gets a dedicated
 * case so any future change shows up as a single broken assertion rather
 * than a cluster of cascading failures.
 */

import type {
  NameStatus,
  SchemaStatus,
  SourceDetail,
  SourceListItem,
  SyncJob,
} from '@/lib/api/sources'
import { describe, expect, it } from 'vitest'
import {
  PHASE_ORDER,
  type Phase,
  availabilityBlockers,
  derivePhase,
  isInFlightPhase,
  isPollingPhase,
  lifecycleGatesFor,
  phaseLabel,
  phaseProgress,
} from '../lifecycle'

function makeJob(overrides: Partial<SyncJob> = {}): SyncJob {
  return {
    id: 'job-1',
    source_id: 'src-1',
    status: 'success',
    started_at: '2026-05-09T00:00:00Z',
    finished_at: '2026-05-09T00:05:00Z',
    completed_at: '2026-05-09T00:05:00Z',
    error_message: null,
    documents_synced: 0,
    documents_indexed: 0,
    chunks_created: 0,
    created_at: '2026-05-09T00:00:00Z',
    updated_at: '2026-05-09T00:05:00Z',
    ...overrides,
  }
}

function makeSource(overrides: Partial<SourceListItem> = {}): SourceListItem {
  return {
    id: 'src-1',
    name: 'Test',
    source_type: 'file_upload',
    is_active: false,
    created_at: '2026-05-09T00:00:00Z',
    has_upload: true,
    document_count: 0,
    chunk_count: 0,
    latest_job: null,
    ...overrides,
  }
}

function makeDetail(overrides: Partial<SourceDetail> = {}): SourceDetail {
  return {
    ...makeSource(),
    source_mode: 'snapshot',
    retrieval_mode: 'vector_only',
    description: 'A test source',
    sync_mode: 'manual',
    sync_schedule: null,
    last_synced_at: null,
    status: 'pending',
    citations_enabled: true,
    updated_at: '2026-05-09T00:00:00Z',
    owner_email: null,
    schema_summary: null,
    ...overrides,
  } as SourceDetail
}

describe('derivePhase', () => {
  describe('terminal failures', () => {
    it('returns failed when the latest job failed', () => {
      const s = makeSource({ latest_job: makeJob({ status: 'failed' }) })
      expect(derivePhase(s)).toBe('failed')
    })

    it('returns failed when schema_status is FAILED', () => {
      const s = makeSource({
        source_type: 'database',
        schema_status: 'FAILED' as SchemaStatus,
        latest_job: makeJob({ status: 'success' }),
      })
      expect(derivePhase(s)).toBe('failed')
    })

    it('a failed job beats a pending_ai name', () => {
      const s = makeSource({
        name_status: 'pending_ai' as NameStatus,
        latest_job: makeJob({ status: 'failed' }),
      })
      expect(derivePhase(s)).toBe('failed')
    })
  })

  describe('DB schema-study states', () => {
    it('STUDYING → analyzing', () => {
      const s = makeSource({
        source_type: 'database',
        schema_status: 'STUDYING' as SchemaStatus,
      })
      expect(derivePhase(s)).toBe('analyzing')
    })

    it('QUEUED → analyzing', () => {
      const s = makeSource({
        source_type: 'database',
        schema_status: 'QUEUED' as SchemaStatus,
      })
      expect(derivePhase(s)).toBe('analyzing')
    })

    it('READY schema with success job → ready', () => {
      const s = makeSource({
        source_type: 'database',
        schema_status: 'READY' as SchemaStatus,
        latest_job: makeJob({ status: 'success' }),
        chunk_count: 5,
      })
      expect(derivePhase(s)).toBe('ready')
    })
  })

  describe('AI naming pending', () => {
    it('name_status pending_ai → naming, even with no job', () => {
      const s = makeSource({ name_status: 'pending_ai' as NameStatus })
      expect(derivePhase(s)).toBe('naming')
    })

    it('description_status pending_ai → naming', () => {
      const s = makeSource({ description_status: 'pending_ai' as NameStatus })
      expect(derivePhase(s)).toBe('naming')
    })

    it('naming pending dominates a still-running job', () => {
      const s = makeSource({
        name_status: 'pending_ai' as NameStatus,
        latest_job: makeJob({ status: 'running', chunks_created: 10 }),
      })
      expect(derivePhase(s)).toBe('naming')
    })

    it('naming pending dominates a completed job', () => {
      const s = makeSource({
        name_status: 'pending_ai' as NameStatus,
        latest_job: makeJob({ status: 'success', chunks_created: 10 }),
        chunk_count: 10,
      })
      expect(derivePhase(s)).toBe('naming')
    })
  })

  describe('in-flight ingestion job', () => {
    it('running with zero chunks → chunking', () => {
      const s = makeSource({
        latest_job: makeJob({ status: 'running', chunks_created: 0 }),
        chunk_count: 0,
      })
      expect(derivePhase(s)).toBe('chunking')
    })

    it('running with chunks > 0 → analyzing', () => {
      const s = makeSource({
        latest_job: makeJob({ status: 'running', chunks_created: 50 }),
        chunk_count: 50,
      })
      expect(derivePhase(s)).toBe('analyzing')
    })
  })

  describe('queued (pending) job', () => {
    it('file source with no upload + pending job → pending_upload', () => {
      const s = makeSource({
        source_type: 'file_upload',
        has_upload: false,
        latest_job: makeJob({ status: 'pending' }),
      })
      expect(derivePhase(s)).toBe('pending_upload')
    })

    it('file source WITH upload + pending job → chunking', () => {
      const s = makeSource({
        source_type: 'file_upload',
        has_upload: true,
        latest_job: makeJob({ status: 'pending' }),
      })
      expect(derivePhase(s)).toBe('chunking')
    })

    it('non-file source + pending job → chunking', () => {
      const s = makeSource({
        source_type: 'web_url',
        has_upload: false,
        latest_job: makeJob({ status: 'pending' }),
      })
      expect(derivePhase(s)).toBe('chunking')
    })
  })

  describe('no job recorded', () => {
    it('file source with no upload → pending_upload', () => {
      const s = makeSource({
        source_type: 'file_upload',
        has_upload: false,
        latest_job: null,
      })
      expect(derivePhase(s)).toBe('pending_upload')
    })

    it('source with chunks but no job → ready (defensive)', () => {
      const s = makeSource({
        latest_job: null,
        chunk_count: 100,
        last_synced_at: '2026-05-09T00:05:00Z',
      })
      expect(derivePhase(s)).toBe('ready')
    })

    it('source with no chunks and no job and no upload signal → pending_upload', () => {
      const s = makeSource({
        source_type: 'web_url',
        latest_job: null,
        chunk_count: 0,
      })
      expect(derivePhase(s)).toBe('pending_upload')
    })
  })

  describe('terminal success', () => {
    it('success + chunks → ready', () => {
      const s = makeSource({
        latest_job: makeJob({ status: 'success', chunks_created: 42 }),
        chunk_count: 42,
      })
      expect(derivePhase(s)).toBe('ready')
    })

    it('completed + chunks → ready', () => {
      const s = makeSource({
        latest_job: makeJob({ status: 'completed', chunks_created: 7 }),
        chunk_count: 7,
      })
      expect(derivePhase(s)).toBe('ready')
    })
  })
})

describe('phaseLabel', () => {
  it('returns a non-empty string for every phase', () => {
    const phases: Phase[] = [
      'pending_upload',
      'naming',
      'chunking',
      'analyzing',
      'ready',
      'failed',
    ]
    for (const phase of phases) {
      expect(phaseLabel(phase).length).toBeGreaterThan(0)
    }
  })
})

describe('phaseProgress', () => {
  it('emits monotonic progress through PHASE_ORDER', () => {
    let prev = -1
    for (const p of PHASE_ORDER) {
      const v = phaseProgress(p)
      expect(v).toBeGreaterThanOrEqual(prev)
      prev = v
    }
  })

  it('caps "ready" at 100', () => {
    expect(phaseProgress('ready')).toBe(100)
  })
})

describe('isInFlightPhase / isPollingPhase', () => {
  it('treats all four pre-ready phases as in-flight', () => {
    expect(isInFlightPhase('pending_upload')).toBe(true)
    expect(isInFlightPhase('naming')).toBe(true)
    expect(isInFlightPhase('chunking')).toBe(true)
    expect(isInFlightPhase('analyzing')).toBe(true)
    expect(isInFlightPhase('ready')).toBe(false)
    expect(isInFlightPhase('failed')).toBe(false)
  })

  it('polls only while the worker is actually doing something', () => {
    // pending_upload is quiet — no worker action until the admin uploads
    // bytes, so we don't waste an HTTP roundtrip every 3s.
    expect(isPollingPhase('pending_upload')).toBe(false)
    expect(isPollingPhase('naming')).toBe(true)
    expect(isPollingPhase('chunking')).toBe(true)
    expect(isPollingPhase('analyzing')).toBe(true)
    expect(isPollingPhase('ready')).toBe(false)
    expect(isPollingPhase('failed')).toBe(false)
  })
})

describe('lifecycleGatesFor — gate matrix', () => {
  const phases: Phase[] = [
    'pending_upload',
    'naming',
    'chunking',
    'analyzing',
    'ready',
    'failed',
  ]

  it.each(phases)('returns a complete gate object for %s', (phase) => {
    const gates = lifecycleGatesFor(phase)
    expect(gates).toHaveProperty('canSyncNow')
    expect(gates).toHaveProperty('canChat')
    expect(gates).toHaveProperty('canMakeAvailableToUsers')
    expect(gates).toHaveProperty('canEditConfig')
  })

  it('ready phase — every consumer-facing control is open', () => {
    const g = lifecycleGatesFor('ready')
    expect(g.canSyncNow).toBe(true)
    expect(g.canChat).toBe(true)
    expect(g.canMakeAvailableToUsers).toBe(true)
    expect(g.canEditConfig).toBe(true)
  })

  it('in-flight phases close sync, chat, availability — but never config', () => {
    for (const p of ['pending_upload', 'naming', 'chunking', 'analyzing'] as Phase[]) {
      const g = lifecycleGatesFor(p)
      expect(g.canSyncNow).toBe(false)
      expect(g.canChat).toBe(false)
      expect(g.canMakeAvailableToUsers).toBe(false)
      expect(g.canEditConfig).toBe(true)
      expect(g.syncNowReason.length).toBeGreaterThan(0)
      expect(g.chatReason.length).toBeGreaterThan(0)
      expect(g.availabilityReason.length).toBeGreaterThan(0)
    }
  })

  it('failed phase — sync is open for retry; chat + availability are closed', () => {
    const g = lifecycleGatesFor('failed')
    expect(g.canSyncNow).toBe(true)
    expect(g.canChat).toBe(false)
    expect(g.canMakeAvailableToUsers).toBe(false)
    expect(g.canEditConfig).toBe(true)
  })
})

describe('shouldPollSourceLifecycle', () => {
  // Imported here (not at top) so the bulk of the suite remains focused on
  // the pure phase derivation. This block just verifies the polling
  // predicate widens to cover AI-naming and schema-study states (U14).
  it('returns false for a steady-state source', async () => {
    const { shouldPollSourceLifecycle } = await import(
      '@/features/sources/hooks/useSources'
    )
    const s = makeSource({
      latest_job: makeJob({ status: 'success' }),
    })
    expect(shouldPollSourceLifecycle(s)).toBe(false)
  })

  it('returns true while the sync job is running', async () => {
    const { shouldPollSourceLifecycle } = await import(
      '@/features/sources/hooks/useSources'
    )
    const s = makeSource({ latest_job: makeJob({ status: 'running' }) })
    expect(shouldPollSourceLifecycle(s)).toBe(true)
  })

  it('returns true while AI naming is pending (no job)', async () => {
    const { shouldPollSourceLifecycle } = await import(
      '@/features/sources/hooks/useSources'
    )
    const s = makeSource({ name_status: 'pending_ai' as NameStatus })
    expect(shouldPollSourceLifecycle(s)).toBe(true)
  })

  it('returns true while AI description is pending', async () => {
    const { shouldPollSourceLifecycle } = await import(
      '@/features/sources/hooks/useSources'
    )
    const s = makeSource({ description_status: 'pending_ai' as NameStatus })
    expect(shouldPollSourceLifecycle(s)).toBe(true)
  })

  it('returns true while the schema study is queued or running', async () => {
    const { shouldPollSourceLifecycle } = await import(
      '@/features/sources/hooks/useSources'
    )
    expect(
      shouldPollSourceLifecycle(
        makeSource({ schema_status: 'QUEUED' as SchemaStatus })
      )
    ).toBe(true)
    expect(
      shouldPollSourceLifecycle(
        makeSource({ schema_status: 'STUDYING' as SchemaStatus })
      )
    ).toBe(true)
  })
})

describe('availabilityBlockers', () => {
  it('reports an empty array when name + description are set and not pending', () => {
    const s = makeDetail({
      name_status: 'ai_set',
      description_status: 'ai_set',
      description: 'A clear description.',
    })
    expect(availabilityBlockers(s)).toEqual([])
  })

  it('reports a blocker when name is pending_ai', () => {
    const s = makeDetail({
      name_status: 'pending_ai',
      description_status: 'ai_set',
      description: 'Already there.',
    })
    expect(availabilityBlockers(s)).toHaveLength(1)
    expect(availabilityBlockers(s)[0]).toMatch(/naming/i)
  })

  it('reports a blocker when description is pending_ai', () => {
    const s = makeDetail({
      name_status: 'user_set',
      description_status: 'pending_ai',
      description: '',
    })
    // pending_ai supersedes the empty-string check.
    expect(availabilityBlockers(s)).toEqual([
      'AI description has not finished — wait for it to clear.',
    ])
  })

  it('reports the empty-description blocker when not pending and the field is empty', () => {
    const s = makeDetail({
      name_status: 'user_set',
      description_status: 'user_set',
      description: '   ',
    })
    expect(availabilityBlockers(s)).toHaveLength(1)
    expect(availabilityBlockers(s)[0]).toMatch(/description is empty/i)
  })
})
