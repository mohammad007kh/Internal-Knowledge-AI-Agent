import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import { render, screen } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { describe, expect, it, vi } from 'vitest'
import { SourcesTable } from '../SourcesTable'

vi.mock('@/lib/api-client', () => ({
  apiClient: {
    get: vi.fn().mockResolvedValue({
      data: {
        items: [
          {
            id: 'src1',
            name: 'Confluence Wiki',
            connector_type: 'confluence',
            status: 'ready',
            document_count: 42,
            last_synced_at: null,
            created_at: '',
          },
          {
            id: 'src2',
            name: 'Jira Backlog',
            connector_type: 'jira',
            status: 'error',
            document_count: 0,
            last_synced_at: null,
            created_at: '',
          },
        ],
        total: 2,
        page: 1,
        page_size: 20,
      },
    }),
    post: vi.fn().mockResolvedValue({ data: {} }),
    delete: vi.fn().mockResolvedValue({ data: {} }),
  },
}))

function wrapper({ children }: { children: React.ReactNode }) {
  const queryClient = new QueryClient({
    defaultOptions: { queries: { retry: false } },
  })
  return <QueryClientProvider client={queryClient}>{children}</QueryClientProvider>
}

describe('SourcesTable', () => {
  it('renders sources in table', async () => {
    render(<SourcesTable />, { wrapper })
    expect(await screen.findByText('Confluence Wiki')).toBeInTheDocument()
    expect(screen.getByText('Jira Backlog')).toBeInTheDocument()
  })

  it('shows correct status badges', async () => {
    render(<SourcesTable />, { wrapper })
    expect(await screen.findByText('ready')).toBeInTheDocument()
    expect(screen.getByText('error')).toBeInTheDocument()
  })

  it('trigger sync button calls POST /sources/{id}/sync', async () => {
    const { apiClient } = await import('@/lib/api-client')
    const user = userEvent.setup()
    render(<SourcesTable />, { wrapper })
    const syncBtn = await screen.findByRole('button', { name: /sync confluence wiki/i })
    await user.click(syncBtn)
    expect(apiClient.post).toHaveBeenCalledWith('/sources/src1/sync')
  })

  it('delete shows confirmation dialog', async () => {
    const user = userEvent.setup()
    render(<SourcesTable />, { wrapper })
    const deleteBtn = await screen.findByRole('button', { name: /delete confluence wiki/i })
    await user.click(deleteBtn)
    expect(await screen.findByText(/all indexed documents and embeddings/i)).toBeInTheDocument()
  })
})
