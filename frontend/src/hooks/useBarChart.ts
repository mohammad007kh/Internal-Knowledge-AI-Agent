import { useEffect, useRef } from 'react'

export interface BarData {
  label: string
  value: number
}

const PADDING = { top: 16, right: 8, bottom: 32, left: 40 } as const
const DEFAULT_COLOR = '#6366f1'

export function useBarChart(data: BarData[], color = DEFAULT_COLOR) {
  const canvasRef = useRef<HTMLCanvasElement>(null)

  useEffect(() => {
    const canvas = canvasRef.current
    if (!canvas) return
    const ctx = canvas.getContext('2d')
    if (!ctx) return

    const { width, height } = canvas
    const chartW = width - PADDING.left - PADDING.right
    const chartH = height - PADDING.top - PADDING.bottom

    ctx.clearRect(0, 0, width, height)

    if (data.length === 0) return

    const maxVal = Math.max(...data.map((d) => d.value), 1)

    // Gridlines at 0.25, 0.5, 0.75, 1.0 fractions
    ctx.font = '10px system-ui'
    ctx.textAlign = 'right'
    ctx.textBaseline = 'middle'
    ctx.fillStyle = '#6b7280'
    ctx.strokeStyle = '#e5e7eb'
    ctx.lineWidth = 1

    for (const frac of [0.25, 0.5, 0.75, 1.0]) {
      const y = PADDING.top + chartH * (1 - frac)
      ctx.beginPath()
      ctx.moveTo(PADDING.left, y)
      ctx.lineTo(PADDING.left + chartW, y)
      ctx.stroke()
      ctx.fillText(String(Math.round(maxVal * frac)), PADDING.left - 4, y)
    }

    // Bars
    const barWidth = chartW / data.length
    ctx.fillStyle = color

    data.forEach((d, i) => {
      const barH = (d.value / maxVal) * chartH
      const x = PADDING.left + i * barWidth + barWidth * 0.1
      const y = PADDING.top + chartH - barH
      ctx.fillRect(x, y, barWidth * 0.8, barH)
    })

    // X-axis labels (every other, slice first 5 chars of label)
    ctx.textAlign = 'center'
    ctx.textBaseline = 'top'
    ctx.fillStyle = '#6b7280'

    data.forEach((d, i) => {
      if (i % 2 !== 0) return
      const x = PADDING.left + i * barWidth + barWidth / 2
      const y = PADDING.top + chartH + 4
      ctx.fillText(d.label.slice(5), x, y)
    })
  }, [data, color])

  return canvasRef
}
