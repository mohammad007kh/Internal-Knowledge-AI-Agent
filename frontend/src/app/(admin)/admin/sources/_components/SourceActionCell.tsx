'use client'

/**
 * SourceActionCell — the "Verb Column" on /admin/sources.
 *
 * Renders a SINGLE next-step affordance per row, dispatching by source type
 * and the row's lifecycle state. Two verb sets:
 *
 *   • file_upload / pdf / docx / web_url / etc. → file-source verbs
 *       Approve & ingest → Run now → Working on it… → Ready for chat
 *       (or View error / Re-run on the unhappy paths)
 *
 *   • source_type === 'database'               → DB-source verbs
 *       Approve → Queued for study → Studying… → Documented · N tables
 *       (or "Approve to enable" / "Re-study" / "Edit credentials" on the
 *       partial / drift / failed paths)
 *       (Discriminator is `sourceKindOf(type) === 'database'` — the backend
 *       StrEnum emits the literal `'database'`, not a per-dialect string.)
 *
 * The component is callback-driven and pure — no React Query, no hooks
 * except local Popover state. Wave 3 wires the real `onApprove` / `onSync` /
 * `onStudy` / `onRetry` handlers to mutations.
 */

import { isDatabaseSource } from '@/app/(admin)/admin/sources/[id]/_components/sourceTypeMatrix'
import { Button } from '@/components/ui/button'
import { Popover, PopoverContent, PopoverTrigger } from '@/components/ui/popover'
import type { SourceListItem } from '@/lib/api/sources'
import { cn } from '@/lib/utils'
import { CheckCircle2, Loader2 } from 'lucide-react'
import { useState } from 'react'

interface SourceActionCellProps {
  source: SourceListItem
  /**
   * On mobile (`SourceRowCard`) the action stretches full-width below the
   * pip strip. On desktop (`SourcesTable`) it stays compact.
   */
  layout?: 'inline' | 'block'
  /** Triggered when the admin approves a source (any source type). */
  onApprove?: (id: string) => void
  /** File sources: kick off a sync now. */
  onSync?: (id: string) => void
  /** DB sources: kick off (or re-run) the studying agent. */
  onStudy?: (id: string) => void
  /** Retry the last failed step (used by both file + DB error paths). */
  onRetry?: (id: string) => void
  /**
   * Open the error popover. The component manages a local popover by default,
   * but a parent can provide a custom handler (e.g. a global drawer).
   */
  onViewError?: (id: string, message: string) => void
}

const PHASE_LABEL_BY_STUDY_STATE: Record<string, string> = {
  CONNECTING: 'Connecting…',
  INVENTORY: 'Listing tables…',
  COLUMNS: 'Studying columns…',
  SAMPLING: 'Sampling rows…',
  DESCRIBING: 'Describing tables with AI…',
  INDEXING: 'Indexing schema…',
}

function phaseLabel(source: SourceListItem): string {
  const state = source.study_state ?? null
  if (!state) return 'Studying…'
  return PHASE_LABEL_BY_STUDY_STATE[state] ?? 'Studying…'
}

// ---------------------------------------------------------------------------
// File-source verb branch
// ---------------------------------------------------------------------------

interface VerbProps {
  source: SourceListItem
  block: boolean
  onApprove?: (id: string) => void
  onSync?: (id: string) => void
  onStudy?: (id: string) => void
  onRetry?: (id: string) => void
  onViewError?: (id: string, message: string) => void
}

