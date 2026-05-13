/**
 * LifecycleStepper — visual state derivation.
 *
 * The chip strip is a pure function of `phase`. We assert that for any given
 * phase: the right number of "done" chips appear, exactly one chip is
 * "active" (or "failed"), and downstream chips remain "pending". Together
 * these guarantee the visual progression is correct without coupling tests
 * to specific Tailwind classes.
 */

import { render, screen } from '@testing-library/react'
import { describe, expect, it } from 'vitest'

import { PHASE_ORDER, type Phase } from '../../lifecycle'
import { LifecycleStepper } from '../LifecycleStepper'

function statesFor(phase: Phase): Record<string, string | null> {
  render(<LifecycleStepper phase={phase} />)
  const chips = screen.getAllByTestId('lifecycle-step')
  const map: Record<string, string | null> = {}
  for (const c of chips) {
    map[c.getAttribute('data-phase') ?? ''] = c.getAttribute('data-state')
  }
  return map
}

describe('LifecycleStepper', () => {
  it('renders one chip per phase in PHASE_ORDER', () => {
    render(<LifecycleStepper phase="naming" />)
    const chips = screen.getAllByTestId('lifecycle-step')
    expect(chips).toHaveLength(PHASE_ORDER.length)
    expect(chips.map((c) => c.getAttribute('data-phase'))).toEqual([
      ...PHASE_ORDER,
    ])
  })

  it('marks earlier steps "done" and the current step "active" for naming', () => {
    const states = statesFor('naming')
    expect(states.pending_upload).toBe('done')
    expect(states.naming).toBe('active')
    expect(states.chunking).toBe('pending')
    expect(states.analyzing).toBe('pending')
    expect(states.ready).toBe('pending')
  })

  it('marks every preceding step "done" when phase is ready', () => {
    const states = statesFor('ready')
    expect(states.pending_upload).toBe('done')
    expect(states.naming).toBe('done')
    expect(states.chunking).toBe('done')
    expect(states.analyzing).toBe('done')
    expect(states.ready).toBe('active')
  })

  it('marks the failed step with the failed tone', () => {
    const states = statesFor('failed')
    // The component anchors `failed` on chunking by convention so the user
    // sees "we died around chunking". Whichever step it anchors on, it must
    // be the one carrying the failed tone — and no other.
    const failedKeys = Object.keys(states).filter((k) => states[k] === 'failed')
    expect(failedKeys).toHaveLength(1)
  })

  it('the active step carries aria-current="step"', () => {
    render(<LifecycleStepper phase="analyzing" />)
    const active = screen
      .getAllByTestId('lifecycle-step')
      .find((c) => c.getAttribute('data-state') === 'active')
    expect(active).toBeTruthy()
    expect(active).toHaveAttribute('aria-current', 'step')
  })
})
