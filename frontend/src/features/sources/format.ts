/**
 * Shared formatting helpers for the sources feature.
 *
 * Kept dependency-free so it can be imported from server and client modules.
 */

const SECONDS_PER_MINUTE = 60
const MINUTES_PER_HOUR = 60
const HOURS_PER_DAY = 24
const DAYS_PER_MONTH = 30

/**
 * Format an ISO timestamp as a short relative string ("12 min ago", "3h ago",
 * "2d ago"). Falls back to the locale date once the value is older than a
 * month, and returns "Never" for null/undefined.
 */
export function formatRelative(value: string | null | undefined): string {
  if (!value) return 'Never'
  const date = new Date(value)
  if (Number.isNaN(date.getTime())) return 'Never'

  const diffMs = Date.now() - date.getTime()
  const seconds = Math.round(diffMs / 1000)

  if (seconds < SECONDS_PER_MINUTE) {
    return seconds <= 5 ? 'just now' : `${seconds}s ago`
  }
  const minutes = Math.round(seconds / SECONDS_PER_MINUTE)
  if (minutes < MINUTES_PER_HOUR) return `${minutes} min ago`

  const hours = Math.round(minutes / MINUTES_PER_HOUR)
  if (hours < HOURS_PER_DAY) return `${hours}h ago`

  const days = Math.round(hours / HOURS_PER_DAY)
  if (days < DAYS_PER_MONTH) return `${days}d ago`

  return date.toLocaleDateString()
}

/**
 * Coerce optional document-count fields into a finite number, returning null
 * when there is no data so callers can render an em dash.
 */
export function coerceCount(value: number | null | undefined): number | null {
  if (typeof value !== 'number' || !Number.isFinite(value)) return null
  return value
}