function FileSourceVerb(props: VerbProps) {
  // We accept the full VerbProps so the dispatcher can hand every callback
  // uniformly, but only the file-source-relevant ones are read here. Avoid
  // destructuring the others to satisfy biome's `noUnusedVariables` rule.
  const { source, block, onApprove, onSync, onRetry, onViewError } = props
  const [popoverOpen, setPopoverOpen] = useState(false)
  const job = source.latest_job ?? null
  const buttonHeight = block ? 'h-9' : 'h-7'
  const buttonWidth = block ? 'w-full' : ''
  const chunkCount = job?.chunks_created ?? 0

  // Awaiting approval — never been ingested.
  if (!source.is_active && !job) {
    return (
      <div className={cn('flex flex-col gap-1', block && 'w-full')}>
        <Button
          type="button"
          size="sm"
          aria-label={`Approve and ingest ${source.name}`}
          onClick={() => onApprove?.(source.id)}
          className={cn(buttonHeight, buttonWidth, 'gap-1.5 text-xs font-medium')}
        >
          Approve &amp; ingest
        </Button>
      </div>
    )
  }

  // Queued — approved but no job yet, or job is pending.
  if (source.is_active && (!job || job.status === 'pending')) {
    return (
      <div className={cn('flex flex-col gap-1', block && 'w-full')}>
        <Button
          type="button"
          variant="ghost"
          size="sm"
          aria-label={`Run sync now for ${source.name}`}
          onClick={() => onSync?.(source.id)}
          className={cn(buttonHeight, buttonWidth, 'gap-1.5 text-xs')}
        >
          Run now
        </Button>
        <p className="text-[11px] text-muted-foreground">Will run on next 30-min cycle.</p>
      </div>
    )
  }

  // Running.
  if (job?.status === 'running') {
    return (
      <div
        className={cn(
          'inline-flex items-center gap-2 text-xs italic text-blue-700 dark:text-blue-300',
          block && 'w-full justify-center py-2'
        )}
        role="status"
        aria-label={`${source.name} ingestion running`}
      >
        <Loader2 className="h-3.5 w-3.5 animate-spin" aria-hidden />
        <span>Working on it&hellip;</span>
      </div>
    )
  }

  // Success with chunks — green check.
  if (job?.status === 'success' && chunkCount > 0) {
    return (
      <div
        className={cn(
          'inline-flex items-center gap-1.5 text-xs font-medium text-emerald-700 dark:text-emerald-300',
          block && 'w-full justify-center py-2'
        )}
        aria-label={`${source.name} ready for chat`}
      >
        <CheckCircle2 className="h-3.5 w-3.5" aria-hidden />
        <span>Ready for chat</span>
      </div>
    )
  }

  // Failed — red link, error popover.
  if (job?.status === 'failed') {
    const message = job.error_message ?? 'No error details available.'
    if (onViewError) {
      return (
        <Button
          type="button"
          variant="link"
          size="sm"
          aria-label={`View error for ${source.name}`}
          onClick={() => onViewError(source.id, message)}
          className={cn(
            buttonHeight,
            buttonWidth,
            'px-0 text-xs font-medium text-red-600 hover:text-red-700 dark:text-red-400 dark:hover:text-red-300'
          )}
        >
          View error
        </Button>
      )
    }
    // Fall back to a self-contained popover with a Retry button.
    return (
      <Popover open={popoverOpen} onOpenChange={setPopoverOpen}>
        <PopoverTrigger asChild>
          <Button
            type="button"
            variant="link"
            size="sm"
            aria-label={`View error for ${source.name}`}
            className={cn(
              buttonHeight,
              buttonWidth,
              'px-0 text-xs font-medium text-red-600 hover:text-red-700 dark:text-red-400 dark:hover:text-red-300'
            )}
          >
            View error
          </Button>
        </PopoverTrigger>
        <PopoverContent align="end" className="w-80 space-y-3 p-3 text-xs">
          <div className="space-y-1">
            <p className="font-medium text-foreground">Last sync failed</p>
            <p className="whitespace-pre-wrap break-words text-muted-foreground">{message}</p>
          </div>
          <Button
            type="button"
            size="sm"
            aria-label={`Retry sync for ${source.name}`}
            onClick={() => {
              setPopoverOpen(false)
              onRetry?.(source.id)
            }}
            className="h-7 w-full gap-1.5 text-xs"
          >
            Retry
          </Button>
        </PopoverContent>
      </Popover>
    )
  }

  // Success but 0 chunks — re-run amber.
  if (job?.status === 'success' && chunkCount === 0) {
    return (
      <div className={cn('flex flex-col gap-1', block && 'w-full')}>
        <Button
          type="button"
          variant="outline"
          size="sm"
          aria-label={`Re-run sync for ${source.name}`}
          onClick={() => onSync?.(source.id)}
          className={cn(
            buttonHeight,
            buttonWidth,
            'gap-1.5 border-amber-500/40 text-xs font-medium text-amber-700 hover:bg-amber-500/10 dark:text-amber-300'
          )}
        >
          Re-run · 0 chunks
        </Button>
      </div>
    )
  }

  // Catch-all: render nothing rather than guess.
  return null
}

