/**
 * Shared formatting utilities.
 *
 * `formatRelative` used to live alongside the `<SyncStatusPill>` component —
 * reaching into a component module for a pure helper was a smell, so it moved
 * here. `SyncStatusPill` re-exports it for backwards compatibility.
 */

// ---------------------------------------------------------------------------
// Relative-time formatter (no extra deps; date-fns is intentionally absent)
//
// Resolution: seconds within the first minute, minutes within the first hour,
// hours within the first day, days within the first fortnight, then the locale
// date string. Null/undefined/unparseable inputs render as "—" so callers
// never have to guard.
// ---------------------------------------------------------------------------

export function formatRelative(value: string | null | undefined, now: number = Date.now()): string {
  if (!value) return '—'
  const ts = new Date(value).getTime()
  if (Number.isNaN(ts)) return '—'
  const deltaSec = Math.max(0, Math.round((now - ts) / 1000))
  if (deltaSec < 5) return 'just now'
  if (deltaSec < 60) return `${deltaSec}s ago`
  const deltaMin = Math.round(deltaSec / 60)
  if (deltaMin < 60) return `${deltaMin}m ago`
  const deltaHr = Math.round(deltaMin / 60)
  if (deltaHr < 24) return `${deltaHr}h ago`
  const deltaDay = Math.round(deltaHr / 24)
  if (deltaDay < 14) return `${deltaDay}d ago`
  return new Date(value).toLocaleDateString()
}
