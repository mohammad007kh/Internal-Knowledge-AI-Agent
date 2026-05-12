'use client'

import { Badge } from '@/components/ui/badge'
import { Skeleton } from '@/components/ui/skeleton'
import { type AuditLogEntry, listAuditLogApi } from '@/lib/api/audit-log'
import { cn } from '@/lib/utils'
import { useQuery } from '@tanstack/react-query'
import Link from 'next/link'
import { ChartCard } from './ChartCard'
import { timeAgo } from './timeAgo'

/**
 * RecentActionsFeed — last ~10 admin_audit_log rows.
 *
 * Reuses the existing `GET /api/v1/admin/audit-log?page_size=10` endpoint (no
 * new backend). Action chip styling mirrors `AuditLogTable`; `login_failure`
 * rows are tinted red. "View all →" links to /admin/audit-log.
 */

const PAGE_SIZE = 10

export function RecentActionsFeed() {
  const { data, isLoading, isError } = useQuery({
    queryKey: ['admin', 'audit-log', { page_size: PAGE_SIZE, recent: true }],
    queryFn: () => listAuditLogApi({ page_size: PAGE_SIZE }),
    staleTime: 30_000,
  })

  const items: AuditLogEntry[] = data?.items ?? []

  return (
    <ChartCard
      title="Recent actions"
      actions={
        <Link href="/admin/audit-log" className="text-xs font-medium text-primary hover:underline">
          View all →
        </Link>
      }
    >
      {isLoading ? (
        <div className="space-y-2">
          {['a', 'b', 'c', 'd'].map((k) => (
            <Skeleton key={k} className="h-8 w-full" />
          ))}
        </div>
      ) : isError ? (
        <p className="py-8 text-center text-sm text-muted-foreground">Couldn&apos;t load recent actions.</p>
      ) : items.length === 0 ? (
        <p className="py-8 text-center text-sm text-muted-foreground">No admin actions recorded yet.</p>
      ) : (
        <ul className="divide-y">
          {items.map((row) => {
            const isFailure = row.action === 'login_failure'
            return (
              <li
                key={row.id}
                className={cn('flex items-center gap-2 py-2 text-xs', isFailure && 'bg-destructive/5')}
              >
                <span className="min-w-0 max-w-[40%] truncate" title={row.admin_user_email ?? 'system'}>
                  {row.admin_user_email ?? <span className="italic text-muted-foreground">system</span>}
                </span>
                <Badge
                  variant={isFailure ? 'destructive' : 'secondary'}
                  className="shrink-0 font-mono text-[10px]"
                >
                  {row.action}
                </Badge>
                <span className="hidden text-muted-foreground sm:inline">{row.resource_type}</span>
                <span className="ml-auto shrink-0 text-muted-foreground tabular-nums">
                  {timeAgo(row.created_at)}
                </span>
              </li>
            )
          })}
        </ul>
      )}
    </ChartCard>
  )
}
