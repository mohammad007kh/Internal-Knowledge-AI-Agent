/**
 * useSyncJobToast — fires once on terminal transition.
 *
 * Locked policy:
 *   - SUCCESS: only toast for session-triggered jobs.
 *   - FAILURE: ALWAYS toast (regardless of trigger source).
 *   - DEDUPE: same job ID never toasts twice in one tab session.
 *   - PERSIST: dedupe survives a reload via sessionStorage.
 */
import { render } from '@testing-library/react'
import type { ReactNode } from 'react'
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'

import type { SyncJob } from '@/lib/api/sources'

const toastSuccessMock = vi.fn()
const toastErrorMock = vi.fn()

vi.mock('sonner', () => ({
  toast: {
    success: (...args: unknown[]) => toastSuccessMock(...args),
    error: (...args: unknown[]) => toastErrorMock(...args),
  },
}))

import { useSyncJobToast } from '../useSyncJobToast'

// ---------------------------------------------------------------------------
// Fixtures + harness
// ---------------------------------------------------------------------------

function makeJob(overrides: Partial<SyncJob> = {}): SyncJob {
  return {
    id: 'job-1',
    source_id: 'src-1',
    status: 'running',
    started_at: '2026-05-09T12:00:00Z',
    finished_at: null,
    completed_at: null,
    error_message: null,
    documents_synced: 0,
    documents_indexed: 12,
    chunks_created: 47,
    created_at: '2026-05-09T12:00:00Z',
    updated_at: '2026-05-09T12:00:00Z',
    ...overrides,
  }
}

interface HarnessProps {
  sourceId?: string
  latestJob: SyncJob | null
  sessionTriggeredJobIds: Set<string>
  onViewError?: (jobId: string) => void
  isDbLiveSource?: boolean
}

function Harness({
  sourceId = 'src-1',
  latestJob,
  sessionTriggeredJobIds,
  onViewError,
  isDbLiveSource,
}: HarnessProps): ReactNode {
  useSyncJobToast({
    sourceId,
    latestJob,
    sessionTriggeredJobIds,
    onViewError,
    isDbLiveSource,
  })
  return null
}

// ---------------------------------------------------------------------------
// Test setup
// ---------------------------------------------------------------------------

beforeEach(() => {
  toastSuccessMock.mockReset()
  toastErrorMock.mockReset()
  window.sessionStorage.clear()
})

afterEach(() => {
  vi.clearAllMocks()
})

// ---------------------------------------------------------------------------
// Tests
// ---------------------------------------------------------------------------

describe('useSyncJobToast — success toast policy', () => {
  it('fires success toast when a session-triggered job transitions to success', () => {
    const sessionIds = new Set<string>(['job-1'])
    const job = makeJob({ status: 'success', documents_indexed: 12, chunks_created: 47 })

    render(<Harness latestJob={job} sessionTriggeredJobIds={sessionIds} />)

    expect(toastSuccessMock).toHaveBeenCalledTimes(1)
    expect(toastSuccessMock).toHaveBeenCalledWith(
      'Sync completed — 12 docs, 47 chunks'
    )
    expect(toastErrorMock).not.toHaveBeenCalled()
  })

  it('uses singular "doc" / "chunk" copy when counts are 1', () => {
    const sessionIds = new Set<string>(['job-1'])
    const job = makeJob({ status: 'success', documents_indexed: 1, chunks_created: 1 })

    render(<Harness latestJob={job} sessionTriggeredJobIds={sessionIds} />)

    expect(toastSuccessMock).toHaveBeenCalledWith('Sync completed — 1 doc, 1 chunk')
  })

  it('stays SILENT for Beat-driven success (job NOT in session set)', () => {
    const sessionIds = new Set<string>() // empty — Beat triggered
    const job = makeJob({ status: 'success' })

    render(<Harness latestJob={job} sessionTriggeredJobIds={sessionIds} />)

    expect(toastSuccessMock).not.toHaveBeenCalled()
    expect(toastErrorMock).not.toHaveBeenCalled()
  })

  it('uses "Schema studied successfully" copy for DB-live sources', () => {
    const sessionIds = new Set<string>(['job-1'])
    const job = makeJob({ status: 'completed' })

    render(
      <Harness latestJob={job} sessionTriggeredJobIds={sessionIds} isDbLiveSource={true} />
    )

    expect(toastSuccessMock).toHaveBeenCalledWith('Schema studied successfully')
  })

  it('does not double-toast across re-renders for the same job', () => {
    const sessionIds = new Set<string>(['job-1'])
    const job = makeJob({ status: 'success' })

    const { rerender } = render(
      <Harness latestJob={job} sessionTriggeredJobIds={sessionIds} />
    )
    rerender(<Harness latestJob={job} sessionTriggeredJobIds={sessionIds} />)
    rerender(<Harness latestJob={job} sessionTriggeredJobIds={sessionIds} />)

    expect(toastSuccessMock).toHaveBeenCalledTimes(1)
  })
})

