import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import { render, screen } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { vi } from 'vitest'
import { SourceSelector } from '../SourceSelector'

vi.mock('@/lib/api-client', () => ({
  apiClient: {
    get: vi.fn().mockResolvedValue({
      data: {
        items: [
          { id: 'src1', name: 'Confluence Wiki', type: 'confluence', document_count: 45 },
          { id: 'src2', name: 'Jira Tickets', type: 'jira', document_count: 120 },
        ],
        total: 2,
      },
    }),
  },
}))

function wrapper({ children }: { children: React.ReactNode }) {
  const qc = new QueryClient({ defaultOptions: { queries: { retry: false } } })
  return <QueryClientProvider client={qc}>{children}</QueryClientProvider>
}

test("renders trigger with 'All sources' when nothing selected", () => {
  render(<SourceSelector selectedIds={[]} onChange={vi.fn()} />, { wrapper })
  expect(screen.getByRole('button', { name: /all sources/i })).toBeInTheDocument()
})

test('opens popover and lists sources', async () => {
  render(<SourceSelector selectedIds={[]} onChange={vi.fn()} />, { wrapper })
  await userEvent.click(screen.getByRole('button', { name: /all sources/i }))
  expect(await screen.findByText('Confluence Wiki')).toBeInTheDocument()
  expect(screen.getByText('Jira Tickets')).toBeInTheDocument()
})

test('calls onChange when a source is toggled', async () => {
  const onChange = vi.fn()
  render(<SourceSelector selectedIds={[]} onChange={onChange} />, { wrapper })
  await userEvent.click(screen.getByRole('button', { name: /all sources/i }))
  const item = await screen.findByRole('option', { name: /confluence wiki/i })
  await userEvent.click(item)
  expect(onChange).toHaveBeenCalledWith(['src1'])
})
