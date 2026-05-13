'use client'

/**
 * LifecycleStepper — horizontal chip strip showing where in the ingestion
 * pipeline the source is.
 *
 * Renders one chip per stage from `phaseOrderFor(sourceKind)`. The current
 * step pulses; all preceding steps are filled emerald; the "failed" tone is
 * applied to whichever step the worker died on (anchored on `analyzing` —
 * the last in-flight phase before `ready` in every per-kind order).
 *
 * FX23: labels + hints + phase order are now source-kind aware. DB sources
 * skip the `chunking` chip and read "Studying schema" for analyzing; web
 * sources show "Crawling content" for the chunking step. File sources keep
 * the existing copy. Connectors mirror web.
 *
 * Pure presentational — receives the phase + kind, no fetching of its own.
 */

import { Tooltip, TooltipContent, TooltipProvider, TooltipTrigger } from '@/components/ui/tooltip'
import {
  type Phase,
  type SourceKind,
  phaseHint,
  phaseLabel,
  phaseOrderFor,
} from '@/features/sources/lifecycle'
import { cn } from '@/lib/utils'
import { CheckIcon, CircleAlertIcon, Loader2Icon } from 'lucide-react'

interface LifecycleStepperProps {
  phase: Phase
  /**
   * Coarse "kind" of the source, used to pick the right per-step labels and
   * the right ordered list of chips. Defaults to `'file'` so the few callers
   * that haven't been migrated render exactly the previous behaviour.
   */
  sourceKind?: SourceKind
  className?: string
}

/**
 * Anchor for the `failed` tone. In every per-kind order the last in-flight
 * step before `ready` is `analyzing`, so we anchor `failed` there: the chip
 * reads "Failed during {analyzing label}" which surfaces the right verb for
 * each source kind ("Failed during studying schema" for DB, "Failed during
 * analyzing & indexing" for file/web).
 *
 * If the chosen kind doesn't include `analyzing` (it always does today —
 * defensive only), we fall back to the last non-`ready` step in the order.
 */
function failedAnchorIndex(
  order: ReadonlyArray<Exclude<Phase, 'failed'>>
): number {
  const idx = order.indexOf('analyzing')
  if (idx >= 0) return idx
  // Fallback: the step immediately before `ready`, or 0 if even that fails.
  const readyIdx = order.indexOf('ready')
  return readyIdx > 0 ? readyIdx - 1 : 0
}

function stepIndex(
  phase: Phase,
  order: ReadonlyArray<Exclude<Phase, 'failed'>>
): number {
  if (phase === 'failed') return failedAnchorIndex(order)
  return order.indexOf(phase as Exclude<Phase, 'failed'>)
}

interface StepChipProps {
  index: number
  currentIndex: number
  stepPhase: Exclude<Phase, 'failed'>
  isFailed: boolean
  label: string
  hint: string
}

function StepChip({ index, currentIndex, stepPhase, isFailed, label, hint }: StepChipProps) {
  const isDone = index < currentIndex
  const isActive = index === currentIndex
  const isActiveFailed = isActive && isFailed

  const baseClasses =
    'relative flex items-center gap-1.5 rounded-full border px-2.5 py-1 text-xs font-medium transition-colors whitespace-nowrap'

  const palette = isActiveFailed
    ? 'border-destructive/40 bg-destructive/10 text-destructive'
    : isActive
      ? 'border-blue-500/40 bg-blue-500/10 text-blue-700 dark:text-blue-300'
      : isDone
        ? 'border-emerald-500/40 bg-emerald-500/10 text-emerald-700 dark:text-emerald-300'
        : 'border-border bg-muted/40 text-muted-foreground'

  // The chip itself is the tooltip trigger; the parent provider supplies
  // delay configuration so we don't need a fresh <TooltipProvider> per chip.
  return (
    <Tooltip>
      <TooltipTrigger asChild>
        <span
          data-testid="lifecycle-step"
          data-phase={stepPhase}
          data-state={
            isActiveFailed
              ? 'failed'
              : isActive
                ? 'active'
                : isDone
                  ? 'done'
                  : 'pending'
          }
          className={cn(baseClasses, palette)}
          aria-current={isActive ? 'step' : undefined}
        >
          {isActiveFailed ? (
            <CircleAlertIcon className="h-3 w-3" aria-hidden />
          ) : isActive ? (
            <Loader2Icon className="h-3 w-3 animate-spin" aria-hidden />
          ) : isDone ? (
            <CheckIcon className="h-3 w-3" aria-hidden />
          ) : (
            <span
              className="inline-block h-1.5 w-1.5 rounded-full bg-current opacity-50"
              aria-hidden
            />
          )}
          <span>{label}</span>
        </span>
      </TooltipTrigger>
      <TooltipContent side="bottom" className="max-w-[220px] text-xs">
        {isActiveFailed
          ? `Failed during ${label.toLowerCase()}.`
          : isActive
            ? hint
            : isDone
              ? `${label} complete.`
              : `${label} — not started.`}
      </TooltipContent>
    </Tooltip>
  )
}

function Connector({ done }: { done: boolean }) {
  return (
    <span
      aria-hidden
      className={cn(
        'h-px w-3 shrink-0 transition-colors sm:w-5',
        done ? 'bg-emerald-500/60' : 'bg-border'
      )}
    />
  )
}

export function LifecycleStepper({
  phase,
  sourceKind = 'file',
  className,
}: LifecycleStepperProps) {
  const order = phaseOrderFor(sourceKind)
  const currentIndex = stepIndex(phase, order)
  const isFailed = phase === 'failed'

  return (
    <TooltipProvider delayDuration={150}>
      <div
        data-testid="lifecycle-stepper"
        data-phase={phase}
        data-source-kind={sourceKind}
        role="list"
        aria-label="Source lifecycle progress"
        className={cn('inline-flex flex-wrap items-center gap-y-2', className)}
      >
        {order.map((stepPhase, idx) => (
          <span key={stepPhase} role="listitem" className="inline-flex items-center">
            <StepChip
              index={idx}
              currentIndex={currentIndex}
              stepPhase={stepPhase}
              isFailed={isFailed}
              label={phaseLabel(stepPhase, sourceKind)}
              hint={phaseHint(stepPhase, sourceKind)}
            />
            {idx < order.length - 1 ? (
              <Connector done={idx < currentIndex} />
            ) : null}
          </span>
        ))}
      </div>
    </TooltipProvider>
  )
}
