'use client'

/**
 * IngestionStrip — compact 4-pip horizontal row that surfaces the ingestion
 * progress of a single source on /admin/sources.
 *
 * Stages:
 *   Uploaded  — bytes landed in MinIO (or, for non-file sources, the latest
 *               sync fetched something successfully)
 *   Parsed    — Documents rows extracted ( document_count > 0 )
 *   Chunked   — Vector chunks ready ( chunk_count > 0 ).  Chunks always carry
 *               an embedding (Chunk.embedding NOT NULL), so "chunked" subsumes
 *               "embedded" — there is no separate Embedded pip.
 *   Approved  — Admin flipped is_active=true, source is visible to users.
 *
 * In-flight jobs (latest_job.status === "running") show a small spinner on the
 * pip currently being worked on.  Failed jobs paint the failed stage red and
 * tooltip the error_message.
 *
 * Usage:
 *   <IngestionStrip source={s} />
 */

import { Tooltip, TooltipContent, TooltipProvider, TooltipTrigger } from '@/components/ui/tooltip'
import type { SourceListItem } from '@/lib/api/sources'
import { cn } from '@/lib/utils'
import { CircleAlert, Loader2 } from 'lucide-react'

interface IngestionStripProps {
  source: SourceListItem
  /** Optional className passthrough so callers can tweak spacing in dense layouts. */
  className?: string
}

type StageId = 'uploaded' | 'parsed' | 'chunked' | 'approved'

interface StageMeta {
  id: StageId
  label: string
  tooltip: string
  active: boolean
}

const STAGE_ORDER: readonly StageId[] = ['uploaded', 'parsed', 'chunked', 'approved'] as const

const RUNNING_STATUSES: readonly string[] = ['running', 'syncing', 'pending'] as const
const FETCH_SUCCESS_STATUSES: readonly string[] = [
  'completed',
  'success',
  'ready',
  'running',
  'syncing',
] as const

function isUploadedActive(source: SourceListItem): boolean {
  if (source.has_upload === true) return true
  const status = source.latest_job?.status
  if (!status) return false
  return (FETCH_SUCCESS_STATUSES as readonly string[]).includes(status)
}

function buildStages(source: SourceListItem): readonly StageMeta[] {
  const documentCount = source.document_count ?? 0
  const chunkCount = source.chunk_count ?? 0
  return [
    {
      id: 'uploaded',
      label: 'Uploaded',
      tooltip: 'File landed in object storage',
      active: isUploadedActive(source),
    },
    {
      id: 'parsed',
      label: documentCount > 0 ? `Parsed (${documentCount.toLocaleString()})` : 'Parsed',
      tooltip: 'Documents extracted',
      active: documentCount > 0,
    },
    {
      id: 'chunked',
      label: chunkCount > 0 ? `Chunked (${chunkCount.toLocaleString()})` : 'Chunked',
      tooltip: 'Vector chunks ready',
      active: chunkCount > 0,
    },
    {
      id: 'approved',
      label: 'Approved',
      tooltip: 'Admin-approved for retrieval',
      active: source.is_active === true,
    },
  ]
}

/**
 * Pick the stage where the in-flight (or failed) sync job lives.  We anchor
 * the spinner / red dot on the first inactive stage in pipeline order — that's
 * the next thing the worker is producing, so users see "we're stuck on X".
 */
function findInFlightStage(stages: readonly StageMeta[]): StageId | null {
  for (const s of stages) {
    if (!s.active) return s.id
  }
  // All stages already complete — anchor any indicator on the last stage so
  // it doesn't visually disappear on a re-sync of an already-approved source.
  return stages[stages.length - 1]?.id ?? null
}

interface IngestionPipProps {
  stage: StageMeta
  isRunning: boolean
  isFailed: boolean
  failureMessage: string | null
  sourceName: string
}

function IngestionPip({
  stage,
  isRunning,
  isFailed,
  failureMessage,
  sourceName,
}: IngestionPipProps) {
  const baseDot = 'h-2 w-2 rounded-full transition-colors'
  const failedDot = 'bg-red-500'
  const activeDot = 'bg-emerald-500'
  const inactiveDot = 'border border-zinc-400/50 bg-transparent dark:border-zinc-500/60'

  const dotClass = isFailed ? failedDot : stage.active ? activeDot : inactiveDot

  const labelClass = isFailed
    ? 'text-red-700 dark:text-red-300'
    : stage.active
      ? 'text-foreground'
      : 'text-muted-foreground'

  const ariaParts = [stage.label, stage.active ? 'completed' : 'pending']
  if (isRunning) ariaParts.push('in progress')
  if (isFailed) ariaParts.push('failed')
  const ariaLabel = `${sourceName}: ${ariaParts.join(', ')}`

  const tooltipText = isFailed ? (failureMessage ?? 'sync failed') : stage.tooltip

  return (
    <Tooltip>
      <TooltipTrigger asChild>
        <span
          aria-label={ariaLabel}
          data-stage={stage.id}
          data-active={stage.active ? 'true' : 'false'}
          data-failed={isFailed ? 'true' : 'false'}
          data-running={isRunning ? 'true' : 'false'}
          className={cn(
            'inline-flex items-center gap-1.5 whitespace-nowrap text-[11px] font-medium leading-none',
            'cursor-default select-none'
          )}
        >
          <span className="relative inline-flex h-2 w-2 items-center justify-center">
            <span className={cn(baseDot, dotClass)} aria-hidden />
            {isRunning ? (
              <Loader2
                className={cn(
                  'absolute -inset-1 h-4 w-4 animate-spin',
                  isFailed ? 'text-red-500' : 'text-blue-500'
                )}
                aria-hidden
              />
            ) : null}
            {isFailed && !isRunning ? (
              <CircleAlert className="absolute -inset-1 h-4 w-4 text-red-500" aria-hidden />
            ) : null}
          </span>
          <span className={cn('capitalize', labelClass)}>{stage.label}</span>
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

export function IngestionStrip({ source, className }: IngestionStripProps) {
  const stages = buildStages(source)
  const jobStatus = source.latest_job?.status ?? null
  const isRunning =
    jobStatus !== null && (RUNNING_STATUSES as readonly string[]).includes(jobStatus)
  const isFailed = jobStatus === 'failed'
  const failureMessage = source.latest_job?.error_message ?? null
  const inFlightStage = isRunning || isFailed ? findInFlightStage(stages) : null

  // Build a label list for the parent role="status" so screen-readers get a
  // single readable summary without navigating each pip.
  const summary = stages.map((s) => `${s.label}${s.active ? ' done' : ' pending'}`).join('; ')

  return (
    <TooltipProvider delayDuration={120}>
      <div
        role="status"
        aria-label={`Ingestion progress for ${source.name}: ${summary}${
          isFailed ? '; sync failed' : isRunning ? '; sync in progress' : ''
        }`}
        className={cn('inline-flex flex-wrap items-center gap-x-2 gap-y-1', className)}
      >
        {stages.map((stage, idx) => {
          const isStageRunning = isRunning && inFlightStage === stage.id
          const isStageFailed = isFailed && inFlightStage === stage.id
          return (
            <span key={stage.id} className="inline-flex items-center gap-2">
              <IngestionPip
                stage={stage}
                isRunning={isStageRunning}
                isFailed={isStageFailed}
                failureMessage={failureMessage}
                sourceName={source.name}
              />
              {idx < STAGE_ORDER.length - 1 ? (
                <Connector filled={stage.active && stages[idx + 1].active} />
              ) : null}
            </span>
          )
        })}
      </div>
    </TooltipProvider>
  )
}
