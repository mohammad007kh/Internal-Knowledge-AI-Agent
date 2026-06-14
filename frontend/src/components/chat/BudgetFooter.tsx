import type { BudgetActivityEntry } from '@/lib/sse/agent-events'

interface BudgetFooterProps {
  budget: BudgetActivityEntry | null
  /** Optional quiet cost note (e.g. activity_summary.cost_label). */
  costNote?: string | null
}

/**
 * A tertiary footnote under the answer (T-074): an optional quiet cost note,
 * plus — only when the research ceiling was actually hit — a calm "reached the
 * research limit" qualifier (amber scoped to the phrase, never a red banner).
 * Renders nothing when within budget and no cost note is supplied.
 */
export function BudgetFooter({ budget, costNote }: BudgetFooterProps) {
  const ceilingHit = budget?.ceilingHit ?? false
  if (!ceilingHit && !costNote) return null

  const remaining = budget?.notCompleted?.length ?? 0

  return (
    <p className="mt-1.5 text-xs text-muted-foreground">
      {costNote && <span>{costNote}</span>}
      {ceilingHit && (
        <>
          {costNote ? '; ' : ''}
          <span className="text-amber-600 dark:text-amber-400">reached the research limit</span>
          {remaining > 0 ? ` before checking ${remaining} more.` : '.'}
        </>
      )}
    </p>
  )
}
