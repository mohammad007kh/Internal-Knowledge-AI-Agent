import { apiClient } from '@/lib/api-client'

// ---------------------------------------------------------------------------
// Audit-log domain types
//
// Mirrors backend/src/schemas/admin_audit_log.py exactly. The wire `id` is a
// string because the backend's BIGINT primary key would overflow JavaScript's
// safe-integer range (2^53) once the table grows past it.
// ---------------------------------------------------------------------------

export interface AuditLogEntry {
  id: string
  created_at: string
  action: string
  resource_type: string
  resource_id: string | null
  admin_user_id: string | null
  admin_user_email: string | null
  metadata: Record<string, unknown>
  ip_address: string | null
  user_agent: string | null
}

export interface PaginatedAuditLog {
  items: AuditLogEntry[]
  total: number
  page: number
  page_size: number
}

/**
 * Filter set forwarded to ``GET /api/v1/admin/audit-log``.
 *
 * All fields are optional. ``from`` / ``to`` are ISO 8601 datetimes (the
 * backend accepts the standard FastAPI / Pydantic datetime parser); the
 * server returns 422 when ``from > to``.
 *
 * Note: ``from`` is a reserved word in JS, so the property here mirrors the
 * URL param name verbatim — callers spread it into ``URLSearchParams`` and
 * the server reads ``alias='from'``.
 */
export interface ListAuditLogParams {
  page?: number
  page_size?: number
  action?: string
  resource_type?: string
  admin_user_id?: string
  from?: string
  to?: string
  search?: string
}

function buildParams(input: ListAuditLogParams): Record<string, string | number> {
  const out: Record<string, string | number> = {}
  if (input.page !== undefined) out.page = input.page
  if (input.page_size !== undefined) out.page_size = input.page_size
  if (input.action) out.action = input.action
  if (input.resource_type) out.resource_type = input.resource_type
  if (input.admin_user_id) out.admin_user_id = input.admin_user_id
  if (input.from) out.from = input.from
  if (input.to) out.to = input.to
  if (input.search) out.search = input.search
  return out
}

export async function listAuditLogApi(
  params: ListAuditLogParams = {}
): Promise<PaginatedAuditLog> {
  const { data } = await apiClient.get<PaginatedAuditLog>('/api/v1/admin/audit-log', {
    params: buildParams(params),
  })
  return data
}
