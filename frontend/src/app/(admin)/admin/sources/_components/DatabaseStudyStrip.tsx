'use client'

/**
 * DatabaseStudyStrip — compact 4-pip horizontal row that surfaces the studying
 * agent's progress on a single DB source on /admin/sources.
 *
 * ## FX34 — unified vocabulary
 *
 * Before FX34 this strip rendered "Connected · Inventoried · Documented ·
 * Ready · Approved" — a leaky abstraction over the studying agent's internal
 * node IDs (CONNECT / INVENTORY / COLUMNS / SAMPLE / DESCRIBE) plus an
 * "Approved" pip that has nothing to do with the worker pipeline at all.
 *
 * The source-detail page (post FX23/FX29b/FX32) shows a SIMPLER, source-kind-
 * aware vocabulary driven by `lifecycle.ts`:
 *
 *     Queued → Naming with AI → Studying schema → Ready
 *
 * FX34 brings this list-row strip in line with the detail page. Same four
 * phases, same labels, same single source of truth (`derivePhase` from
 * `@/features/sources/lifecycle`). Approval is dropped from the strip — it's
 * not a worker phase, and the Mode badge + "Next step" verb cell already
 * communicate availability.
 *
 * Visual treatment is unchanged: same emerald-filled / outlined dots, same
 * Loader2 spinner anchored on the in-flight pip, same CircleAlert on failure.
 *
 * Stages (per `phaseOrderFor('database')`):
 *   Queued           — `derivePhase === 'pending_upload'`
 *   Naming with AI   — `derivePhase === 'naming'`
 *   Studying schema  — `derivePhase === 'analyzing'`
 *   Ready            — `derivePhase === 'ready'`
 *
 * The `failed` phase (job failed, or `schema_status === 'FAILED'`) is rendered
 * as a red tone + CircleAlert on whichever pip the failure anchored on. Where
 * possible we honour `last_error_phase` from the backend so the failure
 * indicator lines up with the actual point of failure; otherwise we anchor on
 * the first non-completed pip in pipeline order (matching IngestionStrip's
 * behaviour).
 */

import { Tooltip, TooltipContent, TooltipProvider, TooltipTrigger } from '@/components/ui/tooltip'
import {
  type Phase,
  derivePhase,
  phaseHint,
  phaseLabel,
  phaseOrderFor,
} from '@/features/sources/lifecycle'
import type { SourceListItem } from '@/lib/api/sources'
import { cn } from '@/lib/utils'
import { CircleAlert, Loader2 } from 'lucide-react'

interface DatabaseStudyStripProps {
  source: SourceListItem
  className?: string
}

type PipPhase = Exclude<Phase, 'failed' | 'chunking'>

interface PipMeta {
  phase: PipPhase
  label: string
  hint: string
  active: boolean
}

/**
 * Map a backend `last_error_phase` token onto one of our pip phases. The
 * backend reports phases at the granularity of the studying agent's node IDs
 * (`CONNECT`, `INVENTORY`, `COLUMNS`, `SAMPLING`, `DESCRIBING`, `INDEXING`);
 * we collapse anything past INVENTORY into `analyzing` since that's the single
 * "Studying schema" chip in the new vocabulary.
 *
 * `CONNECT*` maps to `pending_upload` — the failure happened before the worker
 * even started exploring the schema, which is exactly the "Queued / about to
 * start" pip.
 */
const ERROR_PHASE_TO_PIP_PHASE: Record<string, PipPhase> = {
  CONNECT: 'pending_upload',
  CONNECTING: 'pending_upload',
  INVENTORY: 'analyzing',
  COLUMNS: 'analyzing',
  SAMPLING: 'analyzing',
  DESCRIBING: 'analyzing',
  INDEXING: 'analyzing',
}

function buildPips(source: SourceListItem, phase: Phase): readonly PipMeta[] {
  const order = phaseOrderFor('database')
  // Index of the current (or anchored) phase. For `failed` we anchor on
  // `analyzing` so a failure during schema-study highlights "Studying schema";
  // the per-pip failed flag is computed downstream from `last_error_phase`.
  const anchorPhase: PipPhase =
    phase === 'failed' ? 'analyzing' : (phase as PipPhase)
  const anchorIdx = order.indexOf(anchorPhase)

  return order.map((stepPhase, idx) => {
    const pipPhase = stepPhase as PipPhase
    return {
      phase: pipPhase,
      label: phaseLabel(stepPhase, 'database'),
      hint: phaseHint(stepPhase, 'database'),
      // A pip is "active" if the source has progressed up to or past it. We
      // mirror the IngestionStrip's semantics: prior-step pips light up
      // emerald (done), the current pip lights up too (it's "active"), future
      // pips remain outlined. The Loader2 / CircleAlert overlay lives on the
      // current pip — see `findIndicatorPip` below.
      active: idx <= anchorIdx,
    }
  })
}

/**
 * Pick the pip the studying / failure indicator should anchor on. Honours an
 * explicit `last_error_phase` mapping (FX29-era backend signal) when present;
 * otherwise falls back to the current phase from `derivePhase`.
 */
function findIndicatorPip(
  pips: readonly PipMeta[],
  phase: Phase,
  lastErrorPhase: string | null
): PipPhase | null {
  if (phase === 'failed' && lastErrorPhase) {
    const mapped = ERROR_PHASE_TO_PIP_PHASE[lastErrorPhase.toUpperCase()]
    if (mapped) return mapped
  }
  if (phase === 'failed') return 'analyzing'
  // In-flight: anchor on the current (= last-active) pip.
  for (let i = pips.length - 1; i >= 0; i -= 1) {
    if (pips[i].active) return pips[i].phase
  }
  return pips[0]?.phase ?? null
}

