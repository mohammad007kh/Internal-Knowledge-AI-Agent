import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import { render, screen, waitFor } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { FeedbackButtons } from '../FeedbackButtons'

vi.mock('@/lib/api-client', () => ({
  apiClient: {
    post: vi.fn().mockResolvedValue({ data: { id: 'fb1', rating: 1, comment: null } }),
  },
}))

vi.mock('sonner', () => ({
  toast: { error: vi.fn() },
}))

function wrapper({ children }: { children: React.ReactNode }) {
  const qc = new QueryClient({ defaultOptions: { queries: { retry: false } } })
  return <QueryClientProvider client={qc}>{children}</QueryClientProvider>
}

describe('FeedbackButtons', () => {
  it('renders thumbs up and thumbs down buttons', () => {
    render(<FeedbackButtons sessionId="s1" messageId="m1" initialRating={null} />, { wrapper })
    expect(screen.getByRole('button', { name: /mark as helpful/i })).toBeInTheDocument()
    expect(screen.getByRole('button', { name: /mark as unhelpful/i })).toBeInTheDocument()
  })

  it('thumbs up calls API and disables buttons after success', async () => {
    const { apiClient } = await import('@/lib/api-client')
    ;(apiClient.post as ReturnType<typeof vi.fn>).mockResolvedValueOnce({
      data: { id: 'fb1', rating: 1, comment: null },
    })

    render(<FeedbackButtons sessionId="s1" messageId="m1" initialRating={null} />, { wrapper })

    const thumbsUp = screen.getByRole('button', { name: /mark as helpful/i })
    await userEvent.click(thumbsUp)

    await waitFor(() => {
      expect(apiClient.post).toHaveBeenCalledWith('/api/v1/chat/sessions/s1/messages/m1/feedback', {
        rating: 1,
        comment: null,
      })
    })

    await waitFor(() => {
      expect(screen.getByRole('button', { name: /mark as helpful/i })).toBeDisabled()
      expect(screen.getByRole('button', { name: /mark as unhelpful/i })).toBeDisabled()
    })
  })

  it('thumbs down opens the feedback popover', async () => {
    render(<FeedbackButtons sessionId="s1" messageId="m1" initialRating={null} />, { wrapper })

    const thumbsDown = screen.getByRole('button', { name: /mark as unhelpful/i })
    await userEvent.click(thumbsDown)

    await waitFor(() => {
      expect(screen.getByRole('dialog', { name: /provide feedback details/i })).toBeVisible()
    })
  })

  it('thumbs down submits with comment', async () => {
    const { apiClient } = await import('@/lib/api-client')
    ;(apiClient.post as ReturnType<typeof vi.fn>).mockResolvedValueOnce({
      data: { id: 'fb2', rating: -1, comment: 'Wrong answer' },
    })

    render(<FeedbackButtons sessionId="s1" messageId="m1" initialRating={null} />, { wrapper })

    await userEvent.click(screen.getByRole('button', { name: /mark as unhelpful/i }))

    await waitFor(() => {
      expect(screen.getByRole('dialog', { name: /provide feedback details/i })).toBeVisible()
    })

    await userEvent.type(screen.getByRole('textbox', { name: /feedback comment/i }), 'Wrong answer')
    await userEvent.click(screen.getByRole('button', { name: /^submit$/i }))

    await waitFor(() => {
      expect(apiClient.post).toHaveBeenCalledWith('/api/v1/chat/sessions/s1/messages/m1/feedback', {
        rating: -1,
        comment: 'Wrong answer',
      })
    })
  })

  it('shows initial rating state when pre-existing rating provided', () => {
    render(<FeedbackButtons sessionId="s1" messageId="m1" initialRating={1} />, { wrapper })

    expect(screen.getByRole('button', { name: /mark as helpful/i })).toBeDisabled()
    expect(screen.getByRole('button', { name: /mark as unhelpful/i })).toBeDisabled()
  })
})
