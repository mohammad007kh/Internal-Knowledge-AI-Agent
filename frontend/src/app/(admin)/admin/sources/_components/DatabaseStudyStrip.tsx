'use client'

/**
 * DatabaseStudyStrip — five-pip horizontal row that surfaces the studying
 * agent's progress on a single DB source, mirroring the visual treatment of
 * the file-source `IngestionStrip`.
 *
 * Pips:
 *   Connected   — TCP/SSL handshake succeeded and the inventory phase started
 *                 (any `study_state` other than QUEUED / CONNECT_FAILED).
 *   Inventoried — The agent listed tables (state ∈ COLUMNS/SAMPLING/DESCRIBING/
 *                 INDEXING/READY/READY_PARTIAL, or any *_FAILED that fired
 *                 *after* INVENTORY).
 *   Documented  — Per-column inspection succeeded — proxy "we have something
 *                 worth describing" (state ∈ SAMPLING/DESCRIBING/INDEXING/
 *                 READY/READY_PARTIAL). Shows a `(n)` count when ≥1 table is
 *                 documented.
 *   Ready       — `study_state === READY || READY_PARTIAL`.
 *   Approved    — Admin flipped is_active=true.
 *
 * Live signal:
 *   - schema_status === 'STUDYING' → blue Loader2 spinner anchored on the
 *     first incomplete pip (the work-in-progress phase).
 *   - schema_status === 'FAILED' → red CircleAlert on the failed pip,
 *     resolved from `last_error_phase` (or last incomplete pip as fallback).
 *
 * This component renders against MOCKED state today. Wave 3 wires the real
 * `schema_status` / `study_state` / count fields straight from the API; the
 * pip activation logic is intentionally identical to what Wave 3 will use, so
 * no rewrites are needed at hookup time.
 */

import { Tooltip, TooltipContent, TooltipProvider, TooltipTrigger } from '@/components/ui/tooltip'
import type { SchemaStatus, StudyState } from '@/lib/api/sources'
import { cn } from '@/lib/utils'
import { CircleAlert, Loader2 } from 'lucide-react'

interface DatabaseStudyStripProps {
  schemaStatus: SchemaStatus | null
  /** Same vocabulary as the backend `SchemaStudy.study_state` column. */
  studyState: StudyState | string | null
  isApproved: boolean
  tablesDocumented: number | null
  /**
   * Phase string the backend reports when a study fails (e.g. 'CONNECT',
   * 'INVENTORY', 'COLUMNS', 'SAMPLING', 'DESCRIBING', 'INDEXING'). When set
   * we anchor the failure indicator on the matching pip; otherwise we fall
   * back to the first incomplete pip in pipeline order.
   */
  lastErrorPhase: string | null
  /** Optional source name for screen-reader summaries. */
  sourceName?: string
  className?: string
}

type PipId = 'connected' | 'inventoried' | 'documented' | 'ready' | 'approved'

interface PipMeta {
  id: PipId
  label: string
  tooltip: string
  active: boolean
}

const PIP_ORDER: readonly PipId[] = [
  'connected',
  'inventoried',
  'documented',
  'ready',
  'approved',
] as const

const POST_INVENTORY_STATES: readonly StudyState[] = [
  // INVENTORY itself is included: the pip lights up the moment the worker
  // enters the inventory phase, not only after it finishes. The spinner /
  // in-flight indicator (anchored on the next inactive pip) tells the user
  // we're still working — without that, the user sees "queued" frozen until
  // a whole phase elapses.
  'INVENTORY',
  'COLUMNS',
  'SAMPLING',
  'DESCRIBING',
  'INDEXING',
  'READY',
  'READY_PARTIAL',
]
const POST_INVENTORY_FAILED_STATES: readonly StudyState[] = [
  'COLUMNS_FAILED',
  'SAMPLING_FAILED',
  'DESCRIBING_FAILED',
  'INDEXING_FAILED',
]
const POST_DESCRIBE_STATES: readonly StudyState[] = [
  'SAMPLING',
  'DESCRIBING',
  'INDEXING',
  'READY',
  'READY_PARTIAL',
]
const READY_STATES: readonly StudyState[] = ['READY', 'READY_PARTIAL']

/** Map a `last_error_phase` string to the pip the indicator should anchor on. */
const ERROR_PHASE_TO_PIP: Record<string, PipId> = {
  CONNECT: 'connected',
  CONNECTING: 'connected',
  INVENTORY: 'inventoried',
  COLUMNS: 'inventoried',
  SAMPLING: 'documented',
  DESCRIBING: 'documented',
  INDEXING: 'ready',
}

