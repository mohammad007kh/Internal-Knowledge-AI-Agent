import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import { render } from '@testing-library/react'
import { describe, expect, it, vi } from 'vitest'
import { HealthCards } from '../HealthCards'

vi.mock('@/lib/api-client', () => ({
  apiClient: {
    get: vi.fn().mockResolvedValue({
      data: {
        checks: [
          { service: 'database', status: 'ok', latency_ms: 4, detail: null },
          { service: 'redis', status: 'ok', latency_ms: 1, detail: null },
          { service: 'minio', status: 'degraded', latency_ms: 200, detail: null },
          { service: 'celery', status: 'down', latency_ms: null, detail: null },
        ],
        checked_at: '2024-01-01T00:00:00Z',
      },
    }),
  },
}))

function wrapper({ children }: { children: React.ReactNode }) {
  const client = new QueryClient({ defaultOptions: { queries: { retry: false } } })
  return <QueryClientProvider client={client}>{children}</QueryClientProvider>
}

describe('HealthCards', () => {
  it('renders a status card for each service', async () => {
    const { findByRole } = render(<HealthCards />, { wrapper })

    const db = await findByRole('status', { name: /database/i })
    const redis = await findByRole('status', { name: /redis/i })
    const minio = await findByRole('status', { name: /minio/i })
    const celery = await findByRole('status', { name: /celery/i })

    expect(db).toBeDefined()
    expect(redis).toBeDefined()
    expect(minio).toBeDefined()
    expect(celery).toBeDefined()
  })
})
