import { Skeleton } from '@/components/ui/skeleton'
import { cn } from '@/lib/utils'
import type { JSX, ReactNode } from 'react'

/**
 * KpiTile — hero KPI card for analytics dashboards.
 *
 * Layout (CSS grid, two columns 1fr/auto):
 *   Row 1: label             |  icon (16x16, muted)
 *   Row 2: value (3xl)       |  sparkline (80x24)
 *   Row 3: sub (or reserved spacer for alignment)
 *
 * Three loading modes:
 *   - loading=true             → full skeleton (label/value/sub blocks)
 *   - value === null           → value-line pulse only (label/sub render)
 *   - otherwise                → fully populated
 *
 * The sparkline slot is wrapped in `text-primary/70` so any child <Sparkline>
 * inherits the color via `currentColor`. Server-component-friendly.
 *
 * Usage:
 *   <KpiTile
 *     label="Queries (7d)"
 *     value="1,234"
 *     sub="vs prior week"
 *     icon={<MessageSquareIcon className="h-4 w-4" aria-hidden />}
 *     sparkline={<Sparkline data={[3, 5, 2, 9, 6]} />}
 *   />
 */

export interface KpiTileProps {
  label: string
  value: string | null
  sub?: string
  icon?: ReactNode
  sparkline?: ReactNode
  loading?: boolean
  className?: string
}

const CARD_BASE_CLASS =
  'rounded-lg border bg-card text-card-foreground p-5 transition-shadow hover:shadow-sm'

const LABEL_CLASS = 'text-xs font-medium uppercase tracking-wider text-muted-foreground'

const VALUE_CLASS = 'text-3xl font-semibold leading-tight tracking-tight text-foreground'

const SUB_CLASS = 'text-xs text-muted-foreground min-h-[1rem]'

export function KpiTile({
  label,
  value,
  sub,
  icon,
  sparkline,
  loading = false,
  className,
}: KpiTileProps): JSX.Element {
  if (loading) {
    return (
      <div
        className={cn(CARD_BASE_CLASS, className)}
        aria-busy="true"
        aria-live="polite"
        aria-label={label}
      >
        <div className="grid grid-cols-[1fr_auto] items-center gap-x-3">
          <Skeleton className="h-3 w-24" />
          {icon ? (
            <span aria-hidden className="text-muted-foreground">
              {icon}
            </span>
          ) : null}
        </div>
        <div className="mt-3 grid grid-cols-[1fr_auto] items-center gap-x-3">
          <Skeleton className="h-8 w-32" />
          {sparkline ? <div className="text-primary/70">{sparkline}</div> : null}
        </div>
        <div className="mt-2">
          <Skeleton className="h-3 w-16" />
        </div>
      </div>
    )
  }

  return (
    <div className={cn(CARD_BASE_CLASS, className)}>
      <div className="grid grid-cols-[1fr_auto] items-center gap-x-3">
        <p className={LABEL_CLASS}>{label}</p>
        {icon ? (
          <span aria-hidden className="text-muted-foreground">
            {icon}
          </span>
        ) : null}
      </div>

      <div className="mt-3 grid grid-cols-[1fr_auto] items-center gap-x-3">
        {value === null ? (
          <Skeleton className="h-8 w-24" aria-label="loading…" role="status" />
        ) : (
          <p className={VALUE_CLASS}>{value}</p>
        )}
        {sparkline ? <div className="text-primary/70">{sparkline}</div> : null}
      </div>

      <p className={SUB_CLASS}>{sub ?? ' '}</p>
    </div>
  )
}
