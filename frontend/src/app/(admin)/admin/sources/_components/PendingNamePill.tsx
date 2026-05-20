'use client'

import { SparklesIcon } from 'lucide-react'

import { Tooltip, TooltipContent, TooltipProvider, TooltipTrigger } from '@/components/ui/tooltip'
import { cn } from '@/lib/utils'

const PENDING_NAME_TOOLTIP =
  'The assistant is reading this source and will write a name + description shortly.'

export interface PendingNamePillProps {
  /** Optional className applied to the outer pill — lets parents tweak max-width per layout. */
  className?: string
}

/**
 * Muted shimmer pill rendered in the source-name slot while the AI-naming
 * pipeline is still working. Reuses the same `animate-pulse` rhythm as the
 * table skeleton so the row's resting state and its naming state share the
 * same visual cadence.
 *
 * Tooltip explains what's happening without forcing the admin to learn the
 * `name_status` jargon.
 */
export function PendingNamePill({ className }: PendingNamePillProps) {
  return (
    <TooltipProvider>
      <Tooltip>
        <TooltipTrigger asChild>
          <span
            data-testid="pending-name-pill"
            aria-label="Naming in progress"
            className={cn(
              'inline-flex items-center gap-1.5 rounded-md bg-muted px-2 py-0.5 text-xs font-medium text-muted-foreground',
              'animate-pulse',
              className
            )}
          >
            <SparklesIcon className="h-3 w-3" aria-hidden />
            Naming…
          </span>
        </TooltipTrigger>
        <TooltipContent side="top" className="max-w-xs">
          {PENDING_NAME_TOOLTIP}
        </TooltipContent>
      </Tooltip>
    </TooltipProvider>
  )
}

export const PENDING_NAME_TOOLTIP_TEXT = PENDING_NAME_TOOLTIP
