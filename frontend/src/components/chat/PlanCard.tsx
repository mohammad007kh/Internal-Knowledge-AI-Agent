import type { PlanActivityEntry, StepState } from '@/lib/sse/agent-events'
import { RotateCw } from 'lucide-react'
import { type StepDisplayState, StepStatusBadge } from './StepStatusBadge'

/**
 * FR-008 visibility rule: a plan card is shown ONLY when it carries signal —
 * a multi-step plan OR a revised plan. A trivial 1-step plan surfaces via the
 * status line alone (no card).
 *
 * NOTE (004 review): a `hadClarification` term was specced to also force the card
 * for a 1-step plan reached via a clarification, but it required cross-turn state
 * the chat doesn't carry and was never wired (always false). Removed as dead per
 * the supervisor; re-add with a real cross-turn clarification signal if FR-008's
 * clarification path is implemented. See specs/004 traceability.
 */
export function shouldRenderPlanCard(plan: PlanActivityEntry): boolean {
  return plan.steps.length >= 2 || plan.revision >= 1
}

interface PlanCardProps {
  activePlan: PlanActivityEntry | null
  supersededPlan: PlanActivityEntry | null
  replanReason: string | null
  /** Latest state per step id (from `selectStepStates`); missing → pending. */
  stepStates: Record<string, StepState>
}

/**
 * The conditional plan card (T-073b): a `bg-muted/40` numbered list with per-step
 * status ticks (✓ done / ↻ retrying / ○ pending / ✗ failed). On a replan it shows
 * a one-line `↻ Plan updated — {reason}` note and collapses the superseded plan
 * behind a disclosure — NO strikethrough diff.
 */
export function PlanCard({ activePlan, supersededPlan, replanReason, stepStates }: PlanCardProps) {
  if (!activePlan || !shouldRenderPlanCard(activePlan)) return null

  const tickState = (id: string): StepDisplayState => stepStates[id] ?? 'pending'

  return (
    <div className="rounded-lg border border-border bg-muted/40 p-3">
      {replanReason && (
        <p className="mb-2 flex items-center gap-1.5 text-xs text-amber-600 dark:text-amber-400">
          <RotateCw className="h-3.5 w-3.5 shrink-0" aria-hidden />
          Plan updated — {replanReason}
        </p>
      )}

      <ol className="space-y-1.5">
        {activePlan.steps.map((step, i) => (
          <li key={step.id} className="flex items-start gap-2 text-xs">
            <span className="mt-px tabular-nums text-muted-foreground" aria-hidden>
              {i + 1}.
            </span>
            <StepStatusBadge state={tickState(step.id)} />
            <span className="min-w-0 text-foreground">{step.label}</span>
          </li>
        ))}
      </ol>

      {supersededPlan && (
        <details className="mt-2">
          <summary className="cursor-pointer list-none rounded text-xs text-muted-foreground hover:text-foreground focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring">
            ▸ Original plan (superseded)
          </summary>
          <ol className="mt-1.5 space-y-1 pl-1 text-xs text-muted-foreground">
            {supersededPlan.steps.map((step, i) => (
              <li key={step.id} className="flex items-start gap-2">
                <span className="tabular-nums" aria-hidden>
                  {i + 1}.
                </span>
                <span className="min-w-0">{step.label}</span>
              </li>
            ))}
          </ol>
        </details>
      )}
    </div>
  )
}
