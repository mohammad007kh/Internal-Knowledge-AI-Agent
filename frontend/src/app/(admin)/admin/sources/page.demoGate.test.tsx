import { render, screen } from '@testing-library/react'
import { Suspense } from 'react'
import type { ReadonlyURLSearchParams } from 'next/navigation'
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'

/**
 * Sources page — demo escape hatch gating tests.
 *
 * The `?demo=db-states` query param is supposed to swap the live sources
 * table for a fixed mock dataset. To prevent prod URL-fishing (an admin
 * shown a link to "see the demo" wouldn't realise live data is hidden),
 * the trigger only fires in development builds.
 *
 * These tests stub `useSearchParams` and the heavy children so we can
 * assert on the prop passed to the table — `demoSources` — under both
 * `NODE_ENV` values.
 *
 * File lives next to `page.tsx` (rather than under `__tests__/`) so it is
 * picked up by the closing-routine filter
 * `npx vitest run "src/app/(admin)/admin/sources/page"`.
 */

// Hoisted spies so the mocks below see them before this module's body runs.
const { kpiSpy, tableSpy, useSearchParamsMock } = vi.hoisted(() => ({
  kpiSpy: vi.fn(),
  tableSpy: vi.fn(),
  useSearchParamsMock: vi.fn(),
}))

vi.mock('next/navigation', () => ({
  useSearchParams: () => useSearchParamsMock(),
  useRouter: () => ({
    push: vi.fn(),
    replace: vi.fn(),
    back: vi.fn(),
    forward: vi.fn(),
    refresh: vi.fn(),
    prefetch: vi.fn(),
  }),
  useParams: () => ({}),
  usePathname: () => '/admin/sources',
  redirect: vi.fn(),
}))

vi.mock(
  '@/app/(admin)/admin/sources/_components/SourcesKpiStrip',
  () => ({
    SourcesKpiStrip: (props: { sources: unknown; loading: boolean }) => {
      kpiSpy(props)
      return <div data-testid="kpi-strip" />
    },
  }),
)

vi.mock(
  '@/app/(admin)/admin/sources/_components/SourcesTable',
  () => ({
    SourcesTable: (props: { demoSources?: unknown }) => {
      tableSpy(props)
      return <div data-testid="sources-table" />
    },
    SourcesTableSkeleton: () => <div data-testid="sources-table-skeleton" />,
  }),
)

// `useListSources` only feeds the KPI container; in this test we only assert
// on the demo prop that flows from `isDemoDbStates`, not the live data path.
vi.mock('@/features/sources/hooks/useSources', () => ({
  useListSources: () => ({ data: { items: [] }, isLoading: false }),
}))

import SourcesPage from './page'

function _toReadonlyParams(input: URLSearchParams): ReadonlyURLSearchParams {
  // next/navigation's ReadonlyURLSearchParams is structurally URLSearchParams
  // minus the mutators. Casting is safe for tests — the page only calls .get().
  return input as unknown as ReadonlyURLSearchParams
}

function renderPage() {
  return render(
    <Suspense fallback={null}>
      <SourcesPage />
    </Suspense>,
  )
}

describe('SourcesPage — ?demo=db-states gating', () => {
  beforeEach(() => {
    kpiSpy.mockClear()
    tableSpy.mockClear()
    useSearchParamsMock.mockReset()
  })

  afterEach(() => {
    vi.unstubAllEnvs()
  })

  it('passes DEMO_DB_SOURCES to the table when ?demo=db-states is set in development', () => {
    vi.stubEnv('NODE_ENV', 'development')
    useSearchParamsMock.mockReturnValue(
      _toReadonlyParams(new URLSearchParams('demo=db-states')),
    )

    renderPage()

    // The dev-mode demo banner should be visible.
    expect(
      screen.getByText(/Demo mode · DB studying-agent states · live data hidden/),
    ).toBeInTheDocument()

    expect(tableSpy).toHaveBeenCalled()
    const lastTableCall = tableSpy.mock.calls.at(-1)?.[0] as { demoSources?: unknown }
    expect(lastTableCall.demoSources).toBeDefined()
    expect(Array.isArray(lastTableCall.demoSources)).toBe(true)
  })

  it('IGNORES ?demo=db-states when NODE_ENV is production', () => {
    vi.stubEnv('NODE_ENV', 'production')
    useSearchParamsMock.mockReturnValue(
      _toReadonlyParams(new URLSearchParams('demo=db-states')),
    )

    renderPage()

    // No demo banner.
    expect(
      screen.queryByText(/Demo mode · DB studying-agent states · live data hidden/),
    ).not.toBeInTheDocument()

    // The table receives `undefined` for demoSources — the live data path.
    expect(tableSpy).toHaveBeenCalled()
    const lastTableCall = tableSpy.mock.calls.at(-1)?.[0] as { demoSources?: unknown }
    expect(lastTableCall.demoSources).toBeUndefined()
  })

  it('IGNORES ?demo=db-states when NODE_ENV is test (i.e. anything other than development)', () => {
    vi.stubEnv('NODE_ENV', 'test')
    useSearchParamsMock.mockReturnValue(
      _toReadonlyParams(new URLSearchParams('demo=db-states')),
    )

    renderPage()

    expect(
      screen.queryByText(/Demo mode · DB studying-agent states · live data hidden/),
    ).not.toBeInTheDocument()

    const lastTableCall = tableSpy.mock.calls.at(-1)?.[0] as { demoSources?: unknown }
    expect(lastTableCall.demoSources).toBeUndefined()
  })

  it('does NOT activate demo mode when ?demo is missing, even in development', () => {
    vi.stubEnv('NODE_ENV', 'development')
    useSearchParamsMock.mockReturnValue(_toReadonlyParams(new URLSearchParams()))

    renderPage()

    expect(
      screen.queryByText(/Demo mode · DB studying-agent states · live data hidden/),
    ).not.toBeInTheDocument()

    const lastTableCall = tableSpy.mock.calls.at(-1)?.[0] as { demoSources?: unknown }
    expect(lastTableCall.demoSources).toBeUndefined()
  })
})
