'use client'

import { Button } from '@/components/ui/button'
import { useListSources } from '@/features/sources/hooks/useSources'
import { PlusIcon } from 'lucide-react'
import Link from 'next/link'
import { Suspense } from 'react'
import { SourcesKpiStrip } from './_components/SourcesKpiStrip'
import { SourcesTable, SourcesTableSkeleton } from './_components/SourcesTable'

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
 */
export default function SourcesPage() {
  return (
    <div className="space-y-4 p-4 md:space-y-6 md:p-6">
      <header className="flex flex-wrap items-start justify-between gap-3">
        <div className="min-w-0">
          <h1 className="text-xl font-semibold">Sources</h1>
          <p className="text-sm text-muted-foreground">
            Connected knowledge sources used for retrieval. Each source feeds documents into the
            embedding pipeline and chat citations.
          </p>
        </div>
        <Button asChild className="w-full gap-1.5 sm:w-auto">
          <Link href="/admin/sources/new">
            <PlusIcon className="h-4 w-4" aria-hidden />
            New source
          </Link>
        </Button>
      </header>

      <SourcesKpiStripContainer />

      <Suspense fallback={<SourcesTableSkeleton />}>
        <SourcesTable />
      </Suspense>
    </div>
  )
}

/**
 * Wraps `SourcesKpiStrip` so it can read the shared `useListSources` cache
 * without forcing the table to lift state up.
 */
function SourcesKpiStripContainer() {
  const { data, isLoading } = useListSources()
  const sources = data?.items ?? []
  return <SourcesKpiStrip sources={sources} loading={isLoading} />
}
