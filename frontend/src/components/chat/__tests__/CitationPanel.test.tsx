import { render, screen } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { vi } from 'vitest'
import { CitationPanel } from '../CitationPanel'

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
