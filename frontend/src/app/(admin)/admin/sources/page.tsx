'use client'

import { Button } from '@/components/ui/button'
import { useListSources } from '@/features/sources/hooks/useSources'
import { PlusIcon } from 'lucide-react'
import Link from 'next/link'
import { useSearchParams } from 'next/navigation'
import { Suspense } from 'react'
import { SourcesKpiStrip } from './_components/SourcesKpiStrip'
import { SourcesTable, SourcesTableSkeleton } from './_components/SourcesTable'
import { DEMO_DB_SOURCES } from './_components/demoSources'

/**
 * /admin/sources — knowledge source management.
 *
 * Layout mirrors `/admin/ai-models` / `/admin/embedders`:
 *   - p-6 page padding, semibold xl heading, subtitle
 *   - 4-tile KPI hero strip (derived from the same `useListSources` payload)
 *   - Toolbar (search + type chips + status filter + sync-all)
 *   - Table (desktop) / card list (mobile) with dashed empty state
 *
 * KPI strip and table share the same React Query cache key, so the data is
 * fetched once.
 *
 * Demo escape hatch
 * -----------------
 * Append `?demo=db-states` to the URL to swap the live source list for a
 * fixed array of mocked DB rows that exercise every `schema_status` ×
 * `study_state` combination — useful for reviewing the new
 * `DatabaseStudyStrip` + `SourceActionCell` visuals BEFORE Wave 3 wires the
 * real columns onto the API payload. The escape hatch is admin-only because
 * the page itself is gated by the admin layout. It will be removed once
 * Wave 3 ships.
 */
export default function SourcesPage() {
  const searchParams = useSearchParams()
  const demo = searchParams.get('demo')
  const isDemoDbStates = demo === 'db-states'

  return (
    <div className="space-y-4 p-4 md:space-y-6 md:p-6">
      <header className="flex flex-wrap items-start justify-between gap-3">
        <div className="min-w-0">
          <h1 className="text-xl font-semibold">Sources</h1>
          <p className="text-sm text-muted-foreground">
            Connected knowledge sources used for retrieval. Each source feeds documents into the
            embedding pipeline and chat citations.
          </p>
          {isDemoDbStates ? (
            <p className="mt-2 inline-flex items-center gap-2 rounded-md border border-amber-500/40 bg-amber-500/10 px-2 py-1 text-[11px] font-medium text-amber-700 dark:text-amber-300">
              Demo mode · DB studying-agent states · live data hidden
            </p>
          ) : null}
        </div>
        <Button asChild className="w-full gap-1.5 sm:w-auto">
          <Link href="/admin/sources/new">
            <PlusIcon className="h-4 w-4" aria-hidden />
            New source
          </Link>
        </Button>
      </header>

      <SourcesKpiStripContainer demoSources={isDemoDbStates ? DEMO_DB_SOURCES : undefined} />

      <Suspense fallback={<SourcesTableSkeleton />}>
        <SourcesTable demoSources={isDemoDbStates ? DEMO_DB_SOURCES : undefined} />
      </Suspense>
    </div>
  )
}

/**
 * Wraps `SourcesKpiStrip` so it can read the shared `useListSources` cache
 * without forcing the table to lift state up.
 */
function SourcesKpiStripContainer({
  demoSources,
}: {
  demoSources?: typeof DEMO_DB_SOURCES
}) {
  const { data, isLoading } = useListSources()
  const sources = demoSources ?? data?.items ?? []
  return <SourcesKpiStrip sources={sources} loading={demoSources ? false : isLoading} />
}
