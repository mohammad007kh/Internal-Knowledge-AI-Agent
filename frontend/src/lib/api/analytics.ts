import { apiClient, parseErrorResponse } from '@/lib/api-client'

/**
 * Client + types for the redesigned `/api/v1/analytics` surface.
 *
 * Mirrors `backend/src/schemas/analytics.py` exactly. All endpoints are
 * admin-only aggregation reads.
 */

// ---------------------------------------------------------------------------
// Range token (shared with the backend's RANGE_TO_DELTA map)
// ---------------------------------------------------------------------------

export type AnalyticsRange = '24h' | '7d' | '30d' | '90d'

export const ANALYTICS_RANGES: readonly AnalyticsRange[] = ['24h', '7d', '30d', '90d']

export function isAnalyticsRange(value: string): value is AnalyticsRange {
  return (ANALYTICS_RANGES as readonly string[]).includes(value)
}

// ---------------------------------------------------------------------------
// Shared bucket shapes
// ---------------------------------------------------------------------------

export interface CountByKey {
  key: string
  count: number
}

export interface TypeCount {
  type: string
  count: number
}

export interface StatusCount {
  status: string
  count: number
}

// ---------------------------------------------------------------------------
// /analytics/overview
// ---------------------------------------------------------------------------

export interface ChatMessagesKpi {
  count: number
  previous_count: number
  delta_pct: number | null
}

export interface FeedbackKpi {
  up: number
  down: number
  rated: number
  answered: number
  up_rate: number | null
}

export interface SourcesKpi {
  active: number
  failed_connections: number
  by_connection_status: StatusCount[]
}

export interface SyncKpi {
  total: number
  success: number
  failed: number
  success_rate: number | null
}

export interface SchemaStudiesKpi {
  ready: number
  failed: number
  stale: number
  by_state: CountByKey[]
}

export interface AnalyticsOverview {
  range: string
  chat_messages: ChatMessagesKpi
  feedback: FeedbackKpi
  sources: SourcesKpi
  sync: SyncKpi
  schema_studies: SchemaStudiesKpi
  privileged_actions_today: number
}

// ---------------------------------------------------------------------------
// Time-series points
// ---------------------------------------------------------------------------

export interface ChatVolumePoint {
  date: string
  count: number
}

export interface FeedbackTrendPoint {
  date: string
  answered: number
  up: number
  down: number
}

export interface SyncActivityPoint {
  date: string
  success: number
  failed: number
  documents: number
  chunks: number
}

// ---------------------------------------------------------------------------
// /analytics/source-health
// ---------------------------------------------------------------------------

export interface SourceHealthBreakdown {
  by_type: TypeCount[]
  by_connection_status: StatusCount[]
  by_status: StatusCount[]
}

// ---------------------------------------------------------------------------
// /analytics/schema-studies
// ---------------------------------------------------------------------------

export interface RecentSchemaFailure {
  source_id: string
  source_name: string
  last_error_phase: string | null
  last_error_message: string | null
  finished_at: string | null
}

export interface SchemaStudiesBreakdown {
  by_schema_status: StatusCount[]
  recent_failures: RecentSchemaFailure[]
}

// ---------------------------------------------------------------------------
// /analytics/needs-attention
// ---------------------------------------------------------------------------

export type NeedsAttentionKind = 'connection' | 'sync' | 'study'

export interface NeedsAttentionItem {
  source_id: string
  name: string
  kind: NeedsAttentionKind
  detail: string | null
}

// ---------------------------------------------------------------------------
// API calls
// ---------------------------------------------------------------------------

async function get<T>(url: string, params?: Record<string, string>): Promise<T> {
  try {
    const { data } = await apiClient.get<T>(url, params ? { params } : undefined)
    return data
  } catch (error: unknown) {
    throw parseErrorResponse(error)
  }
}

export function getAnalyticsOverview(range: AnalyticsRange): Promise<AnalyticsOverview> {
  return get<AnalyticsOverview>('/api/v1/analytics/overview', { range })
}

export function getChatVolume(range: AnalyticsRange): Promise<ChatVolumePoint[]> {
  return get<ChatVolumePoint[]>('/api/v1/analytics/chat-volume', { range })
}

export function getFeedbackTrend(range: AnalyticsRange): Promise<FeedbackTrendPoint[]> {
  return get<FeedbackTrendPoint[]>('/api/v1/analytics/feedback-trend', { range })
}

export function getSyncActivity(range: AnalyticsRange): Promise<SyncActivityPoint[]> {
  return get<SyncActivityPoint[]>('/api/v1/analytics/sync-activity', { range })
}

export function getSourceHealth(): Promise<SourceHealthBreakdown> {
  return get<SourceHealthBreakdown>('/api/v1/analytics/source-health')
}

export function getSchemaStudies(): Promise<SchemaStudiesBreakdown> {
  return get<SchemaStudiesBreakdown>('/api/v1/analytics/schema-studies')
}

export function getNeedsAttention(): Promise<NeedsAttentionItem[]> {
  return get<NeedsAttentionItem[]>('/api/v1/analytics/needs-attention')
}
