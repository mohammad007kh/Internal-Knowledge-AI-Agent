'use client'

import {
  type ListAuditLogParams,
  type PaginatedAuditLog,
  listAuditLogApi,
} from '@/lib/api/audit-log'
import { keepPreviousData, useQuery } from '@tanstack/react-query'

/**
 * Query-key factory for the admin audit-log feed.
 *
 * Each (filters, page) tuple is cached independently — Previous/Next on
 * the viewer page reuse cached pages instantly without re-hitting the
 * backend, and React Query's `keepPreviousData` keeps the table populated
 * while the next page is in flight (no flicker).
 */
export const auditLogKeys = {
  all: ['admin', 'audit-log'] as const,
  list: (params: ListAuditLogParams) => [...auditLogKeys.all, 'list', params] as const,
}

export interface UseAuditLogOptions {
  /** Set to `false` while a parent dialog/page is hidden to pause the query. */
  enabled?: boolean
}

export function useAuditLog(
  params: ListAuditLogParams = {},
  options: UseAuditLogOptions = {}
) {
  const { enabled = true } = options
  return useQuery<PaginatedAuditLog>({
    queryKey: auditLogKeys.list(params),
    queryFn: () => listAuditLogApi(params),
    enabled,
    // Keep the previous page rendered while the next page is fetching so
    // the table doesn't flash an empty / skeleton state on Previous/Next.
    placeholderData: keepPreviousData,
  })
}
