'use client'

import type { BudgetActivityEntry, StepActivityEntry } from '@/lib/sse/agent-events'
import { cn } from '@/lib/utils'
import { Check, PenLine } from 'lucide-react'
import { useEffect, useRef, useState } from 'react'
import { ROLE_ICON } from './agent-roles'

const WRAP_UP_LABEL = 'Wrapping up with what I found'
const FLASH_MS = 600

export interface StatusLineProps {
  /** The latest step entry this turn (from `selectActiveStep`), or null pre-plan. */
  activeStep: StepActivityEntry | null
  /** Latest budget note (from `selectLatestBudget`); drives the wrap-up label. */
  budget?: BudgetActivityEntry | null
  /** True once answer tokens begin — the line yields to the streamed markdown. */
  isStreaming: boolean
}

/**
 * Layer-1 live status line (T-071) — the always-visible heartbeat of the agent's
 * work, rendered INSIDE the in-flight assistant bubble in place of the pulsing
 * dots. ONE mutating line, never a stacking log.
 *
 * Anatomy: `[role-glyph] [present-tense label] · [N/M]`.
 *  - progress `· N/M` appears only once a plan exists (`progress.total > 0`);
 *  - amber (never red) on a retrying/failed step — calm-honesty palette;
 *  - a ✓ flash (~600ms) marks a finished step before the next advances;
 *  - a calm wrap-up label replaces progress when the budget ceiling was hit;
 *  - it yields (renders nothing) the moment the answer starts streaming.
 *
 * A11y: a STABLE `aria-live="polite" aria-atomic="true"` wrapper persists for the
 * whole thinking phase; the inner node mutates and goes empty at terminal, so a
 * screen reader hears each status once and stops at the answer.
 */
export function StatusLine({ activeStep, budget, isStreaming }: StatusLineProps) {
  // ✓ flash bookkeeping — fire once per step that reaches `finished`.
  const [flashing, setFlashing] = useState(false)
  const flashedStepId = useRef<string | null>(null)
  const finishedId = activeStep?.state === 'finished' ? activeStep.stepId : null
  useEffect(() => {
    if (finishedId && finishedId !== flashedStepId.current) {
      flashedStepId.current = finishedId
      setFlashing(true)
      const t = setTimeout(() => setFlashing(false), FLASH_MS)
      return () => clearTimeout(t)
    }
  }, [finishedId])

  // ONE stable live region for the whole thinking phase. The inner node mutates
  // (and goes empty at terminal) so a screen reader hears each status once and
  // stops at the answer. NOTE: a plain block wrapper (not `display:contents`) —
  // `contents` can drop the element from the a11y tree in some engines, which
  // would silently disable the announcements this region exists to make.
  return (
    <div aria-live="polite" aria-atomic="true">
      {renderInner({ activeStep, budget, isStreaming, flashing })}
    </div>
  )
}

interface InnerProps extends StatusLineProps {
  flashing: boolean
}

function renderInner({ activeStep, budget, isStreaming, flashing }: InnerProps) {
  // Yield to the streamed answer — the live region goes quiet.
  if (isStreaming) return null

  // Budget ceiling reached: calm wrap-up, supersedes step progress. NOT amber —
  // a ceiling hit is not an error from the user's point of view. This branch
  // intentionally wins over an in-flight `activeStep`: a ceiling event means the
  // agent is synthesizing with what it has and no further steps will run.
  if (budget?.ceilingHit) {
    return (
      <p className="flex min-w-0 items-center gap-1.5 text-sm text-muted-foreground">
        <PenLine className="h-3.5 w-3.5 shrink-0" aria-hidden />
        <span className="min-w-0 truncate">{WRAP_UP_LABEL}</span>
      </p>
    )
  }

  // Pre-plan silent gap: a calm thinking indicator (replaces the pulsing dots).
  // No `role="status"` here — the parent wrapper is already the single polite
  // live region; a nested one would double-announce.
  if (!activeStep) {
    return (
      <p className="flex items-center gap-1.5 text-sm text-muted-foreground">
        <span className="flex items-center gap-1" aria-hidden>
          {[0, 150, 300].map((delay) => (
            <span
              key={delay}
              className="inline-block h-1.5 w-1.5 animate-pulse rounded-full bg-foreground/40 motion-reduce:animate-none"
              style={{ animationDelay: `${delay}ms` }}
            />
          ))}
        </span>
        Thinking…
      </p>
    )
  }

  const trouble = activeStep.state === 'retrying' || activeStep.state === 'failed'
  const isFinished = activeStep.state === 'finished'
  const RoleGlyph = ROLE_ICON[activeStep.role]
  const showProgress = activeStep.progress.total > 0

  return (
    <p
      className={cn(
        'flex min-w-0 items-center gap-1.5 text-sm',
        trouble ? 'text-amber-600 dark:text-amber-400' : 'text-muted-foreground'
      )}
    >
      {isFinished ? (
        <Check
          className={cn(
            'h-3.5 w-3.5 shrink-0 text-emerald-600 dark:text-emerald-400',
            flashing && 'motion-safe:animate-pulse'
          )}
          aria-hidden
        />
      ) : (
        <RoleGlyph className="h-3.5 w-3.5 shrink-0" aria-hidden />
      )}
      {/* Trouble is signalled by colour (amber); pair it with an sr-only token so
          it never depends on the label copy carrying the state (a11y: colour is
          never the sole signal). */}
      {trouble && (
        <span className="sr-only">{activeStep.state === 'failed' ? 'failed: ' : 'retrying: '}</span>
      )}
      <span className="min-w-0 truncate">{activeStep.label}</span>
      {showProgress && (
        <span className="shrink-0 tabular-nums text-muted-foreground">
          {' · '}
          {activeStep.progress.current}/{activeStep.progress.total}
        </span>
      )}
    </p>
  )
}
