'use client'

import { Button } from '@/components/ui/button'
import { SegmentedControl } from '@/components/ui/segmented-control'
import type { AnalyticsRange } from '@/lib/api/analytics'
import { ExternalLinkIcon } from 'lucide-react'

/**
 * Page header for /admin/analytics: title + range toggle + Langfuse deep-link.
 *
 * Langfuse (v1): a deep-link button only — no aggregates surfaced yet.
 * URL resolution order:
 *   1. NEXT_PUBLIC_LANGFUSE_URL if the deployment sets it (matches the
 *      env-driven pattern the rest of the app uses);
 *   2. else `http://localhost:3001` (the docker-compose default;
 *      `HOST_LANGFUSE_PORT` defaults to 3001).
 */

const RANGE_OPTIONS: ReadonlyArray<{ value: AnalyticsRange; label: string }> = [
  { value: '24h', label: '24h' },
  { value: '7d', label: '7d' },
  { value: '30d', label: '30d' },
  { value: '90d', label: '90d' },
]

// Same env-driven pattern as NEXT_PUBLIC_API_URL — falls back to the
// docker-compose default port (HOST_LANGFUSE_PORT defaults to 3001).
const LANGFUSE_URL = process.env.NEXT_PUBLIC_LANGFUSE_URL ?? 'http://localhost:3001'

export interface AnalyticsHeaderProps {
  range: AnalyticsRange
  onRangeChange: (range: AnalyticsRange) => void
}

export function AnalyticsHeader({ range, onRangeChange }: AnalyticsHeaderProps) {
  return (
    <div className="flex flex-col gap-3 sm:flex-row sm:items-center sm:justify-between">
      <h1 className="text-xl font-semibold md:text-2xl">Analytics</h1>
      <div className="flex flex-wrap items-center gap-3">
        <SegmentedControl
          label="Range"
          options={RANGE_OPTIONS}
          value={range}
          onChange={onRangeChange}
        />
        <Button asChild variant="outline" size="sm">
          <a href={LANGFUSE_URL} target="_blank" rel="noreferrer">
            Open Langfuse
            <ExternalLinkIcon className="h-3.5 w-3.5" aria-hidden />
          </a>
        </Button>
      </div>
    </div>
  )
}