interface PipDotProps {
  pip: PipMeta
  isStudying: boolean
  isFailed: boolean
  failureMessage: string | null
  sourceName: string | undefined
}

function PipDot({ pip, isStudying, isFailed, failureMessage, sourceName }: PipDotProps) {
  const baseDot = 'h-2 w-2 rounded-full transition-colors'
  const failedDot = 'bg-red-500'
  const activeDot = 'bg-emerald-500'
  const inactiveDot = 'border border-zinc-400/50 bg-transparent dark:border-zinc-500/60'

  const dotClass = isFailed ? failedDot : pip.active ? activeDot : inactiveDot

  const labelClass = isFailed
    ? 'text-red-700 dark:text-red-300'
    : pip.active
      ? 'text-foreground'
      : 'text-muted-foreground'

  const ariaParts: string[] = [pip.label, pip.active ? 'completed' : 'pending']
  if (isStudying) ariaParts.push('in progress')
  if (isFailed) ariaParts.push('failed')
  const subjectPrefix = sourceName ? `${sourceName}: ` : ''
  const ariaLabel = `${subjectPrefix}${ariaParts.join(', ')}`

  const tooltipText = isFailed ? (failureMessage ?? 'study failed') : pip.hint

  return (
    <Tooltip>
      <TooltipTrigger asChild>
        <span
          aria-label={ariaLabel}
          data-pip={pip.phase}
          data-active={pip.active ? 'true' : 'false'}
          data-failed={isFailed ? 'true' : 'false'}
          data-studying={isStudying ? 'true' : 'false'}
          className={cn(
            'inline-flex items-center gap-1.5 whitespace-nowrap text-[11px] font-medium leading-none',
            'cursor-default select-none'
          )}
        >
          <span className="relative inline-flex h-2 w-2 items-center justify-center">
            <span className={cn(baseDot, dotClass)} aria-hidden />
            {isStudying ? (
              <Loader2
                className={cn(
                  'absolute -inset-1 h-4 w-4 animate-spin',
                  isFailed ? 'text-red-500' : 'text-blue-500'
                )}
                aria-hidden
              />
            ) : null}
            {isFailed && !isStudying ? (
              <CircleAlert className="absolute -inset-1 h-4 w-4 text-red-500" aria-hidden />
            ) : null}
          </span>
          <span className={cn(labelClass)}>{pip.label}</span>
        </span>
      </TooltipTrigger>
      <TooltipContent side="top" align="center">
        {tooltipText}
      </TooltipContent>
    </Tooltip>
  )
}

function Connector({ filled }: { filled: boolean }) {
  return (
    <span
      aria-hidden
      className={cn(
        'h-px w-3 shrink-0 transition-colors sm:w-4',
        filled ? 'bg-emerald-500/60' : 'bg-zinc-300/70 dark:bg-zinc-600/60'
      )}
    />
  )
}

export function DatabaseStudyStrip({ source, className }: DatabaseStudyStripProps) {
  const phase = derivePhase(source)
  const pips = buildPips(source, phase)
  const lastErrorPhase = source.last_error_phase ?? null

  const isFailed = phase === 'failed'
  // "Studying" = there's actual worker progress in flight. We treat any
  // non-terminal phase (`pending_upload` / `naming` / `analyzing`) as
  // in-flight for the spinner overlay, matching IngestionStrip's
  // `RUNNING_STATUSES` semantics.
  const isStudying =
    !isFailed && (phase === 'pending_upload' || phase === 'naming' || phase === 'analyzing')

  const indicatorPip =
    isStudying || isFailed ? findIndicatorPip(pips, phase, lastErrorPhase) : null

  // Failure message previewed in the tooltip. We do NOT surface raw
  // backend error strings here because connection strings, stack
  // traces, or internal hostnames can land in `last_error_message` /
  // `latest_job.error_message` from driver exceptions, and every admin
  // who hovers the row would see them. The detail page's Schema tab
  // sanitises + renders the full reason; the list-row tooltip just
  // tells the admin to look there. (Reversed FX34 reviewer HIGH.)
  const failureMessage: string | null = isFailed
    ? 'Study failed — open the source for details'
    : null

  // Screen-reader summary; matches IngestionStrip's role="status" pattern.
  const summary = pips.map((p) => `${p.label}${p.active ? ' done' : ' pending'}`).join('; ')
  const subject = source.name
    ? `Schema study progress for ${source.name}`
    : 'Schema study progress'

  return (
    <TooltipProvider delayDuration={120}>
      <div
        role="status"
        aria-label={`${subject}: ${summary}${
          isFailed ? '; study failed' : isStudying ? '; study in progress' : ''
        }`}
        className={cn('inline-flex flex-wrap items-center gap-x-2 gap-y-1', className)}
      >
        {pips.map((pip, idx) => {
          const isPipStudying = isStudying && indicatorPip === pip.phase
          const isPipFailed = isFailed && indicatorPip === pip.phase
          return (
            <span key={pip.phase} className="inline-flex items-center gap-2">
              <PipDot
                pip={pip}
                isStudying={isPipStudying}
                isFailed={isPipFailed}
                failureMessage={failureMessage}
                sourceName={source.name}
              />
              {idx < pips.length - 1 ? (
                <Connector filled={pip.active && pips[idx + 1].active} />
              ) : null}
            </span>
          )
        })}
      </div>
    </TooltipProvider>
  )
}
