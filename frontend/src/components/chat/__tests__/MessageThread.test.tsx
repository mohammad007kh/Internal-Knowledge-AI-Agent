import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import { render, screen } from '@testing-library/react'
import { describe, expect, it, vi } from 'vitest'
import { MessageThread } from '../MessageThread'

vi.mock('@/lib/api-client', () => ({
  apiClient: {
    get: vi.fn().mockResolvedValue({
      data: {
        session: { id: 's1', title: 'Test Session' },
        messages: [
          { id: 'm1', role: 'user', content: 'Hello', created_at: '' },
          { id: 'm2', role: 'assistant', content: 'Hi there', created_at: '' },
        ],
      },
    }),
  },
}))

function wrapper({ children }: { children: React.ReactNode }) {
  const qc = new QueryClient({ defaultOptions: { queries: { retry: false } } })
  return <QueryClientProvider client={qc}>{children}</QueryClientProvider>
}

describe('MessageThread', () => {
  it('renders messages for a session', async () => {
    render(<MessageThread sessionId="s1" />, { wrapper })
    expect(await screen.findByText('Hello')).toBeInTheDocument()
    expect(screen.getByText('Hi there')).toBeInTheDocument()
  })

  it('shows empty state when no session', () => {
    render(<MessageThread sessionId={null} />, { wrapper })
    expect(screen.getByText(/select a session/i)).toBeInTheDocument()
  })

  it('shows streaming cursor when isStreaming=true', () => {
    render(<MessageThread sessionId="s1" isStreaming streamingToken="" />, { wrapper })
    expect(screen.getByLabelText(/assistant is typing/i)).toBeInTheDocument()
  })
})
