'use client'

import { AuditLogTable } from '@/app/(admin)/admin/audit-log/_components/AuditLogTable'
import { AuditLogToolbar } from '@/app/(admin)/admin/audit-log/_components/AuditLogToolbar'
import { useAuditLogFilters } from '@/app/(admin)/admin/audit-log/_components/useAuditLogFilters'
import { ErrorState } from '@/components/ui/ErrorState'
import { Card, CardContent } from '@/components/ui/card'
import { Skeleton } from '@/components/ui/skeleton'
import { useAuditLog } from '@/features/audit-log/hooks/useAuditLog'
import { getErrorMessage } from '@/lib/errors'
import { ScrollTextIcon } from 'lucide-react'

const SKELETON_KEYS = ['s1', 's2', 's3', 's4', 's5', 's6', 's7', 's8'] as const

export default function AuditLogPage() {
  const {
    state,
    setState,
    setPage,
    apiParams,
    activeChips,
    clearAll,
    hasActiveFilters,
  } = useAuditLogFilters()

  const { data, isLoading, isError, error, refetch, isFetching } = useAuditLog(apiParams)

  const items = data?.items ?? []
  const total = data?.total ?? 0

  return (
    <div className="space-y-4 p-4 md:space-y-6 md:p-6">
      <div>
        <h1 className="text-xl font-semibold">Audit Log</h1>
        <p className="text-sm text-muted-foreground">
          Append-only record of admin and authentication events. Read-only.
        </p>
      </div>

      <AuditLogToolbar
        state={state}
        onChange={setState}
        activeChips={activeChips}
        onClearAll={clearAll}
        totalCount={total}
        filteredCount={items.length}
      />

      {isLoading ? (
        <div className="space-y-2">
          {SKELETON_KEYS.map((key) => (
            <Skeleton key={key} className="h-10 w-full" />
          ))}
        </div>
      ) : null}

      {isError ? (
        <ErrorState message={getErrorMessage(error)} onRetry={() => refetch()} />
      ) : null}

      {data ? (
        items.length === 0 ? (
          <Card className="border-dashed">
            <CardContent className="flex flex-col items-center gap-3 py-12 text-center">
              <ScrollTextIcon
                className="h-10 w-10 text-muted-foreground"
                aria-hidden
              />
              <div className="space-y-1">
                <p className="text-base font-medium">
                  No audit entries match these filters.
                </p>
                {hasActiveFilters ? (
                  <button
                    type="button"
                    onClick={clearAll}
                    className="text-sm font-medium text-primary hover:underline"
                  >
                    Clear filters
                  </button>
                ) : (
                  <p className="text-sm text-muted-foreground">
                    Audit rows will appear here as admins act on the system.
                  </p>
                )}
              </div>
            </CardContent>
          </Card>
        ) : (
          <div className="relative">
            <AuditLogTable
              items={items}
              total={total}
              page={state.page}
              pageSize={state.pageSize}
              onPageChange={setPage}
            />
            {isFetching && !isLoading ? (
              <div
                aria-hidden
                className="pointer-events-none absolute right-3 top-3 h-2 w-2 animate-pulse rounded-full bg-primary/60"
                title="Refreshing"
              />
            ) : null}
          </div>
        )
      ) : null}
    </div>
  )
}
