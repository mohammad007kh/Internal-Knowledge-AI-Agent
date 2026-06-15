'use client'

import { useState } from 'react'
import { OptionButtonGroup } from './OptionButtonGroup'

/**
 * The follow-up message sent when the user chooses to take another pass after a
 * budget-ceiling stop. STATIC and deterministic — never interpolated from prior
 * assistant output (avoids feedback loops + keeps tests stable). The backend
 * carries conversation history, so "my previous question" resolves through
 * context; no need to re-send the original query text.
 *
 * NOTE (honest semantics): there is NO server-side resume — this starts a fresh
 * pipeline turn. That is why the user-facing label is "Search again", not
 * "Keep searching"/"Continue" (which would falsely imply resumption).
 */
export const KEEP_SEARCHING_PROMPT =
  'Please take another pass at my previous question — go deeper and try other sources or angles.'

interface ContinueSearchAffordanceProps {
  /** Start a fresh follow-up turn (caller sends KEEP_SEARCHING_PROMPT). */
  onSearchAgain: () => void
  /** Dismiss locally — no network call. */
  onLeave: () => void
  className?: string
}

/**
 * Calm "take another pass?" affordance shown after the agent stops at its budget
 * ceiling (T-075). The single source of truth for the continue/stop choice,
 * mounted under a finished turn on both surfaces (main chat + admin sandbox).
 * Locks after the first choice so a double-click can't double-fire.
 */
export function ContinueSearchAffordance({
  onSearchAgain,
  onLeave,
  className,
}: ContinueSearchAffordanceProps) {
  const [chosen, setChosen] = useState(false)
  return (
    <OptionButtonGroup
      className={className}
      label="I stopped here to stay within budget. Want me to take another pass?"
      disabled={chosen}
      options={[
        { id: 'again', label: 'Search again', value: 'again', recommended: true },
        { id: 'leave', label: 'Leave it here', value: 'leave' },
      ]}
      onSelect={(value) => {
        if (chosen) return
        setChosen(true)
        if (value === 'again') onSearchAgain()
        else onLeave()
      }}
    />
  )
}
