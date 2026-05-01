'use client'

import {
  AlertDialog,
  AlertDialogAction,
  AlertDialogCancel,
  AlertDialogContent,
  AlertDialogDescription,
  AlertDialogFooter,
  AlertDialogHeader,
  AlertDialogTitle,
} from '@/components/ui/alert-dialog'
import { Badge } from '@/components/ui/badge'
import { useActivateEmbedder, useActivateEmbedderPreview } from '@/hooks/use-embedders'
import { cn } from '@/lib/utils'
import type { ActivateEmbedderResponse, EmbedderPublic } from '@/types/embedder'
import { AlertTriangleIcon, Loader2Icon } from 'lucide-react'
import { useEffect, useState } from 'react'
import { toast } from 'sonner'

/**
 * Activation flow per design doc §6.5.
 *
 * On open: dry-run via `GET /activate-preview` to populate:
 *   - chunks_to_reembed
 *   - estimated_seconds
 *   - estimated_api_cost_usd
 *   - dimension_locked / untested rejection signals
 *   - cross-family hint vs. active LLM families
 *
 * Confirm → `POST /activate`. The backend kicks off a Celery re-embed job;
 * we surface the returned `job_id` and initial status so the admin can
 * track progress (full progress polling is the parent page's concern when
 * v1 wires the job-status endpoint).
 */

interface ActivateEmbedderDialogProps {
  open: boolean
  onOpenChange: (open: boolean) => void
  embedder: EmbedderPublic | null
}

function formatDuration(seconds: number): string {
  if (seconds < 60) return `~${seconds}s`
  const minutes = Math.round(seconds / 60)
  if (minutes < 60) return `~${minutes} min`
  const hours = Math.floor(minutes / 60)
  const remaining = minutes % 60
  return remaining === 0 ? `~${hours} h` : `~${hours} h ${remaining} min`
}

function formatCost(usd: number): string {
  if (usd < 0.01) return '< $0.01'
  return `$${usd.toFixed(2)}`
}

