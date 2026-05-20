'use client'

/**
 * SyncStatusPill — persistent header indicator for the source's sync state.
 *
 * The pill always lives next to the page title, regardless of the current tab.
 * It reads `source.latest_job` and renders one of four states:
 *
 *   - never:    "Never synced"                 (muted)
 *   - running:  "Syncing… (started 12s ago)"   (blue, pulsing dot)
 *   - success:  "Last sync succeeded 2m ago"   (emerald)
 *   - failed:   "Last sync failed"             (destructive)
 *
 * For DB live sources the verbiage flips to "Studying schema…" / "Schema
 * studied …" / "Schema study failed" — `text_to_query` retrieval / `live`
 * source mode does not ingest documents, so calling the pipeline a "sync"
 * would mislead.
 *
 * Pure presentational component — receives the source and a "live" flag,
 * does no fetching. Keeps the data flow predictable: parent owns polling,
 * child owns visual derivation.
 */

import { Badge } from '@/components/ui/badge'
import type { SourceDetail } from '@/lib/api/sources'
import { formatRelative } from '@/lib/format'
import { cn } from '@/lib/utils'

// `formatRelative` moved to `@/lib/format` (a pure util doesn't belong in a
// component module). Re-exported here so existing importers — which may reach
// for either module — keep working.
export { formatRelative }

// ---------------------------------------------------------------------------
// Pill state derivation
// ---------------------------------------------------------------------------

export type PillState = 'never' | 'running' | 'success' | 'failed'

interface DerivedPill {
  state: PillState
  label: string
  /** Raw timestamp the relative time below is computed from (or null). */
  ts: string | null
}

function derivePill(source: SourceDetail, isDbLiveSource: boolean): DerivedPill {
  const job = source.latest_job
  if (!job) {
    return {
      state: 'never',
      label: isDbLiveSource ? 'Schema not studied' : 'Never synced',
      ts: null,
    }
  }
  if (job.status === 'pending' || job.status === 'running') {
    return {
      state: 'running',
      label: isDbLiveSource ? 'Studying schema…' : 'Syncing…',
      ts: job.started_at,
    }
  }
  if (job.status === 'failed') {
    return {
      state: 'failed',
      label: isDbLiveSource ? 'Schema study failed' : 'Last sync failed',
      ts: job.finished_at ?? job.completed_at ?? job.started_at,
    }
  }
  // success / completed
  return {
    state: 'success',
    label: isDbLiveSource ? 'Schema studied' : 'Last sync succeeded',
    ts: job.finished_at ?? job.completed_at ?? job.started_at,
  }
}

// ---------------------------------------------------------------------------
// Component
// ---------------------------------------------------------------------------

export interface SyncStatusPillProps {
  source: SourceDetail
  isDbLiveSource: boolean
  /** Override `Date.now()` in tests. */
  now?: number
}

export function SyncStatusPill({ source, isDbLiveSource, now }: SyncStatusPillProps) {
  const { state, label, ts } = derivePill(source, isDbLiveSource)

  const palette: Record<PillState, string> = {
    never: 'bg-muted text-muted-foreground border-border',
    running: 'bg-blue-500/15 text-blue-700 dark:text-blue-300 border-blue-500/30',
    success: 'bg-emerald-500/15 text-emerald-700 dark:text-emerald-300 border-emerald-500/30',
    failed: 'bg-destructive/15 text-destructive border-destructive/40',
  }

  const dotPalette: Record<PillState, string> = {
    never: 'bg-muted-foreground/40',
    running: 'bg-blue-500 animate-pulse',
    success: 'bg-emerald-500',
    failed: 'bg-destructive',
  }

  // Compose label + relative time. For "running" we say "started 12s ago"; for
  // success/failed we say the relative time after the label; for "never" we
  // show the label alone.
  let detail: string | null = null
  if (state === 'running') {
    if (ts) detail = `started ${formatRelative(ts, now)}`
  } else if (state === 'success' || state === 'failed') {
    if (ts) detail = formatRelative(ts, now)
  }

  return (
    <Badge
      variant="outline"
      data-testid="sync-status-pill"
      data-state={state}
      role="status"
      aria-live="polite"
      className={cn('gap-1.5 font-medium', palette[state])}
    >
      <span
        aria-hidden
        className={cn('inline-block h-2 w-2 rounded-full', dotPalette[state])}
      />
      <span>{label}</span>
      {detail ? <span className="opacity-80">· {detail}</span> : null}
    </Badge>
  )
}
