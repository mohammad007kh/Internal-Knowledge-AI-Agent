'use client'

import { useEffect, useRef } from 'react'

/**
 * Hand-rolled canvas chart hooks for the analytics dashboard.
 *
 * Siblings to `@/hooks/useBarChart` — same zero-dependency approach (a `useRef`
 * onto a `<canvas>`, drawn in a `useEffect`). No charting npm package.
 *
 * All hooks:
 *  - clear + redraw on data/option changes;
 *  - read colors from explicit hex (passed by the caller, which resolves them
 *    from CSS-var-friendly Tailwind palette literals — canvas can't read CSS
 *    custom properties so we pass concrete hex);
 *  - leave responsive sizing to the caller (`className="w-full"` on the canvas
 *    + a fixed `width`/`height` attribute pair for the drawing buffer).
 */

const PADDING = { top: 16, right: 12, bottom: 28, left: 40 } as const
const GRID_FRACTIONS = [0.25, 0.5, 0.75, 1.0] as const
const AXIS_COLOR = '#6b7280'
const GRID_COLOR = '#e5e7eb'
const LABEL_FONT = '10px system-ui'

interface ChartGeom {
  width: number
  height: number
  chartW: number
  chartH: number
}

function geom(canvas: HTMLCanvasElement): ChartGeom {
  const { width, height } = canvas
  return {
    width,
    height,
    chartW: width - PADDING.left - PADDING.right,
    chartH: height - PADDING.top - PADDING.bottom,
  }
}

function drawYGrid(ctx: CanvasRenderingContext2D, g: ChartGeom, maxVal: number): void {
  ctx.font = LABEL_FONT
  ctx.textAlign = 'right'
  ctx.textBaseline = 'middle'
  ctx.fillStyle = AXIS_COLOR
  ctx.strokeStyle = GRID_COLOR
  ctx.lineWidth = 1
  for (const frac of GRID_FRACTIONS) {
    const y = PADDING.top + g.chartH * (1 - frac)
    ctx.beginPath()
    ctx.moveTo(PADDING.left, y)
    ctx.lineTo(PADDING.left + g.chartW, y)
    ctx.stroke()
    ctx.fillText(String(Math.round(maxVal * frac)), PADDING.left - 4, y)
  }
}

function drawXLabels(ctx: CanvasRenderingContext2D, g: ChartGeom, labels: readonly string[]): void {
  if (labels.length === 0) return
  ctx.font = LABEL_FONT
  ctx.textAlign = 'center'
  ctx.textBaseline = 'top'
  ctx.fillStyle = AXIS_COLOR
  const step = g.chartW / labels.length
  // Show at most ~7 labels to avoid overlap; pick an even stride.
  const stride = Math.max(1, Math.ceil(labels.length / 7))
  labels.forEach((label, i) => {
    if (i % stride !== 0) return
    const x = PADDING.left + i * step + step / 2
    ctx.fillText(label, x, PADDING.top + g.chartH + 4)
  })
}

/** A short `MM-DD` label from an ISO `YYYY-MM-DD` date string. */
export function shortDay(isoDate: string): string {
  // Slice the `MM-DD` tail; fall back to the raw value if unexpected.
  return isoDate.length >= 10 ? isoDate.slice(5, 10) : isoDate
}

// ---------------------------------------------------------------------------
// Area / line chart (single series)
// ---------------------------------------------------------------------------

export interface AreaPoint {
  label: string
  value: number
}

export function useAreaChart(data: readonly AreaPoint[], stroke = '#6366f1', fill = 'rgba(99,102,241,0.15)') {
  const canvasRef = useRef<HTMLCanvasElement>(null)
  useEffect(() => {
    const canvas = canvasRef.current
    if (!canvas) return
    const ctx = canvas.getContext('2d')
    if (!ctx) return
    const g = geom(canvas)
    ctx.clearRect(0, 0, g.width, g.height)
    if (data.length === 0) return

    const maxVal = Math.max(...data.map((d) => d.value), 1)
    drawYGrid(ctx, g, maxVal)

    const stepX = data.length > 1 ? g.chartW / (data.length - 1) : 0
    const xAt = (i: number) => (data.length > 1 ? PADDING.left + i * stepX : PADDING.left + g.chartW / 2)
    const yAt = (v: number) => PADDING.top + g.chartH - (v / maxVal) * g.chartH

    // Fill area.
    ctx.beginPath()
    ctx.moveTo(xAt(0), PADDING.top + g.chartH)
    data.forEach((d, i) => ctx.lineTo(xAt(i), yAt(d.value)))
    ctx.lineTo(xAt(data.length - 1), PADDING.top + g.chartH)
    ctx.closePath()
    ctx.fillStyle = fill
    ctx.fill()

    // Stroke line — or, with a single data point (e.g. a 24h range that
    // returned only today), a dot, so the chart isn't blank.
    if (data.length === 1) {
      ctx.beginPath()
      ctx.arc(xAt(0), yAt(data[0]!.value), 3.5, 0, Math.PI * 2)
      ctx.fillStyle = stroke
      ctx.fill()
    } else {
      ctx.beginPath()
      data.forEach((d, i) => (i === 0 ? ctx.moveTo(xAt(i), yAt(d.value)) : ctx.lineTo(xAt(i), yAt(d.value))))
      ctx.strokeStyle = stroke
      ctx.lineWidth = 2
      ctx.lineJoin = 'round'
      ctx.stroke()
    }

    drawXLabels(ctx, g, data.map((d) => d.label))
  }, [data, stroke, fill])
  return canvasRef
}