export function ActivateEmbedderDialog({
  open,
  onOpenChange,
  embedder,
}: ActivateEmbedderDialogProps) {
  const {
    data: preview,
    isLoading,
    isError,
    error,
  } = useActivateEmbedderPreview(open ? (embedder?.id ?? null) : null)
  const activateMutation = useActivateEmbedder()
  const [job, setJob] = useState<ActivateEmbedderResponse | null>(null)

  useEffect(() => {
    if (!open) setJob(null)
  }, [open])

  if (!embedder) return null

  const blockedDimension = preview?.dimension_locked ?? false
  const blockedUntested = preview?.untested ?? false
  const blocked = blockedDimension || blockedUntested

  const targetFamily = preview?.target_family ?? embedder.provider
  const llmFamilies = preview?.active_llm_families ?? []
  const crossFamily = llmFamilies.length > 0 && !llmFamilies.includes(targetFamily)

  function handleConfirm() {
    if (!embedder) return
    activateMutation.mutate(embedder.id, {
      onSuccess: (data) => {
        setJob(data)
        toast.success('Activation job started', {
          description: `Re-embed job ${data.job_id} queued`,
        })
      },
      onError: (err) => {
        const message = err instanceof Error ? err.message : 'Activation failed'
        toast.error(message)
      },
    })
  }

  const showJobView = job !== null

  return (
    <AlertDialog open={open} onOpenChange={onOpenChange}>
      <AlertDialogContent className="sm:max-w-lg">
        <AlertDialogHeader>
          <AlertDialogTitle>
            <span className="flex items-center gap-2">
              <AlertTriangleIcon className="h-5 w-5 text-amber-500" aria-hidden />
              Activate {embedder.name}?
            </span>
          </AlertDialogTitle>
          <AlertDialogDescription>
            Activating a new embedder triggers a full re-index. All chunks must be re-embedded so
            similarity search stays consistent.
          </AlertDialogDescription>
        </AlertDialogHeader>
        <div className="space-y-3 text-sm">
          {showJobView ? (
            <div className="rounded-md border border-emerald-500/40 bg-emerald-500/5 p-3 text-xs">
              <p className="font-medium text-emerald-700 dark:text-emerald-300">
                Job {job?.job_id} — {job?.status}
              </p>
              {job?.message ? <p className="mt-1 text-muted-foreground">{job.message}</p> : null}
              <p className="mt-2 text-muted-foreground">
                The previous active embedder stays in service until the re-embed completes. Monitor
                progress under <em>Embedders</em>; this dialog can be closed safely.
              </p>
            </div>
          ) : isLoading ? (
            <div className="flex items-center gap-2 text-muted-foreground">
              <Loader2Icon className="h-4 w-4 animate-spin" aria-hidden />
              Computing dry-run preview…
            </div>
          ) : isError ? (
            <p className="text-destructive">
              Failed to load preview: {error instanceof Error ? error.message : 'unknown'}
            </p>
          ) : preview ? (
            <>
              <div className="grid grid-cols-3 gap-2 rounded-md border bg-muted/30 p-3 text-xs">
                <div className="space-y-0.5">
                  <p className="text-muted-foreground">Chunks to re-embed</p>
                  <p className="font-mono text-base">
                    {preview.chunks_to_reembed.toLocaleString()}
                  </p>
                </div>
                <div className="space-y-0.5">
                  <p className="text-muted-foreground">Est. duration</p>
                  <p className="font-mono text-base">{formatDuration(preview.estimated_seconds)}</p>
                </div>
                <div className="space-y-0.5">
                  <p className="text-muted-foreground">Est. cost</p>
                  <p className="font-mono text-base">
                    {formatCost(preview.estimated_api_cost_usd)}
                  </p>
                </div>
              </div>

              {blockedDimension ? (
                <div
                  role="alert"
                  className="rounded-md border border-destructive/40 bg-destructive/10 p-3 text-xs text-destructive"
                >
                  <strong>DIMENSION_LOCKED_V1.</strong> This embedder declares {embedder.dimensions}{' '}
                  dimensions, but v1 requires exactly 1536. Pick or register a 1536-dim embedder to
                  activate.
                </div>
              ) : null}

              {blockedUntested ? (
                <div
                  role="alert"
                  className="rounded-md border border-destructive/40 bg-destructive/10 p-3 text-xs text-destructive"
                >
                  <strong>UNTESTED_EMBEDDER.</strong> Run a successful test connection within the
                  last 24h before activating.
                </div>
              ) : null}

              {crossFamily ? (
                <div
                  className={cn(
                    'rounded-md border border-amber-500/40 bg-amber-500/10 p-3 text-xs',
                    'text-amber-900 dark:text-amber-200'
                  )}
                >
                  Active answer-generator LLM family
                  {llmFamilies.length > 1 ? 'ies' : ''}:{' '}
                  {llmFamilies.map((family) => (
                    <Badge
                      key={family}
                      variant="secondary"
                      className="ml-1 text-[10px] uppercase tracking-wide"
                    >
                      {family}
                    </Badge>
                  ))}
                  . Common pairings prefer matching families for billing/key consistency, but the
                  system enforces no correctness rule here.
                </div>
              ) : null}
            </>
          ) : null}
        </div>
        <AlertDialogFooter>
          <AlertDialogCancel>{showJobView ? 'Close' : 'Cancel'}</AlertDialogCancel>
          {!showJobView ? (
            <AlertDialogAction
              onClick={(event) => {
                event.preventDefault()
                handleConfirm()
              }}
              disabled={blocked || isLoading || activateMutation.isPending}
              className="bg-amber-600 text-white hover:bg-amber-700"
            >
              {activateMutation.isPending ? 'Starting…' : 'Activate & re-index'}
            </AlertDialogAction>
          ) : null}
        </AlertDialogFooter>
      </AlertDialogContent>
    </AlertDialog>
  )
}
