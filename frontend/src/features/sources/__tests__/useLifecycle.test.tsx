/**
 * useLifecycle — the React-hook wrapper around `derivePhase` +
 * `lifecycleGatesFor` + `availabilityBlockers`.
 *
 * We use `renderHook` so the test stays close to how the page consumes the
 * hook. The hook does no fetching of its own (it's a pure derivation), so we
 * don't need a QueryClientProvider here.
 */

import type { SourceDetail } from '@/lib/api/sources'
import { renderHook } from '@testing-library/react'
import { describe, expect, it } from 'vitest'

import { useLifecycle } from '../lifecycle'

function makeDetail(overrides: Partial<SourceDetail> = {}): SourceDetail {
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
    source_mode: 'snapshot',
    retrieval_mode: 'vector_only',
    description: 'A description.',
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

describe('useLifecycle', () => {
  it('treats a null source as "naming" with every gate closed', () => {
    const { result } = renderHook(() => useLifecycle(null))
    expect(result.current.phase).toBe('naming')
    expect(result.current.canSyncNow).toBe(false)
    expect(result.current.canChat).toBe(false)
    expect(result.current.canMakeAvailableToUsers).toBe(false)
    expect(result.current.canApproveNow).toBe(false)
  })

  it('opens every gate for a ready, fully-named source', () => {
    const source = makeDetail({
      name_status: 'ai_set',
      description_status: 'ai_set',
      latest_job: {
        id: 'j',
        source_id: 'src-1',
        status: 'success',
        started_at: null,
        finished_at: null,
        completed_at: null,
        error_message: null,
        documents_synced: 0,
        documents_indexed: 0,
        chunks_created: 42,
        created_at: '2026-05-09T00:00:00Z',
        updated_at: '2026-05-09T00:00:00Z',
      },
      chunk_count: 42,
      last_synced_at: '2026-05-09T00:05:00Z',
    })
    const { result } = renderHook(() => useLifecycle(source))
    expect(result.current.phase).toBe('ready')
    expect(result.current.canSyncNow).toBe(true)
    expect(result.current.canChat).toBe(true)
    expect(result.current.canMakeAvailableToUsers).toBe(true)
    expect(result.current.canApproveNow).toBe(true)
    expect(result.current.approvalBlockers).toEqual([])
  })

  it('blocks approval when a ready source has an empty description', () => {
    const source = makeDetail({
      name_status: 'user_set',
      description_status: 'user_set',
      description: '',
      chunk_count: 10,
      latest_job: {
        id: 'j',
        source_id: 'src-1',
        status: 'success',
        started_at: null,
        finished_at: null,
        completed_at: null,
        error_message: null,
        documents_synced: 0,
        documents_indexed: 0,
        chunks_created: 10,
        created_at: '2026-05-09T00:00:00Z',
        updated_at: '2026-05-09T00:00:00Z',
      },
      last_synced_at: '2026-05-09T00:05:00Z',
    })
    const { result } = renderHook(() => useLifecycle(source))
    expect(result.current.phase).toBe('ready')
    expect(result.current.canMakeAvailableToUsers).toBe(true)
    // Composite gate AND phase + naming blockers — should be false.
    expect(result.current.canApproveNow).toBe(false)
    expect(result.current.approvalBlockers.length).toBeGreaterThan(0)
  })

  it('locks chat + availability + sync while naming is in flight', () => {
    const source = makeDetail({
      name_status: 'pending_ai',
      description_status: 'pending_ai',
    })
    const { result } = renderHook(() => useLifecycle(source))
    expect(result.current.phase).toBe('naming')
    expect(result.current.canSyncNow).toBe(false)
    expect(result.current.canChat).toBe(false)
    expect(result.current.canMakeAvailableToUsers).toBe(false)
    expect(result.current.canApproveNow).toBe(false)
  })
})
