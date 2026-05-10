'use client'

/**
 * useSyncJobToast — fires a toast on the terminal transition of a sync job.
 *
 * Policy (locked decisions, do not redesign):
 *   - SUCCESS: only toast for syncs the admin started in this tab/session.
 *     Beat-driven scheduled syncs that complete while the page is open are
 *     SILENT — the status pill flips and the history table updates, no toast.
 *   - FAILURE: ALWAYS toast, regardless of trigger source. A failed sync needs
 *     attention even if a Beat schedule started it. Failure toasts have a
 *     longer duration and include a "View error" action.
 *   - DEDUPE: a job ID is toasted at most once per tab-session, even across
 *     re-renders or remounts. Persisted via sessionStorage so a reload does
 *     not double-toast. Each tab has its own sessionStorage scope — multi-tab
 *     N admins receive N toasts; we don't try to coordinate across tabs.
 *
 * The hook receives:
 *   - `latestJob`: read off `source.latest_job` upstream
 *   - `sessionTriggeredJobIds`: Set<string> of job IDs the admin started in
 *     this session via `useTriggerSync().mutate`. The caller maintains this
 *     set and passes a stable Set instance.
 */

import type { SyncJob } from '@/lib/api/sources'
import { useEffect, useRef } from 'react'
import { toast } from 'sonner'

const SESSION_STORAGE_PREFIX = 'sync-toast:lastTerminal:'

/** Build the per-source sessionStorage key. */
function storageKey(sourceId: string): string {
  return `${SESSION_STORAGE_PREFIX}${sourceId}`
}

/**
 * Read the last-terminal-toasted job id from sessionStorage. Returns `null`
 * if the storage entry is missing, malformed, or sessionStorage itself is
 * unavailable (SSR, privacy mode).
 */
function readLastToasted(sourceId: string): string | null {
  if (typeof window === 'undefined') return null
  try {
    return window.sessionStorage.getItem(storageKey(sourceId))
  } catch {
    return null
  }
}

function writeLastToasted(sourceId: string, jobId: string): void {
  if (typeof window === 'undefined') return
  try {
    window.sessionStorage.setItem(storageKey(sourceId), jobId)
  } catch {
    // sessionStorage unavailable — accept the trade-off (a reload may double-
    // toast). We intentionally do NOT log here: production logs would fill up
    // for every privacy-mode session.
  }
}

export interface UseSyncJobToastArgs {
  sourceId: string
  /** The `latest_job` slice from the source detail payload. Optional/null. */
  latestJob: SyncJob | null | undefined
  /** Set of job IDs the admin started in this tab via the sync mutation. */
  sessionTriggeredJobIds: ReadonlySet<string>
  /**
   * Called when the user clicks the failure toast's "View error" action.
   * Typically scrolls to the sync history row for the failed job. The hook
   * itself doesn't know how to find the row — that's a concern of the page.
   */
  onViewError?: (jobId: string) => void
  /**
   * Re-label the success copy for DB-live sources. When true the toast says
   * "Schema studied" rather than "Sync completed".
   */
  isDbLiveSource?: boolean
}

/**
 * Fire-once-on-terminal-transition toast for sync jobs.
 *
 * The hook tracks two pieces of per-source state:
 *
 *   1. `lastToastedRef` (in-memory): the job ID we most-recently fired a toast
 *      for. Prevents double-firing across React's Strict-Mode double-effect
 *      and across re-renders of the parent.
 *
 *   2. sessionStorage entry (`sync-toast:lastTerminal:{sourceId}`): the same
 *      thing, but persisted across reloads of the same tab. Without this, an
 *      admin who hits Refresh while a sync is mid-flight would get a second
 *      success toast when the page remounts after the job is already
 *      terminal.
 *
 * The hook is intentionally side-effect-only — it returns nothing. Callers
 * should still render their own UI (status pill) so the absence of a toast
 * (Beat-driven success) is not invisible.
 */
export function useSyncJobToast({
  sourceId,
  latestJob,
  sessionTriggeredJobIds,
  onViewError,
  isDbLiveSource = false,
}: UseSyncJobToastArgs): void {
  // Hydrate from sessionStorage on mount so a reload of a page mid-sync
  // doesn't immediately re-toast the just-finished job.
  const lastToastedRef = useRef<string | null>(null)
  const hydratedRef = useRef(false)
  if (!hydratedRef.current) {
    lastToastedRef.current = readLastToasted(sourceId)
    hydratedRef.current = true
  }

  useEffect(() => {
    if (!latestJob) return

    const status = latestJob.status
    const isTerminalSuccess = status === 'success' || status === 'completed'
    const isTerminalFailure = status === 'failed'

    if (!isTerminalSuccess && !isTerminalFailure) return
    if (lastToastedRef.current === latestJob.id) return

    if (isTerminalSuccess) {
      // SUCCESS: only toast for session-triggered jobs. Beat-driven success
      // is silent. We still update the dedupe ref so a future re-render
      // doesn't surface a toast for this job by accident.
      const isSessionTriggered = sessionTriggeredJobIds.has(latestJob.id)
      lastToastedRef.current = latestJob.id
      writeLastToasted(sourceId, latestJob.id)
      if (!isSessionTriggered) return

      const docs = latestJob.documents_indexed
      const chunks = latestJob.chunks_created
      const message = isDbLiveSource
        ? 'Schema studied successfully'
        : `Sync completed — ${docs} doc${docs === 1 ? '' : 's'}, ${chunks} chunk${
            chunks === 1 ? '' : 's'
          }`
      toast.success(message)
      return
    }

    if (isTerminalFailure) {
      lastToastedRef.current = latestJob.id
      writeLastToasted(sourceId, latestJob.id)
      const errorMessage =
        latestJob.error_message ??
        (isDbLiveSource ? 'Schema study failed' : 'Sync failed')
      toast.error(errorMessage, {
        duration: 10_000,
        action: onViewError
          ? {
              label: 'View error',
              onClick: () => onViewError(latestJob.id),
            }
          : undefined,
      })
    }
  }, [latestJob, sessionTriggeredJobIds, sourceId, onViewError, isDbLiveSource])
}
