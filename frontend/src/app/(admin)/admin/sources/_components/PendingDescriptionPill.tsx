'use client'

import { SparklesIcon } from 'lucide-react'

import { Tooltip, TooltipContent, TooltipProvider, TooltipTrigger } from '@/components/ui/tooltip'
import { cn } from '@/lib/utils'

const PENDING_DESCRIPTION_TOOLTIP =
  'The assistant is reading this source and will write a description shortly.'

export interface PendingDescriptionPillProps {
  /** Optional className applied to the outer pill — lets parents tweak max-width per layout. */
  className?: string
}

/**
 * Sibling of `PendingNamePill` for the description slot. Renders a muted
 * shimmer pill while `description_status === 'pending_ai'` and no description
 * is available yet. The clamp on the surrounding description container does
 * not apply to this pill — the pill is small and self-bounded.
 *
 * Tooltip explains the in-flight AI work without forcing the admin to learn
 * the `description_status` jargon.
 */
export function PendingDescriptionPill({ className }: PendingDescriptionPillProps) {
  return (
    <TooltipProvider>
      <Tooltip>
        <TooltipTrigger asChild>
          <span
            data-testid="pending-description-pill"
            aria-label="Drafting description in progress"
            className={cn(
              'inline-flex items-center gap-1.5 rounded-md bg-muted px-2 py-0.5 text-xs font-medium text-muted-foreground',
              'animate-pulse',
              className
            )}
          >
            <SparklesIcon className="h-3 w-3" aria-hidden />
            Drafting description…
          </span>
        </TooltipTrigger>
        <TooltipContent side="top" className="max-w-xs">
          {PENDING_DESCRIPTION_TOOLTIP}
        </TooltipContent>
      </Tooltip>
    </TooltipProvider>
  )
}

export const PENDING_DESCRIPTION_TOOLTIP_TEXT = PENDING_DESCRIPTION_TOOLTIP
