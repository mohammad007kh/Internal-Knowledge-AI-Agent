export interface HealthCheck {
  service: 'database' | 'redis' | 'minio' | 'celery'
  status: 'ok' | 'degraded' | 'down'
  latency_ms: number | null
  detail: string | null
}

export interface SystemHealth {
  checks: HealthCheck[]
  checked_at: string
}

export interface SystemMetrics {
  total_users: number
  active_users_7d: number
  active_sources: number
  total_documents: number
  queries_7d: number
  avg_response_time_ms: number
}

export interface DailyQueryCount {
  date: string
  count: number
}

export interface SourceQueryStat {
  source_id: string
  source_name: string
  query_count: number
}

export interface ActivityEvent {
  id: string
  event_type: string
  message: string
  severity: 'info' | 'warning' | 'error'
  created_at: string
}
