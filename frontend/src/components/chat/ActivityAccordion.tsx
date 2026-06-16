'use client'

import {
  type ActivityState,
  type StepActivityEntry,
  type StepRun,
  selectHasTrouble,
  selectStepRuns,
  selectStepStates,
} from '@/lib/sse/agent-events'
import { cn } from '@/lib/utils'
import { ChevronRight, CornerDownRight } from 'lucide-react'
import { useId, useMemo, useState } from 'react'
import { PlanCard, shouldRenderPlanCard } from './PlanCard'
import { StepStatusBadge } from './StepStatusBadge'
import { ROLE_ICON, ROLE_LABEL } from './agent-roles'

interface ActivityAccordionProps {
  activity: ActivityState
  /** Open a step's payload in the slide-over. */
  onStepSelect: (step: StepActivityEntry) => void
}

/**
 * Layer-2 activity accordion (T-073b): a collapsed-by-default INLINE disclosure
 * attached to the finished assistant turn. Native controlled disclosure (a real
 * `<button aria-expanded aria-controls>` + a `hidden` region) — no Radix, no new
 * deps. Expands to a conditional PlanCard + one block per role that participated,
 * with hand-off connectors. An amber dot bubbles to the collapsed header on
 * trouble (retry/fail); colour is paired with an sr-only equivalent.
 */
export function ActivityAccordion({ activity, onStepSelect }: ActivityAccordionProps) {
  const [open, setOpen] = useState(false)
  const panelId = useId()
  const btnId = useId()

  // Memoised on the (immutable) entries identity — these run on every render
  // during live streaming, so avoid recomputing the folds each token.
  const { entries } = activity
  const runs = useMemo(() => selectStepRuns(activity), [activity])
  const stepStates = useMemo(() => selectStepStates(activity), [activity])
  const hasTrouble = useMemo(() => selectHasTrouble(activity), [activity])

  // `stepCount` reflects the PLAN's shape (planned steps), not how many have
  // executed — so the header reads "the agent's plan has N steps".
  const stepCount =
    activity.activePlan?.steps.length ?? runs.reduce((n, r) => n + r.steps.length, 0)

  // Nothing happened (no plan, no steps) → render nothing at all.
  if (entries.length === 0) return null

  const showPlan = activity.activePlan ? shouldRenderPlanCard(activity.activePlan) : false

  return (
    <div className="mt-2">
      <button
        id={btnId}
        type="button"
        aria-expanded={open}
        aria-controls={panelId}
        onClick={() => setOpen((o) => !o)}
        className={cn(
          'group flex min-h-[44px] w-full items-center gap-1.5 rounded-md px-1.5 py-2 text-xs text-muted-foreground',
          'transition-colors duration-150 hover:text-foreground motion-reduce:transition-none',
          'focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring focus-visible:ring-offset-2 focus-visible:ring-offset-background'
        )}
      >
        <ChevronRight
          className={cn(
            'h-3.5 w-3.5 shrink-0 transition-transform duration-150 motion-reduce:transition-none',
            open && 'rotate-90'
          )}
          aria-hidden
        />
        <span>
          Agent activity · {stepCount} {stepCount === 1 ? 'step' : 'steps'}
        </span>
        {hasTrouble && (
          <>
            <span
              className="ml-1 h-1.5 w-1.5 shrink-0 rounded-full bg-amber-500 dark:bg-amber-400"
              aria-hidden
            />
            <span className="sr-only">(includes retried or failed steps)</span>
          </>
        )}
      </button>

      <div
        id={panelId}
        role="region"
        aria-labelledby={btnId}
        hidden={!open}
        className="mt-1.5 space-y-2 border-l border-border pl-3"
      >
        {open && (
          <>
            {showPlan && (
              <PlanCard
                activePlan={activity.activePlan}
                supersededPlan={activity.supersededPlan}
                replanReason={activity.replanReason}
                stepStates={stepStates}
              />
            )}
            {runs.map((run, i) => (
              <div key={`${run.role}-${run.steps[0].stepId}`}>
                {i > 0 && <Handoff from={runs[i - 1].role} to={run.role} />}
                <RoleSection run={run} onStepSelect={onStepSelect} />
              </div>
            ))}
          </>
        )}
      </div>
    </div>
  )
}

function Handoff({ from, to }: { from: StepRun['role']; to: StepRun['role'] }) {
  return (
    <div className="flex items-center gap-1 py-0.5 pl-0.5 text-xs text-muted-foreground">
      <CornerDownRight className="h-3 w-3 shrink-0" aria-hidden />
      <span>
        {ROLE_LABEL[from]} → {ROLE_LABEL[to]}
      </span>
    </div>
  )
}

interface RoleSectionProps {
  run: StepRun
  onStepSelect: (step: StepActivityEntry) => void
}

function RoleSection({ run, onStepSelect }: RoleSectionProps) {
  const RoleGlyph = ROLE_ICON[run.role]
  return (
    <section aria-label={`${ROLE_LABEL[run.role]} activity`} className="agent-block-in">
      <h4 className="flex items-center gap-1.5 text-xs font-medium text-foreground">
        <RoleGlyph className="h-4 w-4 shrink-0 text-muted-foreground" aria-hidden />
        {ROLE_LABEL[run.role]}
      </h4>
      <div className="mt-0.5 space-y-0.5">
        {run.steps.map((step) => (
          <button
            key={step.stepId}
            type="button"
            onClick={() => onStepSelect(step)}
            aria-label={`Open source for: ${step.label}`}
            className={cn(
              'flex min-h-[44px] w-full items-center gap-1.5 rounded px-1.5 py-2 text-left text-xs text-muted-foreground',
              'transition-colors duration-150 hover:bg-muted/60 hover:text-foreground motion-reduce:transition-none',
              'focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring'
            )}
          >
            <StepStatusBadge state={step.state} />
            <span className="min-w-0 truncate">{step.summary ?? step.label}</span>
          </button>
        ))}
      </div>
    </section>
  )
}
