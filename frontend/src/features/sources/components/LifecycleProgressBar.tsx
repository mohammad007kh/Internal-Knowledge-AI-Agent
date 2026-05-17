'use client'

/**
 * LifecycleProgressBar — animated progress bar that surfaces ingestion
 * progress (FX16). Render when the source is in flight; collapses to null
 * once the source is `ready` or `failed`.
 *
 * Visual treatment:
 *   - Phase has a real percent (we approximate per stage) → solid fill bar.
 *   - Phase is indeterminate (waiting for upload) → striped marquee.
 *   - Active phase animates a subtle shimmer over the fill to convey motion.
 *
 * No fetching; pure presentational. The parent passes `phase` from
 * `derivePhase(source)`.
 */

import {
  type Phase,
  type SourceKind,
  isInFlightPhase,
  phaseLabel,
  phaseProgress,
} from '@/features/sources/lifecycle'
import { cn } from '@/lib/utils'

interface LifecycleProgressBarProps {
  phase: Phase
  className?: string
  /** Optional sub-line shown beneath the bar (e.g. "started 12s ago"). */
  detail?: string | null
  /**
   * FX26 — when true (file source with bytes in object storage) the
   * `pending_upload` label flips to "Queued for indexing" to match the
   * stepper. Default `false` keeps the existing copy for legacy callers.
   */
  hasUpload?: boolean
  /**
   * FX29b — the source's coarse kind (file / web / database / connector).
   * Drives `phaseLabel` so a web_url source in `pending_upload` reads
   * "Queued" instead of the file-pipeline "Waiting for upload". Defaults
   * to `'file'` so older call sites keep the legacy file-centric copy.
   */
  sourceKind?: SourceKind
}

export function LifecycleProgressBar({
  phase,
  className,
  detail,
  hasUpload = false,
  sourceKind = 'file',
}: LifecycleProgressBarProps) {
  // FX16 contract: progress bar disappears when the process is done.
  if (!isInFlightPhase(phase)) return null

  const percent = phaseProgress(phase)
  const indeterminate = phase === 'pending_upload'
  const label = phaseLabel(phase, sourceKind, { hasUpload })

  return (
    <div
      data-testid="lifecycle-progress-bar"
      data-phase={phase}
      data-indeterminate={indeterminate ? 'true' : 'false'}
      className={cn(
        'rounded-md border bg-card px-3 py-2.5 shadow-sm',
        className
      )}
      role="status"
      aria-live="polite"
    >
      <div className="mb-1.5 flex items-baseline justify-between gap-3">
        <p className="text-xs font-medium text-foreground">{label}</p>
        {!indeterminate ? (
          <p
            className="text-xs tabular-nums text-muted-foreground"
            data-testid="lifecycle-progress-percent"
          >
            {percent}%
          </p>
        ) : (
          <p className="text-xs italic text-muted-foreground">working…</p>
        )}
      </div>
      <div
        className="relative h-1.5 w-full overflow-hidden rounded-full bg-muted"
        role="progressbar"
        aria-valuemin={0}
        aria-valuemax={100}
        aria-valuenow={indeterminate ? undefined : percent}
        aria-label={`${label} progress`}
      >
        {indeterminate ? (
          <span
            aria-hidden
            className={cn(
              'absolute inset-y-0 left-0 w-1/3 rounded-full',
              'bg-gradient-to-r from-transparent via-blue-500/70 to-transparent',
              'animate-[lifecycle-marquee_1.4s_linear_infinite]'
            )}
          />
        ) : (
          <span
            aria-hidden
            className={cn(
              'block h-full rounded-full bg-blue-500 transition-[width] duration-500 ease-out',
              'relative overflow-hidden'
            )}
            style={{ width: `${percent}%` }}
          >
            <span
              aria-hidden
              className={cn(
                'absolute inset-y-0 left-0 w-1/3',
                'bg-gradient-to-r from-transparent via-white/40 to-transparent',
                'animate-[lifecycle-shimmer_1.6s_linear_infinite]'
              )}
            />
          </span>
        )}
      </div>
      {detail ? (
        <p
          className="mt-1.5 text-xs text-muted-foreground"
          data-testid="lifecycle-progress-detail"
        >
          {detail}
        </p>
      ) : null}
    </div>
  )
}
