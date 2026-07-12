import type { ActivityState, StepActivityEntry } from '@/lib/sse/agent-events'
import { selectLatestBudget } from '@/lib/sse/agent-events'
import { ActivityAccordion } from './ActivityAccordion'
import { BudgetFooter } from './BudgetFooter'
import { ContinueSearchAffordance } from './ContinueSearchAffordance'

interface AgenticTurnFooterProps {
  /** The finished turn's activity snapshot. Renders nothing if empty. */
  activity: ActivityState
  /** True if this is the most recent assistant turn (gates the continue affordance). */
  isLastAssistant: boolean
  /** True while a new turn is streaming (hides the affordance — no double-send). */
  isStreaming: boolean
  /** True if the user already chose "Leave it here" on this turn. */
  continueDismissed: boolean
  /** Open a step's payload in the slide-over. */
  onInspectStep: (step: StepActivityEntry) => void
  /** Start a fresh follow-up turn ("Search again"). */
  onSearchAgain: () => void
  /** Locally dismiss the budget-continue affordance for this turn. */
  onLeaveBudget: () => void
}

/**
 * The shared finished-turn footer for an agentic assistant turn (004 review:
 * Fix C). Single source of truth for the Layer-2 accordion + budget footnote +
 * the live-edge continue affordance, reused by the main chat (`MessageBubble`)
 * and the admin sandbox (`SandboxBubble`). Stateless — the per-surface dismiss
 * Set + last-assistant computation stay in each parent (their lifecycles differ).
 */
export function AgenticTurnFooter({
  activity,
  isLastAssistant,
  isStreaming,
  continueDismissed,
  onInspectStep,
  onSearchAgain,
  onLeaveBudget,
}: AgenticTurnFooterProps) {
  if (activity.entries.length === 0) return null

  const turnBudget = selectLatestBudget(activity)
  // Offer "Search again" only on the live edge: most recent assistant turn,
  // ceiling offered to continue, not dismissed, nothing streaming.
  const showContinue =
    isLastAssistant && !isStreaming && !continueDismissed && (turnBudget?.offerContinue ?? false)

  return (
    <>
      <ActivityAccordion activity={activity} onStepSelect={onInspectStep} />
      {/* Quiet cost / over-ceiling footnote — renders only when the ceiling was hit. */}
      <BudgetFooter budget={turnBudget} />
      {/* Honest "take another pass?" affordance — live edge only. */}
      {showContinue && (
        <ContinueSearchAffordance
          className="mt-2.5"
          onSearchAgain={onSearchAgain}
          onLeave={onLeaveBudget}
        />
      )}
    </>
  )
}
