'use client'

import { Button } from '@/components/ui/button'
import { Popover, PopoverContent, PopoverTrigger } from '@/components/ui/popover'
import { useTriggerSync, useUpdateSource } from '@/features/sources/hooks/useSources'
import type { SourceListItem } from '@/lib/api/sources'
import { getErrorMessage } from '@/lib/errors'
import { cn } from '@/lib/utils'
import { CheckCircle2, Loader2 } from 'lucide-react'
import { useState } from 'react'
import { toast } from 'sonner'
import { type Phase, derivePhase } from './sourcePhase'

interface ActionCellProps {
  source: SourceListItem
  /**
   * On mobile (`SourceRowCard`) the action is rendered as a full-width primary
   * action at the bottom of the card. On desktop (`SourcesTable`) it stays
   * compact in the "Next step" column.
   */
  layout?: 'inline' | 'block'
}

/**
 * Renders exactly one verb per row based on the derived phase. Wired to:
 *   - `useUpdateSource` for the **Approve & ingest** action (PATCH `is_active`)
 *   - `useTriggerSync` for **Run now** / **Retry** / **Re-run**
 *
 * The sync-now endpoint (`POST /api/v1/sources/{id}/sync`) ships in
 * `triggerSyncApi` already, so no stub is needed.
 */
export function ActionCell({ source, layout = 'inline' }: ActionCellProps) {
  const phase = derivePhase(source)
  const updateMutation = useUpdateSource(source.id)
  const syncMutation = useTriggerSync()
  const [errorPopoverOpen, setErrorPopoverOpen] = useState(false)

  const block = layout === 'block'
  const buttonHeight = block ? 'h-9' : 'h-7'
  const buttonWidth = block ? 'w-full' : ''

  function handleApprove() {
    updateMutation.mutate(
      { is_active: true },
      {
        onSuccess: () => toast.success(`${source.name} approved — ingestion will start shortly.`),
        onError: (err) => toast.error(getErrorMessage(err) || 'Approval failed'),
      }
    )
  }

  function handleSync() {
    syncMutation.mutate(source.id, {
      onSuccess: () => {
        toast.success('Sync started')
        setErrorPopoverOpen(false)
      },
      onError: (err) => toast.error(getErrorMessage(err) || 'Sync failed'),
    })
  }

  if (phase === 'awaiting_approval') {
    return (
      <div className={cn('flex flex-col gap-1', block && 'w-full')}>
        <Button
          type="button"
          size="sm"
          aria-label={`Approve and ingest ${source.name}`}
          disabled={updateMutation.isPending}
          onClick={handleApprove}
          className={cn(buttonHeight, buttonWidth, 'gap-1.5 text-xs font-medium')}
        >
          {updateMutation.isPending ? (
            <Loader2 className="h-3.5 w-3.5 animate-spin" aria-hidden />
          ) : null}
          Approve &amp; ingest
        </Button>
        <p className="text-[11px] text-muted-foreground">Sits idle until you approve</p>
      </div>
    )
  }

  if (phase === 'queued') {
    return (
      <div className={cn('flex flex-col gap-1', block && 'w-full')}>
        <Button
          type="button"
          variant="ghost"
          size="sm"
          aria-label={`Run sync now for ${source.name}`}
          disabled={syncMutation.isPending}
          onClick={handleSync}
          className={cn(buttonHeight, buttonWidth, 'gap-1.5 text-xs')}
        >
          {syncMutation.isPending ? (
            <Loader2 className="h-3.5 w-3.5 animate-spin" aria-hidden />
          ) : null}
          Run now
        </Button>
        <p className="text-[11px] text-muted-foreground">Will run on next 30-min cycle.</p>
      </div>
    )
  }

  if (phase === 'running') {
    return (
      <div
        className={cn(
          'inline-flex items-center gap-2 text-xs italic text-blue-700 dark:text-blue-300',
          block && 'w-full justify-center py-2'
        )}
        role="status"
        aria-label={`${source.name} is currently ingesting`}
      >
        <Loader2 className="h-3.5 w-3.5 animate-spin" aria-hidden />
        <span>Working on it&hellip;</span>
      </div>
    )
  }

  if (phase === 'ready') {
    return (
      <div
        className={cn(
          'inline-flex items-center gap-1.5 text-xs font-medium text-emerald-700 dark:text-emerald-300',
          block && 'w-full justify-center py-2'
        )}
        aria-label={`${source.name} is ready for chat`}
      >
        <CheckCircle2 className="h-3.5 w-3.5" aria-hidden />
        <span>Ready for chat</span>
      </div>
    )
  }

  if (phase === 'failed') {
    const errorMessage = source.latest_job?.error_message ?? 'No error details available.'
    return (
      <Popover open={errorPopoverOpen} onOpenChange={setErrorPopoverOpen}>
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
            <p className="whitespace-pre-wrap break-words text-muted-foreground">{errorMessage}</p>
          </div>
          <Button
            type="button"
            size="sm"
            aria-label={`Retry sync for ${source.name}`}
            disabled={syncMutation.isPending}
            onClick={handleSync}
            className="h-7 w-full gap-1.5 text-xs"
          >
            {syncMutation.isPending ? (
              <Loader2 className="h-3.5 w-3.5 animate-spin" aria-hidden />
            ) : null}
            Retry
          </Button>
        </PopoverContent>
      </Popover>
    )
  }

  if (phase === 'empty') {
    return (
      <div className={cn('flex flex-col gap-1', block && 'w-full')}>
        <Button
          type="button"
          variant="outline"
          size="sm"
          aria-label={`Re-run sync for ${source.name}`}
          disabled={syncMutation.isPending}
          onClick={handleSync}
          className={cn(
            buttonHeight,
            buttonWidth,
            'gap-1.5 border-amber-500/40 text-xs font-medium text-amber-700 hover:bg-amber-500/10 dark:text-amber-300'
          )}
        >
          {syncMutation.isPending ? (
            <Loader2 className="h-3.5 w-3.5 animate-spin" aria-hidden />
          ) : null}
          Re-run
        </Button>
        <p className="text-[11px] text-muted-foreground">
          Last sync produced 0 chunks &mdash; file may be empty
        </p>
      </div>
    )
  }

  // `unknown` phase — fall back to a neutral em-dash so the column stays the
  // same width but does not pretend to know what to do next.
  const _exhaustive: Phase = phase
  void _exhaustive
  return (
    <span className="text-xs text-muted-foreground" aria-label="No action available">
      &mdash;
    </span>
  )
}
