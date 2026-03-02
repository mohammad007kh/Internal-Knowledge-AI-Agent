import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import { render, screen } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { describe, expect, it, vi } from 'vitest'
import { SelectedSessionProvider } from '../SelectedSessionContext'
import { SessionList } from '../SessionList'

vi.mock('@/lib/api-client', () => ({
  apiClient: {
    get: vi.fn().mockResolvedValue({
      data: {
        items: [{ id: 's1', title: 'First', updated_at: '', message_count: 2 }],
        total: 1,
        limit: 50,
        offset: 0,
      },
    }),
    post: vi.fn().mockResolvedValue({
      data: { id: 's2', title: 'New Chat', updated_at: '', message_count: 0 },
    }),
    delete: vi.fn().mockResolvedValue({ data: {} }),
  },
}))

function wrapper({ children }: { children: React.ReactNode }) {
  const qc = new QueryClient({ defaultOptions: { queries: { retry: false } } })
  return (
    <QueryClientProvider client={qc}>
      <SelectedSessionProvider>{children}</SelectedSessionProvider>
    </QueryClientProvider>
  )
}

describe('SessionList', () => {
  it('renders session list items', async () => {
    render(<SessionList />, { wrapper })
    expect(await screen.findByText('First')).toBeInTheDocument()
  })

  it("'new chat' button calls createSession API", async () => {
    const user = userEvent.setup()
    render(<SessionList />, { wrapper })
    await user.click(screen.getByRole('button', { name: /new chat/i }))
    const { apiClient } = await import('@/lib/api-client')
    expect(apiClient.post).toHaveBeenCalledWith(
      '/chat/sessions',
      expect.objectContaining({ title: 'New Chat' })
    )
  })
})
