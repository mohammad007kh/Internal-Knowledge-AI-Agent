import {
  type ActivityState,
  type AgentEvent,
  activityLogReducer,
  emptyActivityState,
  parseAgentEvent,
} from '@/lib/sse/agent-events'
import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import { render, screen } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { vi } from 'vitest'
import { KEEP_SEARCHING_PROMPT } from '../ContinueSearchAffordance'
import { MessageThread } from '../MessageThread'

function fold(frames: ReadonlyArray<[string, unknown]>): ActivityState {
  return frames
    .map(([t, d]) => parseAgentEvent(t, d))
    .filter((e): e is AgentEvent => e !== null)
    .reduce(activityLogReducer, emptyActivityState)
}

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

test('shows pulsing dots when isPending and !isStreaming and !streamingToken', async () => {
  render(<MessageThread sessionId="s1" isPending />, { wrapper })
  // Wait for the initial messages query to settle so the thread renders, then
  // assert the thinking-dots placeholder bubble is in the document.
  expect(await screen.findByTestId('thinking-dots')).toBeInTheDocument()
  expect(screen.getByLabelText(/assistant is thinking/i)).toBeInTheDocument()
})

// --- T-077 in-flight Layer-1 wiring + flag-off regression ---

test('flag-off regression: empty activityLog keeps the classic PulsingDots, no StatusLine', async () => {
  render(<MessageThread sessionId="s1" isPending activityLog={emptyActivityState} />, { wrapper })
  // Identical to pre-004 behaviour: the thinking-dots bubble, nothing agentic.
  expect(await screen.findByTestId('thinking-dots')).toBeInTheDocument()
  expect(screen.queryByText(/reading|verifying|planning|thinking…/i)).not.toBeInTheDocument()
})

test('attaches a collapsed activity accordion to a finished agentic turn', async () => {
  const activityLog = fold([
    [
      'plan',
      {
        revision: 0,
        steps: [
          { id: 's1', label: 'Read it', source_id: 'u', source_name: 'p' },
          { id: 's2', label: 'Check it', source_id: 'u', source_name: 'p' },
        ],
      },
    ],
    ['step', { step_id: 's1', role: 'executor', state: 'finished', label: 'Read the policy' }],
    ['step', { step_id: 's2', role: 'verifier', state: 'finished', label: 'Verified it' }],
  ])
  // Stream settled (isStreaming false) with a non-empty log; finishedMessageId
  // names the assistant turn (m2) → the snapshot effect keys it under m2 and the
  // accordion attaches to that turn's bubble — independent of refetch timing.
  render(
    <MessageThread
      sessionId="s1"
      isStreaming={false}
      activityLog={activityLog}
      finishedMessageId="m2"
    />,
    { wrapper }
  )
  expect(await screen.findByRole('button', { name: /agent activity/i })).toBeInTheDocument()
})

test('offers "Search again" on a budget-capped last turn and sends the follow-up (T-075)', async () => {
  const onSend = vi.fn()
  const activityLog = fold([
    ['step', { step_id: 's1', role: 'executor', state: 'finished', label: 'Looked' }],
    ['budget', { ceiling_hit: true, not_completed: ['more'], offer_continue: true }],
  ])
  render(
    <MessageThread
      sessionId="s1"
      isStreaming={false}
      activityLog={activityLog}
      finishedMessageId="m2"
      onSend={onSend}
    />,
    { wrapper }
  )
  const again = await screen.findByRole('button', { name: /search again/i })
  await userEvent.click(again)
  expect(onSend).toHaveBeenCalledWith(KEEP_SEARCHING_PROMPT)
})

test('does NOT snapshot under the wrong turn when finishedMessageId is absent', async () => {
  const activityLog = fold([
    ['step', { step_id: 's1', role: 'executor', state: 'finished', label: 'Read it' }],
  ])
  // No finishedMessageId (mid-flight / no terminal id yet) → no accordion latched
  // onto the most-recent persisted message (the Q1 mis-attribution guard).
  render(<MessageThread sessionId="s1" isStreaming={false} activityLog={activityLog} />, {
    wrapper,
  })
  await screen.findByText('Hi there!')
  expect(screen.queryByRole('button', { name: /agent activity/i })).not.toBeInTheDocument()
})

test('replaces PulsingDots with the live StatusLine once the agent narrates a step', async () => {
  const activityLog = fold([
    [
      'plan',
      { revision: 0, steps: [{ id: 's1', label: 'Read it', source_id: 'u', source_name: 'p' }] },
    ],
    [
      'step',
      {
        step_id: 's1',
        role: 'executor',
        state: 'started',
        label: 'Reading the policy',
        progress: { current: 1, total: 2 },
      },
    ],
  ])
  render(<MessageThread sessionId="s1" isPending activityLog={activityLog} />, { wrapper })
  expect(await screen.findByText('Reading the policy')).toBeInTheDocument()
  expect(screen.queryByTestId('thinking-dots')).not.toBeInTheDocument()
})