// ---------------------------------------------------------------------------
// Stacked bar chart (N segments per bar)
// ---------------------------------------------------------------------------

export interface StackedBar {
  label: string
  /** Segment values in draw order (bottom → top). */
  segments: readonly number[]
}

export function useStackedBarChart(data: readonly StackedBar[], colors: readonly string[]) {
  const canvasRef = useRef<HTMLCanvasElement>(null)
  useEffect(() => {
    const canvas = canvasRef.current
    if (!canvas) return
    const ctx = canvas.getContext('2d')
    if (!ctx) return
    const g = geom(canvas)
    ctx.clearRect(0, 0, g.width, g.height)
    if (data.length === 0) return

    const totals = data.map((d) => d.segments.reduce((s, v) => s + v, 0))
    const maxVal = Math.max(...totals, 1)
    drawYGrid(ctx, g, maxVal)

    const barWidth = g.chartW / data.length
    data.forEach((d, i) => {
      const x = PADDING.left + i * barWidth + barWidth * 0.12
      const w = barWidth * 0.76
      let cursorY = PADDING.top + g.chartH
      d.segments.forEach((value, segIdx) => {
        if (value <= 0) return
        const h = (value / maxVal) * g.chartH
        cursorY -= h
        ctx.fillStyle = colors[segIdx % colors.length] ?? '#9ca3af'
        ctx.fillRect(x, cursorY, w, h)
      })
    })

    drawXLabels(ctx, g, data.map((d) => d.label))
  }, [data, colors])
  return canvasRef
}

// ---------------------------------------------------------------------------
// Grouped/stacked bars + an overlay line on a secondary scale
// ---------------------------------------------------------------------------

export interface BarsWithOverlayBar {
  label: string
  /** Stacked bar segments (bottom → top), e.g. [success, failed]. */
  segments: readonly number[]
  /** Value on the secondary (right) axis, drawn as a line. */
  overlay: number
}

export function useBarsWithOverlay(
  data: readonly BarsWithOverlayBar[],
  barColors: readonly string[],
  overlayColor = '#0ea5e9'
) {
  const canvasRef = useRef<HTMLCanvasElement>(null)
  useEffect(() => {
    const canvas = canvasRef.current
    if (!canvas) return
    const ctx = canvas.getContext('2d')
    if (!ctx) return
    const g = geom(canvas)
    ctx.clearRect(0, 0, g.width, g.height)
    if (data.length === 0) return

    const barTotals = data.map((d) => d.segments.reduce((s, v) => s + v, 0))
    const maxBar = Math.max(...barTotals, 1)
    const maxOverlay = Math.max(...data.map((d) => d.overlay), 1)
    drawYGrid(ctx, g, maxBar)

    const barWidth = g.chartW / data.length
    data.forEach((d, i) => {
      const x = PADDING.left + i * barWidth + barWidth * 0.12
      const w = barWidth * 0.76
      let cursorY = PADDING.top + g.chartH
      d.segments.forEach((value, segIdx) => {
        if (value <= 0) return
        const h = (value / maxBar) * g.chartH
        cursorY -= h
        ctx.fillStyle = barColors[segIdx % barColors.length] ?? '#9ca3af'
        ctx.fillRect(x, cursorY, w, h)
      })
    })

    // Overlay line on the secondary scale.
    const cx = (i: number) => PADDING.left + i * barWidth + barWidth / 2
    const cy = (v: number) => PADDING.top + g.chartH - (v / maxOverlay) * g.chartH
    ctx.beginPath()
    data.forEach((d, i) => (i === 0 ? ctx.moveTo(cx(i), cy(d.overlay)) : ctx.lineTo(cx(i), cy(d.overlay))))
    ctx.strokeStyle = overlayColor
    ctx.lineWidth = 2
    ctx.lineJoin = 'round'
    ctx.stroke()
    // Right-axis ticks for the overlay scale.
    ctx.font = LABEL_FONT
    ctx.textAlign = 'left'
    ctx.textBaseline = 'middle'
    ctx.fillStyle = overlayColor
    for (const frac of GRID_FRACTIONS) {
      const y = PADDING.top + g.chartH * (1 - frac)
      ctx.fillText(String(Math.round(maxOverlay * frac)), PADDING.left + g.chartW + 2, y)
    }

    drawXLabels(ctx, g, data.map((d) => d.label))
  }, [data, barColors, overlayColor])
  return canvasRef
}
