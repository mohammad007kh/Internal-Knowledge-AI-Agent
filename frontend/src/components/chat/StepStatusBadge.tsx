import type { StepState } from '@/lib/sse/agent-events'
import { cn } from '@/lib/utils'
import { Check, Circle, CircleDot, RotateCw, X } from 'lucide-react'
import type { IconGlyph } from './types'

/**
 * Display state for a single plan step's status glyph.
 *
 * Extends the wire `StepState` with a synthetic `'pending'` used by the
 * PlanCard for steps the agent has not reached yet (no `step` event observed).
 */
export type StepDisplayState = StepState | 'pending'

interface BadgeDef {
  Icon: IconGlyph
  /** Tailwind colour — dual-theme pairs so it stays legible in light AND dark. */
  color: string
  /** Accessible label — color is NEVER the sole signal (a11y constraint). */
  label: string
}

// State → glyph + colour + sr-only label.
//   ✓ finished → emerald   ↻ retrying → amber   ○ pending → muted
//   ◉ started → muted (active)   ✗ failed → amber (deep)   — NEVER red.
const BADGES: Record<StepDisplayState, BadgeDef> = {
  pending: { Icon: Circle, color: 'text-muted-foreground', label: 'pending' },
  started: { Icon: CircleDot, color: 'text-muted-foreground', label: 'in progress' },
  finished: { Icon: Check, color: 'text-emerald-600 dark:text-emerald-400', label: 'done' },
  retrying: { Icon: RotateCw, color: 'text-amber-600 dark:text-amber-400', label: 'retrying' },
  failed: { Icon: X, color: 'text-amber-700 dark:text-amber-400', label: 'failed' },
}

interface StepStatusBadgeProps {
  state: StepDisplayState
  /** Extra classes merged onto the glyph (e.g. size override). */
  className?: string
}

/**
 * The shared per-step status glyph (T-073a leaf primitive). Reused by the
 * Layer-1 StatusLine, the PlanCard tick list, and the activity accordion rows
 * so the role/state visual language is defined in exactly ONE place.
 *
 * Color encodes STATE only (amber = trouble-but-recovering; never red). Role
 * identity is carried elsewhere by a separate lucide icon, never by this badge.
 */
export function StepStatusBadge({ state, className }: StepStatusBadgeProps) {
  const { Icon, color, label } = BADGES[state]
  return (
    <span className="inline-flex shrink-0 items-center">
      <Icon className={cn('h-3.5 w-3.5', color, className)} aria-hidden />
      <span className="sr-only">{label}</span>
    </span>
  )
}