describe('useSyncJobToast — failure toast policy', () => {
  it('ALWAYS fires error toast on failure (session-triggered)', () => {
    const sessionIds = new Set<string>(['job-1'])
    const job = makeJob({ status: 'failed', error_message: 'connection refused' })

    render(<Harness latestJob={job} sessionTriggeredJobIds={sessionIds} />)

    expect(toastErrorMock).toHaveBeenCalledTimes(1)
    expect(toastErrorMock).toHaveBeenCalledWith(
      'connection refused',
      expect.objectContaining({ duration: 10_000 })
    )
  })

  it('ALWAYS fires error toast on failure (Beat-driven)', () => {
    const sessionIds = new Set<string>() // not session-triggered
    const job = makeJob({ status: 'failed', error_message: 'timeout' })

    render(<Harness latestJob={job} sessionTriggeredJobIds={sessionIds} />)

    expect(toastErrorMock).toHaveBeenCalledTimes(1)
    expect(toastErrorMock).toHaveBeenCalledWith(
      'timeout',
      expect.objectContaining({ duration: 10_000 })
    )
  })

  it('falls back to generic copy when error_message is null', () => {
    const sessionIds = new Set<string>()
    const job = makeJob({ status: 'failed', error_message: null })

    render(<Harness latestJob={job} sessionTriggeredJobIds={sessionIds} />)

    expect(toastErrorMock).toHaveBeenCalledWith('Sync failed', expect.any(Object))
  })

  it('uses DB-live copy for failed schema studies', () => {
    const sessionIds = new Set<string>()
    const job = makeJob({ status: 'failed', error_message: null })

    render(
      <Harness latestJob={job} sessionTriggeredJobIds={sessionIds} isDbLiveSource={true} />
    )

    expect(toastErrorMock).toHaveBeenCalledWith(
      'Schema study failed',
      expect.any(Object)
    )
  })

  it('attaches a "View error" action when onViewError is supplied', () => {
    const sessionIds = new Set<string>(['job-1'])
    const onViewError = vi.fn()
    const job = makeJob({ status: 'failed', error_message: 'oops' })

    render(
      <Harness
        latestJob={job}
        sessionTriggeredJobIds={sessionIds}
        onViewError={onViewError}
      />
    )

    expect(toastErrorMock).toHaveBeenCalledTimes(1)
    const call = toastErrorMock.mock.calls[0]
    const opts = call[1] as {
      action?: { label: string; onClick: () => void }
    }
    expect(opts.action?.label).toBe('View error')
    opts.action?.onClick()
    expect(onViewError).toHaveBeenCalledWith('job-1')
  })
})

describe('useSyncJobToast — dedupe + sessionStorage', () => {
  it('does NOT fire when latestJob is null', () => {
    render(<Harness latestJob={null} sessionTriggeredJobIds={new Set()} />)
    expect(toastSuccessMock).not.toHaveBeenCalled()
    expect(toastErrorMock).not.toHaveBeenCalled()
  })

  it('does NOT fire while job is still pending/running', () => {
    const job = makeJob({ status: 'running' })
    render(<Harness latestJob={job} sessionTriggeredJobIds={new Set(['job-1'])} />)
    expect(toastSuccessMock).not.toHaveBeenCalled()
  })

  it('persists last-toasted job id to sessionStorage', () => {
    const sessionIds = new Set<string>(['job-1'])
    const job = makeJob({ status: 'success' })

    render(<Harness latestJob={job} sessionTriggeredJobIds={sessionIds} />)

    const stored = window.sessionStorage.getItem('sync-toast:lastTerminal:src-1')
    expect(stored).toBe('job-1')
  })

  it('does NOT re-toast on remount when sessionStorage already has the job id', () => {
    // Simulate a previous toast fire — sessionStorage has the dedupe sentinel.
    window.sessionStorage.setItem('sync-toast:lastTerminal:src-1', 'job-1')

    const sessionIds = new Set<string>(['job-1'])
    const job = makeJob({ status: 'success' })

    render(<Harness latestJob={job} sessionTriggeredJobIds={sessionIds} />)

    expect(toastSuccessMock).not.toHaveBeenCalled()
  })

  it('toasts again for a NEW job id, even if a previous one is in sessionStorage', () => {
    window.sessionStorage.setItem('sync-toast:lastTerminal:src-1', 'job-old')

    const sessionIds = new Set<string>(['job-new'])
    const job = makeJob({ id: 'job-new', status: 'success' })

    render(<Harness latestJob={job} sessionTriggeredJobIds={sessionIds} />)

    expect(toastSuccessMock).toHaveBeenCalledTimes(1)
    expect(window.sessionStorage.getItem('sync-toast:lastTerminal:src-1')).toBe(
      'job-new'
    )
  })

  it('scopes sessionStorage by sourceId — different sources don\'t collide', () => {
    const sessionIds = new Set<string>(['job-1'])
    const job = makeJob({ status: 'success' })

    render(
      <>
        <Harness sourceId="src-1" latestJob={job} sessionTriggeredJobIds={sessionIds} />
        <Harness
          sourceId="src-2"
          latestJob={makeJob({ id: 'job-2', source_id: 'src-2', status: 'success' })}
          sessionTriggeredJobIds={new Set(['job-2'])}
        />
      </>
    )

    expect(window.sessionStorage.getItem('sync-toast:lastTerminal:src-1')).toBe('job-1')
    expect(window.sessionStorage.getItem('sync-toast:lastTerminal:src-2')).toBe('job-2')
  })

  it('handles a running → success transition by toasting once on the success render', () => {
    const sessionIds = new Set<string>(['job-1'])
    const running = makeJob({ status: 'running' })
    const success = makeJob({ status: 'success' })

    const { rerender } = render(
      <Harness latestJob={running} sessionTriggeredJobIds={sessionIds} />
    )
    expect(toastSuccessMock).not.toHaveBeenCalled()

    rerender(<Harness latestJob={success} sessionTriggeredJobIds={sessionIds} />)

    expect(toastSuccessMock).toHaveBeenCalledTimes(1)
  })
})
