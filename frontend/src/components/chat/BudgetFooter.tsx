import type { BudgetActivityEntry } from '@/lib/sse/agent-events'

interface BudgetFooterProps {
  budget: BudgetActivityEntry | null
}

/**
 * A tertiary footnote under the answer (T-074): only when the research ceiling
 * was actually hit, a calm "reached the research limit" qualifier (amber scoped
 * to the phrase, never a red banner). Renders nothing when within budget.
 *
 * NOTE (004 review): a `costNote` prop (intended for activity_summary.cost_label)
 * was removed as dead — it had no live caller. Re-add when the cost label is
 * actually surfaced.
 */
export function BudgetFooter({ budget }: BudgetFooterProps) {
  if (!budget?.ceilingHit) return null

  const remaining = budget.notCompleted?.length ?? 0

  return (
    <p className="mt-1.5 text-xs text-muted-foreground">
      <span className="text-amber-600 dark:text-amber-400">reached the research limit</span>
      {remaining > 0 ? ` before checking ${remaining} more.` : '.'}
    </p>
  )
}
