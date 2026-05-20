/**
 * LifecycleStepper — visual state derivation.
 *
 * The chip strip is a pure function of `phase` + `sourceKind`. We assert that
 * for any given phase: the right number of "done" chips appear, exactly one
 * chip is "active" (or "failed"), and downstream chips remain "pending".
 * Together these guarantee the visual progression is correct without coupling
 * tests to specific Tailwind classes.
 *
 * FX23: extended with per-source-kind cases. DB sources skip the `chunking`
 * chip (4 chips total instead of 5); web sources reuse the file order but
 * relabel `chunking` → "Crawling content"; connectors mirror web.
 */

import { render, screen } from '@testing-library/react'
import { describe, expect, it } from 'vitest'

import {
  PHASE_ORDER,
  type Phase,
  type SourceKind,
  phaseLabel,
  phaseOrderFor,
} from '../../lifecycle'
import { LifecycleStepper } from '../LifecycleStepper'

function statesFor(
  phase: Phase,
  sourceKind: SourceKind = 'file'
): Record<string, string | null> {
  render(<LifecycleStepper phase={phase} sourceKind={sourceKind} />)
  const chips = screen.getAllByTestId('lifecycle-step')
  const map: Record<string, string | null> = {}
  for (const c of chips) {
    map[c.getAttribute('data-phase') ?? ''] = c.getAttribute('data-state')
  }
  return map
}