function isConnected(state: StudyState | string | null): boolean {
  if (!state) return false
  return state !== 'QUEUED' && state !== 'CONNECT_FAILED' && state !== 'CONNECTING'
}

function isInventoried(state: StudyState | string | null): boolean {
  if (!state) return false
  return (
    (POST_INVENTORY_STATES as readonly string[]).includes(state) ||
    (POST_INVENTORY_FAILED_STATES as readonly string[]).includes(state)
  )
}

function isDocumented(state: StudyState | string | null): boolean {
  if (!state) return false
  return (POST_DESCRIBE_STATES as readonly string[]).includes(state)
}

function isReady(state: StudyState | string | null): boolean {
  if (!state) return false
  return (READY_STATES as readonly string[]).includes(state)
}

function buildPips(props: DatabaseStudyStripProps): readonly PipMeta[] {
  const { studyState, isApproved, tablesDocumented } = props
  const documented = isDocumented(studyState)
  const docCount = tablesDocumented ?? 0
  const documentedLabel =
    documented && docCount > 0 ? `Documented (${docCount.toLocaleString()})` : 'Documented'

  return [
    {
      id: 'connected',
      label: 'Connected',
      tooltip: 'Database handshake succeeded',
      active: isConnected(studyState),
    },
    {
      id: 'inventoried',
      label: 'Inventoried',
      tooltip: 'Tables listed from information_schema',
      active: isInventoried(studyState),
    },
    {
      id: 'documented',
      label: documentedLabel,
      tooltip: 'Columns inspected; AI descriptions in progress or done',
      active: documented,
    },
    {
      id: 'ready',
      label: 'Ready',
      tooltip: 'Schema indexed and queryable by the agent',
      active: isReady(studyState),
    },
    {
      id: 'approved',
      label: 'Approved',
      tooltip: 'Admin-approved for retrieval',
      active: isApproved === true,
    },
  ]
}

/**
 * Pick the pip the studying / failure indicator should anchor on. Honours an
 * explicit `last_error_phase` mapping; otherwise picks the first incomplete
 * pip in pipeline order.
 */
function findIndicatorPip(pips: readonly PipMeta[], lastErrorPhase: string | null): PipId | null {
  if (lastErrorPhase) {
    const mapped = ERROR_PHASE_TO_PIP[lastErrorPhase.toUpperCase()]
    if (mapped) return mapped
  }
  for (const p of pips) {
    if (!p.active) return p.id
  }
  // All complete — anchor on the last so a re-study of an approved source
  // still surfaces the spinner.
  return pips[pips.length - 1]?.id ?? null
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

  const tooltipText = isFailed ? (failureMessage ?? 'study failed') : pip.tooltip

  return (
    <Tooltip>
      <TooltipTrigger asChild>
        <span
          aria-label={ariaLabel}
          data-pip={pip.id}
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
          <span className={cn('capitalize', labelClass)}>{pip.label}</span>
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

export function DatabaseStudyStrip(props: DatabaseStudyStripProps) {
  const { schemaStatus, lastErrorPhase, className, sourceName } = props
  const pips = buildPips(props)

  const isStudying = schemaStatus === 'STUDYING'
  const isFailed = schemaStatus === 'FAILED'
  const indicatorPip = isStudying || isFailed ? findIndicatorPip(pips, lastErrorPhase) : null

  // Screen-reader summary; matches IngestionStrip's role="status" pattern.
  const summary = pips.map((p) => `${p.label}${p.active ? ' done' : ' pending'}`).join('; ')
  const subject = sourceName ? `Schema study progress for ${sourceName}` : 'Schema study progress'

  // Wave 3 will surface a real, admin-readable error string. Today we keep
  // the tooltip generic — connection strings or internal messages must NEVER
  // leak through the strip.
  const failureMessage: string | null = isFailed ? 'Study failed — see Verb Column' : null

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
          const isPipStudying = isStudying && indicatorPip === pip.id
          const isPipFailed = isFailed && indicatorPip === pip.id
          return (
            <span key={pip.id} className="inline-flex items-center gap-2">
              <PipDot
                pip={pip}
                isStudying={isPipStudying}
                isFailed={isPipFailed}
                failureMessage={failureMessage}
                sourceName={sourceName}
              />
              {idx < PIP_ORDER.length - 1 ? (
                <Connector filled={pip.active && pips[idx + 1].active} />
              ) : null}
            </span>
          )
        })}
      </div>
    </TooltipProvider>
  )
}
