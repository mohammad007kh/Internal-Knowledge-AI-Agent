import type { StepActivityEntry } from '@/lib/sse/agent-events'
import { render, screen } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { useState } from 'react'
import { vi } from 'vitest'
import { CitationPanel, DetailPanel, type PanelContent } from '../CitationPanel'

const citation = {
  id: 'c1',
  document_id: 'd1',
  source_id: 'src1',
  source_name: 'Confluence',
  document_title: 'Architecture Overview',
  excerpt: 'Our microservices follow clean architecture principles.',
  score: 0.88,
  url: 'https://docs.example.com/arch',
}

test('renders citation content when open', () => {
  render(<CitationPanel citation={citation} onClose={vi.fn()} />)
  expect(screen.getByText('Architecture Overview')).toBeInTheDocument()
  expect(screen.getByText(/microservices follow/)).toBeInTheDocument()
  expect(screen.getByText(/88%/)).toBeInTheDocument()
})

test('calls onClose when close button clicked', async () => {
  const onClose = vi.fn()
  render(<CitationPanel citation={citation} onClose={onClose} />)
  await userEvent.click(screen.getByRole('button', { name: /close/i }))
  expect(onClose).toHaveBeenCalled()
})

test('calls onClose on Escape key', async () => {
  const onClose = vi.fn()
  render(<CitationPanel citation={citation} onClose={onClose} />)
  await userEvent.keyboard('{Escape}')
  expect(onClose).toHaveBeenCalled()
})

test('shows external link when url provided', () => {
  render(<CitationPanel citation={citation} onClose={vi.fn()} />)
  const link = screen.getByRole('link', { name: /view original/i })
  expect(link).toHaveAttribute('href', citation.url)
})

test('does not show external link when url is null', () => {
  render(<CitationPanel citation={{ ...citation, url: null }} onClose={vi.fn()} />)
  expect(screen.queryByRole('link', { name: /view original/i })).not.toBeInTheDocument()
})

test('hidden when citation is null', () => {
  render(<CitationPanel citation={null} onClose={vi.fn()} />)
  const panel = screen.getByRole('complementary', { hidden: true })
  expect(panel).toHaveAttribute('aria-hidden', 'true')
})

// --- DetailPanel: step variant (T-073b generalization) ---

const step: StepActivityEntry = {
  kind: 'step',
  stepId: 's1',
  role: 'verifier',
  state: 'finished',
  label: 'Cross-checked the figures',
  summary: 'Compared 7 rows against the source table; all matched.',
  progress: { current: 3, total: 4 },
}

test('DetailPanel renders an agent step payload (role, label, summary)', () => {
  render(<DetailPanel content={{ kind: 'step', step }} onClose={vi.fn()} />)
  expect(screen.getByText('Cross-checked the figures')).toBeInTheDocument()
  expect(screen.getByText('Verifying')).toBeInTheDocument()
  expect(screen.getByText(/compared 7 rows/i)).toBeInTheDocument()
  expect(screen.getByRole('complementary')).toHaveAttribute('aria-label', 'Step details')
})

test('DetailPanel shows a fallback when a step has no summary', () => {
  render(
    <DetailPanel content={{ kind: 'step', step: { ...step, summary: null } }} onClose={vi.fn()} />
  )
  expect(screen.getByText(/no additional detail/i)).toBeInTheDocument()
})

test('DetailPanel renders a citation via the discriminated union', () => {
  render(<DetailPanel content={{ kind: 'citation', citation }} onClose={vi.fn()} />)
  expect(screen.getByText('Architecture Overview')).toBeInTheDocument()
})

test('DetailPanel restores focus to the trigger when closed (non-modal a11y)', async () => {
  function Harness() {
    const [open, setOpen] = useState(false)
    const content: PanelContent | null = open ? { kind: 'step', step } : null
    return (
      <>
        <button type="button" onClick={() => setOpen(true)}>
          open detail
        </button>
        <DetailPanel content={content} onClose={() => setOpen(false)} />
      </>
    )
  }
  render(<Harness />)
  const trigger = screen.getByRole('button', { name: /open detail/i })
  await userEvent.click(trigger) // opens → focus moves to the panel's close button
  expect(trigger).not.toHaveFocus()
  await userEvent.keyboard('{Escape}') // closes
  expect(trigger).toHaveFocus() // focus returned to the trigger, not dropped to body
})
