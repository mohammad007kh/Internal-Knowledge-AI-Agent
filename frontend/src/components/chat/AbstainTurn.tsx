'use client'

import type { BudgetActivityEntry } from '@/lib/sse/agent-events'
import { cn } from '@/lib/utils'
import { InfoIcon } from 'lucide-react'
import { BudgetFooter } from './BudgetFooter'
import { ContinueSearchAffordance } from './ContinueSearchAffordance'

interface AbstainTurnProps {
  /** The calm abstain message (e.g. "I couldn't find enough grounded info…"). */
  message: string
  budget?: BudgetActivityEntry | null
  costNote?: string | null
  /** Called when the user opts to keep searching (only offered if offerContinue). */
  onContinue?: () => void
  /** Called when the user opts to stop here. */
  onStop?: () => void
}

const DEFAULT_ABSTAIN = "I couldn't find enough grounded information to answer this confidently."

/**
 * Honest-failure (abstain) assistant turn (T-075). Visually aligned with the
 * existing fallback styling (`bg-muted/40` + italic muted + InfoIcon) so abstain
 * reads as a deliberate, first-class state — not a bug. When the budget offers
 * to continue, a calm OptionButtonGroup gives Keep searching / Stop here. No red.
 */
export function AbstainTurn({ message, budget, costNote, onContinue, onStop }: AbstainTurnProps) {
  const offerContinue = budget?.offerContinue ?? false

  return (
    <div className="max-w-[75%] rounded-2xl rounded-tl-sm bg-muted/40 px-4 py-2.5">
      <div className={cn('break-words text-sm italic text-muted-foreground')}>
        <InfoIcon className="mr-1.5 inline-block h-3.5 w-3.5 align-[-2px]" aria-hidden="true" />
        {message || DEFAULT_ABSTAIN}
      </div>

      <BudgetFooter budget={budget ?? null} costNote={costNote} />

      {/* Shared continue/stop affordance (single source of truth, T-075). */}
      {offerContinue && (
        <ContinueSearchAffordance
          className="mt-2.5"
          onSearchAgain={() => onContinue?.()}
          onLeave={() => onStop?.()}
        />
      )}
    </div>
  )
}
