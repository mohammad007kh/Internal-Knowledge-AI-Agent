import { render, screen } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { vi } from 'vitest'
import { SourceChips } from '../SourceChips'

const sources = [
  { id: 's1', name: 'Confluence Wiki', source_type: 'confluence', document_count: 10 },
  { id: 's2', name: 'Jira', source_type: 'jira', document_count: 5 },
]

test('renders source badges', () => {
  render(<SourceChips sources={sources} onRemove={vi.fn()} />)
  expect(screen.getByText('Confluence Wiki')).toBeInTheDocument()
  expect(screen.getByText('Jira')).toBeInTheDocument()
})

test('calls onRemove when X clicked', async () => {
  const onRemove = vi.fn()
  render(<SourceChips sources={sources} onRemove={onRemove} />)
  await userEvent.click(screen.getByRole('button', { name: /remove source: confluence wiki/i }))
  expect(onRemove).toHaveBeenCalledWith('s1')
})

test('renders nothing when sources is empty', () => {
  const { container } = render(<SourceChips sources={[]} onRemove={vi.fn()} />)
  expect(container.firstChild).toBeNull()
})
