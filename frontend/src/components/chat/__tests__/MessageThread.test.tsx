import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import { render, screen } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { vi } from 'vitest'
import { MessageThread } from '../MessageThread'

vi.mock('@/lib/api-client', () => ({
  apiClient: {
    get: vi.fn().mockResolvedValue({
      data: {
        session: { id: 's1', title: 'Test', source_ids: [] },
        messages: [
          {
            id: 'm1',
            role: 'user',
            content: 'Hello',
            created_at: new Date().toISOString(),
          },
          {
            id: 'm2',
            role: 'assistant',
            content: 'Hi there!',
            created_at: new Date().toISOString(),
            citations: [
              {
                id: 'c1',
                document_id: 'd1',
                source_id: 'src1',
                source_name: 'Wiki',
                document_title: 'Getting Started',
                excerpt: 'This guide explains…',
                score: 0.92,
                url: null,
              },
            ],
          },
        ],
      },
    }),
  },
}))

function wrapper({ children }: { children: React.ReactNode }) {
  const qc = new QueryClient({ defaultOptions: { queries: { retry: false } } })
  return <QueryClientProvider client={qc}>{children}</QueryClientProvider>
}

test('renders persisted messages', async () => {
  render(<MessageThread sessionId="s1" />, { wrapper })
  expect(await screen.findByText('Hello')).toBeInTheDocument()
  expect(await screen.findByText('Hi there!')).toBeInTheDocument()
})

test('shows citation badge on assistant message', async () => {
  render(<MessageThread sessionId="s1" />, { wrapper })
  const citationBtn = await screen.findByRole('button', { name: /view citation 1/i })
  expect(citationBtn).toBeInTheDocument()
})

test('opens citation panel on citation click', async () => {
  render(<MessageThread sessionId="s1" />, { wrapper })
  const citationBtn = await screen.findByRole('button', { name: /view citation 1/i })
  await userEvent.click(citationBtn)
  expect(screen.getByText('Getting Started')).toBeInTheDocument()
  expect(screen.getByText(/This guide explains/)).toBeInTheDocument()
})

test('renders streaming bubble when isStreaming=true', () => {
  render(<MessageThread sessionId="s1" isStreaming streamingToken="Thinking about" />, {
    wrapper,
  })
  expect(screen.getByText(/Thinking about/)).toBeInTheDocument()
})

test('shows placeholder when no sessionId', () => {
  render(<MessageThread sessionId={null} />, { wrapper })
  expect(screen.getByText(/select or create a session/i)).toBeInTheDocument()
})
