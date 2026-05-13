'use client'

/**
 * LifecycleStepper — horizontal chip strip showing where in the ingestion
 * pipeline the source is.
 *
 * Renders one chip per stage from `PHASE_ORDER`. The current step pulses; all
 * preceding steps are filled emerald; the active "failed" tone is applied to
 * whichever step the worker died on (anchored to the first incomplete step).
 *
 * Pure presentational — receives the phase, no fetching of its own.
 */

import { Tooltip, TooltipContent, TooltipProvider, TooltipTrigger } from '@/components/ui/tooltip'
import { type Phase, PHASE_ORDER, phaseLabel } from '@/features/sources/lifecycle'
import { cn } from '@/lib/utils'
import { CheckIcon, CircleAlertIcon, Loader2Icon } from 'lucide-react'

interface LifecycleStepperProps {
  phase: Phase
  /** When `true`, swap the "Waiting for upload" copy for an upload-source-
   *  agnostic phrase. Defaults to `false`. */
  hideFirstStepLabel?: boolean
  className?: string
}

const STEP_HINTS: Record<(typeof PHASE_ORDER)[number], string> = {
  pending_upload: 'Files are landing in object storage.',
  naming: 'The AI is drafting a name and description.',
  chunking: 'Splitting the content into retrieval-friendly chunks.',
  analyzing: 'Embedding chunks and finalizing the index.',
  ready: 'This source is ready to query.',
}

function stepIndex(phase: Phase): number {
  // failed renders inside whichever step we were last on; default to chunking.
  if (phase === 'failed') return PHASE_ORDER.indexOf('chunking')
  return PHASE_ORDER.indexOf(phase)
}

interface StepChipProps {
  index: number
  currentIndex: number
  phase: Phase
  isFailed: boolean
  label: string
  hint: string
}

function StepChip({ index, currentIndex, phase, isFailed, label, hint }: StepChipProps) {
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
          data-phase={PHASE_ORDER[index]}
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

export function LifecycleStepper({ phase, hideFirstStepLabel = false, className }: LifecycleStepperProps) {
  const currentIndex = stepIndex(phase)
  const isFailed = phase === 'failed'

  return (
    <TooltipProvider delayDuration={150}>
      <div
        data-testid="lifecycle-stepper"
        data-phase={phase}
        role="list"
        aria-label="Source lifecycle progress"
        className={cn('inline-flex flex-wrap items-center gap-y-2', className)}
      >
        {PHASE_ORDER.map((stepPhase, idx) => {
          const label =
            hideFirstStepLabel && stepPhase === 'pending_upload'
              ? 'Queued'
              : phaseLabel(stepPhase)
          return (
            <span key={stepPhase} role="listitem" className="inline-flex items-center">
              <StepChip
                index={idx}
                currentIndex={currentIndex}
                phase={phase}
                isFailed={isFailed}
                label={label}
                hint={STEP_HINTS[stepPhase]}
              />
              {idx < PHASE_ORDER.length - 1 ? (
                <Connector done={idx < currentIndex} />
              ) : null}
            </span>
          )
        })}
      </div>
    </TooltipProvider>
  )
}
