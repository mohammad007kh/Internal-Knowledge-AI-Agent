'use client'

/**
 * AvailabilityToggle — the "Available to users" switch (U14).
 *
 * Mounted on both the Overview tab and the Settings tab. Wraps the existing
 * `useUpdateSource` mutation and combines two gates:
 *
 *   1. Lifecycle phase — `canMakeAvailableToUsers` from `useLifecycle`. Off
 *      while the source is ingesting / naming / analyzing.
 *   2. Approval blockers — naming/description must be present (PRD §11).
 *
 * Disabled state always carries a human-readable explanation in the
 * accompanying callout. The component handles all of this so callers don't
 * duplicate the gate logic.
 */

import { Switch } from '@/components/ui/switch'
import {
  Tooltip,
  TooltipContent,
  TooltipProvider,
  TooltipTrigger,
} from '@/components/ui/tooltip'
import { useUpdateSource } from '@/features/sources/hooks/useSources'
import { useLifecycle } from '@/features/sources/lifecycle'
import type { SourceDetail } from '@/lib/api/sources'
import { getErrorMessage } from '@/lib/errors'
import { cn } from '@/lib/utils'
import { toast } from 'sonner'

interface AvailabilityToggleProps {
  source: SourceDetail
  /** Compact mode hides the helper paragraph; used on Overview where the
   *  context is already established. */
  compact?: boolean
  className?: string
  /** Override for tests; defaults to `availability-toggle-${source.id}`. */
  testIdPrefix?: string
}

export function AvailabilityToggle({
  source,
  compact = false,
  className,
  testIdPrefix = 'availability-toggle',
}: AvailabilityToggleProps) {
  const updateMutation = useUpdateSource(source.id)
  const { canMakeAvailableToUsers, availabilityReason, approvalBlockers, phase } =
    useLifecycle(source)

  // The switch is gated by:
  //   - Phase gate (canMakeAvailableToUsers). Always blocks turn-ON when
  //     ingestion isn't done.
  //   - Approval blockers (naming/description). Block turn-ON only.
  //   - In-flight mutation. Blocks any toggle.
  // Turning OFF an already-on switch is always allowed; an admin needs to
  // be able to unpublish a misbehaving source even mid-ingestion.
  const isOn = source.is_active
  const blockTurnOn =
    !canMakeAvailableToUsers || approvalBlockers.length > 0
  const disabled =
    updateMutation.isPending || (!isOn && blockTurnOn)

  const reasons: string[] = []
  if (!canMakeAvailableToUsers && availabilityReason) reasons.push(availabilityReason)
  reasons.push(...approvalBlockers)

  const tooltipBody = reasons[0] ?? null

  function handleCheckedChange(checked: boolean) {
    updateMutation.mutate(
      { is_active: checked },
      {
        onSuccess: () =>
          toast.success(
            checked
              ? 'Source approved — now available to users'
              : 'Source hidden from users'
          ),
        onError: (err) => toast.error(getErrorMessage(err)),
      }
    )
  }

  const helperId = `${testIdPrefix}-helper-${source.id}`

  return (
    <div className={cn('space-y-2', className)} data-testid={testIdPrefix}>
      <div className="flex items-center justify-between gap-3">
        <div className="min-w-0 flex-1 space-y-0.5">
          <p className="text-sm font-medium">Available to users</p>
          {!compact ? (
            <p className="text-xs text-muted-foreground">
              When off, the source is hidden from the chat session source picker.
              New sources start off until approved by an admin.
            </p>
          ) : null}
        </div>
        <TooltipProvider delayDuration={150}>
          <Tooltip>
            <TooltipTrigger asChild>
              <span>
                <Switch
                  checked={isOn}
                  disabled={disabled}
                  onCheckedChange={handleCheckedChange}
                  aria-label="Toggle source availability to users"
                  aria-describedby={reasons.length > 0 ? helperId : undefined}
                  data-testid={`${testIdPrefix}-switch`}
                  data-phase={phase}
                />
              </span>
            </TooltipTrigger>
            {tooltipBody ? (
              <TooltipContent side="left" className="max-w-[280px] text-xs">
                {tooltipBody}
              </TooltipContent>
            ) : null}
          </Tooltip>
        </TooltipProvider>
      </div>
      {!isOn && reasons.length > 0 ? (
        <div
          id={helperId}
          role="status"
          className="rounded-md border border-amber-500/40 bg-amber-500/5 p-3 text-xs text-amber-900 dark:text-amber-200"
          data-testid={`${testIdPrefix}-blockers`}
        >
          <p className="font-medium">Cannot approve yet:</p>
          <ul className="mt-1 list-disc space-y-1 pl-5">
            {reasons.map((r) => (
              <li key={r}>{r}</li>
            ))}
          </ul>
        </div>
      ) : null}
    </div>
  )
}