// ---------------------------------------------------------------------------
// DB-source verb branch
// ---------------------------------------------------------------------------

function DatabaseSourceVerb(props: VerbProps) {
  // DB sources use `onStudy` rather than `onSync`; the unused callback is
  // dropped here intentionally.
  const { source, block, onApprove, onStudy, onRetry, onViewError } = props
  const [popoverOpen, setPopoverOpen] = useState(false)
  const buttonHeight = block ? 'h-9' : 'h-7'
  const buttonWidth = block ? 'w-full' : ''
  const status = source.schema_status ?? null
  const documented = source.tables_documented ?? 0
  const partial = source.tables_partial ?? 0

  // Approve — schema_status null means we've never queued the studying agent.
  if (!source.is_active && status === null) {
    return (
      <Button
        type="button"
        size="sm"
        aria-label={`Approve ${source.name} for studying`}
        onClick={() => onApprove?.(source.id)}
        className={cn(buttonHeight, buttonWidth, 'gap-1.5 text-xs font-medium')}
      >
        Approve
      </Button>
    )
  }

  // Queued. The "queued before any work" state lives on study_state, NOT on
  // schema_status (FX41 — schema_status only emits studying/completed/failed).
  if (source.study_state === 'QUEUED') {
    return (
      <div
        className={cn(
          'inline-flex items-center gap-2 text-xs text-muted-foreground',
          block && 'w-full justify-center py-2'
        )}
        role="status"
        aria-label={`${source.name} queued for study`}
      >
        <span>Queued for study</span>
      </div>
    )
  }

  // Studying — phase label derived from study_state.
  if (status === 'studying') {
    return (
      <div
        className={cn(
          'inline-flex items-center gap-2 text-xs italic text-blue-700 dark:text-blue-300',
          block && 'w-full justify-center py-2'
        )}
        role="status"
        aria-label={`${source.name} studying schema`}
      >
        <Loader2 className="h-3.5 w-3.5 animate-spin" aria-hidden />
        <span>{phaseLabel(source)}</span>
      </div>
    )
  }

  // Ready (completed study), not yet approved — primary "Approve to enable".
  if (status === 'completed' && !source.is_active) {
    const tableLabel = documented === 1 ? '1 table' : `${documented.toLocaleString()} tables`
    return (
      <Button
        type="button"
        size="sm"
        aria-label={`Approve ${source.name} — ${tableLabel} documented`}
        onClick={() => onApprove?.(source.id)}
        className={cn(buttonHeight, buttonWidth, 'gap-1.5 text-xs font-medium')}
      >
        Documented · {tableLabel} · Approve to enable
      </Button>
    )
  }

  // Partial — amber, surface partial counts. READY_PARTIAL is a study_state
  // value (the studying agent shipped a usable schema doc but at least one
  // table failed AI description); schema_status is still "READY" overall, so
  // this branch MUST run before the plain "Ready" branch — otherwise an
  // approved source with partial coverage shows a misleading green check.
  if (source.study_state === 'READY_PARTIAL') {
    const tableLabel = documented === 1 ? '1 table' : `${documented.toLocaleString()} tables`
    return (
      <Button
        type="button"
        variant="outline"
        size="sm"
        aria-label={`Review partial schema documentation for ${source.name}`}
        onClick={() => onStudy?.(source.id)}
        className={cn(
          buttonHeight,
          buttonWidth,
          'gap-1.5 border-amber-500/40 text-xs font-medium text-amber-700 hover:bg-amber-500/10 dark:text-amber-300'
        )}
      >
        Documented · {tableLabel} · {partial.toLocaleString()} partial — review
      </Button>
    )
  }

  // Stale — drift detected. Comes BEFORE the green "Ready" branch so a
  // drift-positive approved source surfaces the re-study CTA instead of the
  // misleading "all good" check. The drift signal lives on
  // `drift_signal_count` (FX41 — schema_status never emits 'stale').
  if ((source.drift_signal_count ?? 0) > 0) {
    return (
      <Button
        type="button"
        variant="outline"
        size="sm"
        aria-label={`Re-study ${source.name} after schema drift`}
        onClick={() => onStudy?.(source.id)}
        className={cn(
          buttonHeight,
          buttonWidth,
          'gap-1.5 border-amber-500/40 text-xs font-medium text-amber-700 hover:bg-amber-500/10 dark:text-amber-300'
        )}
      >
        Schema drift detected · Re-study
      </Button>
    )
  }

  // Ready and approved — green check. (Comes AFTER the READY_PARTIAL and
  // drift guards above so partial coverage / drift on an approved source
  // still surface their CTAs instead of being masked by the green check.)
  if (status === 'completed' && source.is_active) {
    return (
      <div
        className={cn(
          'inline-flex items-center gap-1.5 text-xs font-medium text-emerald-700 dark:text-emerald-300',
          block && 'w-full justify-center py-2'
        )}
        aria-label={`${source.name} ready`}
      >
        <CheckCircle2 className="h-3.5 w-3.5" aria-hidden />
        <span>Ready</span>
      </div>
    )
  }

  // Failed — red link, error popover with phase + retry.
  if (status === 'failed') {
    // NEVER include connection-string text here. Wave 3 will populate
    // `last_error_message` with an admin-readable description; today we use
    // a generic placeholder so the shell is reviewable.
    const phase = source.last_error_phase ?? 'connection'
    const message = source.last_error_message ?? `Failed during ${phase.toLowerCase()} phase.`
    if (onViewError) {
      return (
        <Button
          type="button"
          variant="link"
          size="sm"
          aria-label={`View connection error for ${source.name}`}
          onClick={() => onViewError(source.id, message)}
          className={cn(
            buttonHeight,
            buttonWidth,
            'px-0 text-xs font-medium text-red-600 hover:text-red-700 dark:text-red-400 dark:hover:text-red-300'
          )}
        >
          Connection failed · Edit credentials
        </Button>
      )
    }
    return (
      <Popover open={popoverOpen} onOpenChange={setPopoverOpen}>
        <PopoverTrigger asChild>
          <Button
            type="button"
            variant="link"
            size="sm"
            aria-label={`View connection error for ${source.name}`}
            className={cn(
              buttonHeight,
              buttonWidth,
              'px-0 text-xs font-medium text-red-600 hover:text-red-700 dark:text-red-400 dark:hover:text-red-300'
            )}
          >
            Connection failed · Edit credentials
          </Button>
        </PopoverTrigger>
        <PopoverContent align="end" className="w-80 space-y-3 p-3 text-xs">
          <div className="space-y-1">
            <p className="font-medium text-foreground">Study failed</p>
            <p className="text-[11px] uppercase tracking-wide text-muted-foreground">
              Phase · {phase}
            </p>
            <p className="whitespace-pre-wrap break-words text-muted-foreground">{message}</p>
          </div>
          <Button
            type="button"
            size="sm"
            aria-label={`Retry study for ${source.name}`}
            onClick={() => {
              setPopoverOpen(false)
              onRetry?.(source.id)
            }}
            className="h-7 w-full gap-1.5 text-xs"
          >
            Retry
          </Button>
        </PopoverContent>
      </Popover>
    )
  }

  // Fallback for rows where Wave 3 hasn't populated `schema_status` yet —
  // keep the shell graceful rather than rendering nothing.
  return (
    <span className="text-[11px] italic text-muted-foreground">Connected — pending wiring</span>
  )
}

// ---------------------------------------------------------------------------
// Public dispatcher
// ---------------------------------------------------------------------------

export function SourceActionCell({
  source,
  layout = 'inline',
  onApprove,
  onSync,
  onStudy,
  onRetry,
  onViewError,
}: SourceActionCellProps) {
  const block = layout === 'block'
  const Verb = isDatabaseSource(source.source_type) ? DatabaseSourceVerb : FileSourceVerb
  return (
    <Verb
      source={source}
      block={block}
      onApprove={onApprove}
      onSync={onSync}
      onStudy={onStudy}
      onRetry={onRetry}
      onViewError={onViewError}
    />
  )
}
