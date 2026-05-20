/**
 * Tiny relative-time formatter for the analytics dashboard feeds.
 *
 * Local helper (not `@/lib/format`) so this feature has no cross-team
 * dependency — the U10-followups team is in the middle of moving
 * `formatRelative` into `@/lib/format`; once that lands this can be replaced
 * with a re-export.
 */

const UNITS: ReadonlyArray<{ limit: number; div: number; name: string }> = [
  { limit: 60, div: 1, name: 'second' },
  { limit: 3600, div: 60, name: 'minute' },
  { limit: 86_400, div: 3600, name: 'hour' },
  { limit: 604_800, div: 86_400, name: 'day' },
  { limit: 2_629_800, div: 604_800, name: 'week' },
  { limit: 31_557_600, div: 2_629_800, name: 'month' },
  { limit: Number.POSITIVE_INFINITY, div: 31_557_600, name: 'year' },
]

export function timeAgo(value: string | Date | null | undefined): string {
  if (value === null || value === undefined) return '—'
  const then = value instanceof Date ? value : new Date(value)
  const ms = then.getTime()
  if (Number.isNaN(ms)) return '—'

  const diffSec = Math.round((Date.now() - ms) / 1000)
  if (diffSec < 5) return 'just now'

  const abs = Math.abs(diffSec)
  for (const u of UNITS) {
    if (abs < u.limit) {
      const v = Math.round(abs / u.div)
      const plural = v === 1 ? '' : 's'
      return diffSec >= 0 ? `${v} ${u.name}${plural} ago` : `in ${v} ${u.name}${plural}`
    }
  }
  return '—'
}
