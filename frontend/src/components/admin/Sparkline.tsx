import type { JSX } from 'react'

/**
 * Sparkline — minimal, dependency-free inline SVG line chart.
 *
 * Designed as a server-component-friendly presentational primitive that
 * inherits its color from the parent via `currentColor`. The caller controls
 * the color with Tailwind text-* classes.
 *
 * Usage:
 *   <Sparkline data={[3, 5, 2, 9, 6]} className="text-primary" />
 *   <Sparkline data={[]} />                       // renders null
 *   <Sparkline data={[7]} ariaLabel="One value" /> // tiny horizontal mark
 *
 * Notes:
 * - No `'use client'`: pure SVG, no state, no effects.
 * - `vector-effect="non-scaling-stroke"` keeps stroke width constant on resize.
 * - Y axis is inverted in SVG, so we map max → top (PADDING) and min → bottom.
 */

export interface SparklineProps {
  data: number[]
  width?: number
  height?: number
  className?: string
  ariaLabel?: string
}

const STROKE_PADDING = 2

function formatPoints(data: number[], width: number, height: number): string {
  if (data.length === 1) {
    // Tiny horizontal line in the middle — give it 4px of presence.
    const midY = height / 2
    const startX = width / 2 - 2
    const endX = width / 2 + 2
    return `${startX},${midY} ${endX},${midY}`
  }

  let min = data[0]
  let max = data[0]
  for (const v of data) {
    if (v < min) min = v
    if (v > max) max = v
  }
  const range = max - min
  const usableHeight = height - STROKE_PADDING * 2
  const usableWidth = width
  const stepX = data.length > 1 ? usableWidth / (data.length - 1) : 0

  return data
    .map((value, index) => {
      const x = index * stepX
      // Flat line in the middle when all values are equal.
      const normalized = range === 0 ? 0.5 : (value - min) / range
      // Invert Y: highest value sits near the top (small offset).
      const y = STROKE_PADDING + (1 - normalized) * usableHeight
      return `${x},${y}`
    })
    .join(' ')
}

export function Sparkline({
  data,
  width = 80,
  height = 24,
  className,
  ariaLabel = 'Trend',
}: SparklineProps): JSX.Element | null {
  const finite = data.filter((v) => Number.isFinite(v))
  if (finite.length === 0) {
    return null
  }

  const points = formatPoints(finite, width, height)

  return (
    <svg
      role="img"
      aria-label={ariaLabel}
      width={width}
      height={height}
      viewBox={`0 0 ${width} ${height}`}
      className={className}
    >
      <title>{ariaLabel}</title>
      <polyline
        points={points}
        fill="none"
        stroke="currentColor"
        strokeWidth={1.5}
        strokeLinecap="round"
        strokeLinejoin="round"
        vectorEffect="non-scaling-stroke"
      />
    </svg>
  )
}