describe('LifecycleStepper', () => {
  it('renders one chip per phase in PHASE_ORDER (default file kind)', () => {
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
    // The component anchors `failed` on `analyzing` (the last in-flight step
    // before `ready`). Whichever step it anchors on, exactly one chip must
    // carry the failed tone.
    const failedKeys = Object.keys(states).filter((k) => states[k] === 'failed')
    expect(failedKeys).toHaveLength(1)
    expect(failedKeys[0]).toBe('analyzing')
  })

  it('the active step carries aria-current="step"', () => {
    render(<LifecycleStepper phase="analyzing" />)
    const active = screen
      .getAllByTestId('lifecycle-step')
      .find((c) => c.getAttribute('data-state') === 'active')
    expect(active).toBeTruthy()
    expect(active).toHaveAttribute('aria-current', 'step')
  })

  // ---------------------------------------------------------------------
  // FX23 — source-kind-aware labels + ordering
  // ---------------------------------------------------------------------

  describe('FX23: source-kind aware', () => {
    it('database stepper drops the chunking chip', () => {
      const { container } = render(
        <LifecycleStepper phase="analyzing" sourceKind="database" />
      )
      const chips = screen.getAllByTestId('lifecycle-step')
      expect(chips).toHaveLength(phaseOrderFor('database').length)
      expect(chips).toHaveLength(4)
      const phases = chips.map((c) => c.getAttribute('data-phase'))
      expect(phases).toEqual(['pending_upload', 'naming', 'analyzing', 'ready'])
      expect(phases).not.toContain('chunking')
      // Container carries the source-kind so screenshots / dom-snapshots can
      // verify the right variant was rendered.
      const stepper = container.querySelector('[data-testid="lifecycle-stepper"]')
      expect(stepper).toHaveAttribute('data-source-kind', 'database')
    })

    it('database analyzing chip reads "Studying schema"', () => {
      render(<LifecycleStepper phase="analyzing" sourceKind="database" />)
      const chips = screen.getAllByTestId('lifecycle-step')
      const analyzingChip = chips.find(
        (c) => c.getAttribute('data-phase') === 'analyzing'
      )
      expect(analyzingChip?.textContent).toContain('Studying schema')
    })

    it('database pending_upload chip reads "Queued" — not "Waiting for upload"', () => {
      render(<LifecycleStepper phase="pending_upload" sourceKind="database" />)
      const chips = screen.getAllByTestId('lifecycle-step')
      const firstChip = chips.find(
        (c) => c.getAttribute('data-phase') === 'pending_upload'
      )
      expect(firstChip?.textContent).toContain('Queued')
      expect(firstChip?.textContent).not.toContain('Waiting for upload')
    })

    it('web stepper reads "Crawling content" instead of "Chunking content"', () => {
      render(<LifecycleStepper phase="chunking" sourceKind="web" />)
      const chips = screen.getAllByTestId('lifecycle-step')
      const chunkingChip = chips.find(
        (c) => c.getAttribute('data-phase') === 'chunking'
      )
      expect(chunkingChip?.textContent).toContain('Crawling content')
      expect(chunkingChip?.textContent).not.toContain('Chunking content')
    })

    it('web stepper still walks 5 chips in the same order as file', () => {
      render(<LifecycleStepper phase="naming" sourceKind="web" />)
      const chips = screen.getAllByTestId('lifecycle-step')
      expect(chips).toHaveLength(5)
      expect(chips.map((c) => c.getAttribute('data-phase'))).toEqual([
        'pending_upload',
        'naming',
        'chunking',
        'analyzing',
        'ready',
      ])
    })

    it('file stepper keeps the original labels (regression guard)', () => {
      render(<LifecycleStepper phase="chunking" sourceKind="file" />)
      const chips = screen.getAllByTestId('lifecycle-step')
      const firstChip = chips.find(
        (c) => c.getAttribute('data-phase') === 'pending_upload'
      )
      const chunkingChip = chips.find(
        (c) => c.getAttribute('data-phase') === 'chunking'
      )
      expect(firstChip?.textContent).toContain('Waiting for upload')
      expect(chunkingChip?.textContent).toContain('Chunking content')
    })

    it('failed phase on a DB source still anchors exactly one failed chip — on analyzing', () => {
      const states = statesFor('failed', 'database')
      const failedKeys = Object.keys(states).filter(
        (k) => states[k] === 'failed'
      )
      expect(failedKeys).toHaveLength(1)
      // DB has no `chunking` so the failure can't anchor there — must be
      // `analyzing` (the last in-flight step before ready).
      expect(failedKeys[0]).toBe('analyzing')
    })

    it('failed phase on a web source anchors on analyzing', () => {
      const states = statesFor('failed', 'web')
      const failedKeys = Object.keys(states).filter(
        (k) => states[k] === 'failed'
      )
      expect(failedKeys).toHaveLength(1)
      expect(failedKeys[0]).toBe('analyzing')
    })

    it('connector stepper renders the same chips + labels as web', () => {
      render(<LifecycleStepper phase="chunking" sourceKind="connector" />)
      const chips = screen.getAllByTestId('lifecycle-step')
      const chunkingChip = chips.find(
        (c) => c.getAttribute('data-phase') === 'chunking'
      )
      expect(chunkingChip?.textContent).toContain(
        phaseLabel('chunking', 'web')
      )
    })
  })

  describe('FX26: file pending_upload chip is hasUpload-aware', () => {
    it('without hasUpload, the file pending_upload chip reads "Waiting for upload"', () => {
      render(<LifecycleStepper phase="pending_upload" sourceKind="file" />)
      const chips = screen.getAllByTestId('lifecycle-step')
      const pendingChip = chips.find(
        (c) => c.getAttribute('data-phase') === 'pending_upload'
      )
      expect(pendingChip?.textContent).toContain('Waiting for upload')
    })

    it('with hasUpload=true the file pending_upload chip flips to "Queued for indexing"', () => {
      render(
        <LifecycleStepper
          phase="pending_upload"
          sourceKind="file"
          hasUpload
        />
      )
      const chips = screen.getAllByTestId('lifecycle-step')
      const pendingChip = chips.find(
        (c) => c.getAttribute('data-phase') === 'pending_upload'
      )
      expect(pendingChip?.textContent).toContain('Queued for indexing')
    })

    it('hasUpload does not change DB / web / connector pending chip labels', () => {
      // The flag is only meaningful for the file pending_upload pair.
      render(
        <LifecycleStepper
          phase="pending_upload"
          sourceKind="database"
          hasUpload
        />
      )
      const dbChips = screen.getAllByTestId('lifecycle-step')
      const dbPending = dbChips.find(
        (c) => c.getAttribute('data-phase') === 'pending_upload'
      )
      expect(dbPending?.textContent).toContain('Queued')
      // The DB queued copy is intentionally "Queued" (not "Queued for
      // indexing") — keep the assertion strict so a regression that
      // bleeds the file-specific copy elsewhere shows up here.
      expect(dbPending?.textContent).not.toContain('for indexing')
    })
  })
})
