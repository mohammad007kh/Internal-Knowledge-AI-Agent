/**
 * Unit tests for `formatRelative` — the relative-time formatter shared by the
 * source-detail header pill, the Overview cards, and the AI-naming card.
 *
 * `now` is pinned so the buckets are deterministic.
 */
import { describe, expect, it } from 'vitest'

import { formatRelative } from '../format'

const NOW = new Date('2026-05-12T12:00:00Z').getTime()

function ago(ms: number): string {
  return new Date(NOW - ms).toISOString()
}

const SECOND = 1000
const MINUTE = 60 * SECOND
const HOUR = 60 * MINUTE
const DAY = 24 * HOUR

describe('formatRelative', () => {
  it('renders "—" for null / undefined', () => {
    expect(formatRelative(null, NOW)).toBe('—')
    expect(formatRelative(undefined, NOW)).toBe('—')
  })

  it('renders "—" for an unparseable string', () => {
    expect(formatRelative('not-a-date', NOW)).toBe('—')
  })

  it('renders "just now" within the first 5 seconds', () => {
    expect(formatRelative(ago(0), NOW)).toBe('just now')
    expect(formatRelative(ago(3 * SECOND), NOW)).toBe('just now')
  })

  it('renders "{n}s ago" within the first minute', () => {
    expect(formatRelative(ago(30 * SECOND), NOW)).toBe('30s ago')
  })

  it('renders "{n}m ago" within the first hour', () => {
    expect(formatRelative(ago(5 * MINUTE), NOW)).toBe('5m ago')
  })

  it('renders "{n}h ago" within the first day', () => {
    expect(formatRelative(ago(3 * HOUR), NOW)).toBe('3h ago')
  })

  it('renders "{n}d ago" within the first fortnight', () => {
    expect(formatRelative(ago(2 * DAY), NOW)).toBe('2d ago')
  })

  it('falls back to the locale date string past two weeks', () => {
    const old = ago(30 * DAY)
    expect(formatRelative(old, NOW)).toBe(new Date(old).toLocaleDateString())
  })

  it('clamps future timestamps to "just now" (never negative)', () => {
    expect(formatRelative(new Date(NOW + 10 * SECOND).toISOString(), NOW)).toBe('just now')
  })

  it('defaults `now` to Date.now() when omitted', () => {
    // A timestamp ~5 minutes in the past, computed against the real clock.
    const fiveMinAgo = new Date(Date.now() - 5 * MINUTE).toISOString()
    expect(formatRelative(fiveMinAgo)).toBe('5m ago')
  })
})
