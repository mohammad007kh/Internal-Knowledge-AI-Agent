import { render, screen } from '@testing-library/react'
import { describe, expect, it } from 'vitest'
import type { AnalyticsOverview, ChatVolumePoint } from '@/lib/api/analytics'
import { KpiRow } from '../KpiRow'

// next/navigation is mocked globally in src/test/setup.ts; next/link works
// directly in jsdom.

function buildOverview(overrides: Partial<AnalyticsOverview> = {}): AnalyticsOverview {
  return {
    range: '7d',
    chat_messages: { count: 1234, previous_count: 1000, delta_pct: 23.4 },
    feedback: { up: 80, down: 20, rated: 100, answered: 250, up_rate: 0.8 },
    sources: {
      active: 12,
      failed_connections: 2,
      by_connection_status: [{ status: 'healthy', count: 10 }, { status: 'failed', count: 2 }],
    },
    sync: { total: 40, success: 38, failed: 2, success_rate: 0.95 },
    schema_studies: { ready: 5, failed: 1, stale: 0, by_state: [] },
    privileged_actions_today: 7,
    ...overrides,
  }
}

const chatVolume: ChatVolumePoint[] = Array.from({ length: 14 }, (_, i) => ({
  date: `2026-05-${String(i + 1).padStart(2, '0')}`,
  count: i * 3,
}))

describe('KpiRow', () => {
  it('renders all six KPIs with formatted values + delta', () => {
    render(<KpiRow overview={buildOverview()} chatVolume={chatVolume} loading={false} rangeLabel="7d" />)

    // 1. Chat messages — toLocaleString'd count + Δ% sub.
    expect(screen.getByText('1,234')).toBeInTheDocument()
    expect(screen.getByText(/\+23\.4% vs prior period/)).toBeInTheDocument()
    // 2. Answer feedback — 80% with "100 rated / 250 answers".
    expect(screen.getByText('80%')).toBeInTheDocument()
    expect(screen.getByText(/100 rated \/ 250 answers/)).toBeInTheDocument()
    // 3. Active sources — 12 with "2 failed".
    expect(screen.getByText('12')).toBeInTheDocument()
    expect(screen.getByText('2 failed')).toBeInTheDocument()
    // 4. Sync success — 95% with "38 of 40 jobs".
    expect(screen.getByText('95%')).toBeInTheDocument()
    expect(screen.getByText(/38 of 40 jobs/)).toBeInTheDocument()
    // 5. Schema studies — "5 ready" with "1 failed", links into /admin/sources.
    expect(screen.getByText('5 ready')).toBeInTheDocument()
    const studiesLink = screen.getByRole('link', { name: /view schema studies in sources/i })
    expect(studiesLink).toHaveAttribute('href', '/admin/sources?schema_status=FAILED')
    // 6. Privileged actions today.
    expect(screen.getByText('7')).toBeInTheDocument()
  })

  it('shows skeleton tiles while loading', () => {
    render(<KpiRow overview={undefined} chatVolume={undefined} loading rangeLabel="7d" />)
    // The loading KpiTiles expose aria-busy.
    const busy = screen.getAllByLabelText(/chat messages|answer feedback|active sources|sync success|schema studies|privileged actions/i)
    expect(busy.length).toBeGreaterThanOrEqual(6)
  })

  it('handles null rates and zero failures gracefully', () => {
    render(
      <KpiRow
        overview={buildOverview({
          chat_messages: { count: 0, previous_count: 0, delta_pct: null },
          feedback: { up: 0, down: 0, rated: 0, answered: 0, up_rate: null },
          sources: { active: 3, failed_connections: 0, by_connection_status: [] },
          sync: { total: 0, success: 0, failed: 0, success_rate: null },
          schema_studies: { ready: 0, failed: 0, stale: 0, by_state: [] },
        })}
        chatVolume={[]}
        loading={false}
        rangeLabel="7d"
      />
    )
    expect(screen.getByText('no prior data')).toBeInTheDocument()
    expect(screen.getByText('all reachable')).toBeInTheDocument()
    // up_rate / success_rate null → "—"
    expect(screen.getAllByText('—').length).toBeGreaterThanOrEqual(2)
  })
})
