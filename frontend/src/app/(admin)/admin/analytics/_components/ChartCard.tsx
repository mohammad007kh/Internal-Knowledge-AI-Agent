import { cn } from '@/lib/utils'
import type { ReactNode } from 'react'

/**
 * ChartCard — shared card shell for the analytics dashboard panels.
 *
 * Border + `bg-card` + a header row with `title` on the left and optional
 * `actions` on the right (e.g. a "Configure →" link or a big rolling
 * percentage). Body is whatever you pass as children.
 *
 * Mirrors the `QueryVolumeChart` wrapper but reusable across all panels.
 */

export interface ChartCardProps {
  title: ReactNode
  actions?: ReactNode
  /** Optional subtitle / caption shown under the title. */
  subtitle?: ReactNode
  children: ReactNode
  className?: string
  /** Body padding override; defaults to none (children control it). */
  bodyClassName?: string
}

export function ChartCard({
  title,
  actions,
  subtitle,
  children,
  className,
  bodyClassName,
}: ChartCardProps) {
  return (
    <section className={cn('rounded-lg border bg-card text-card-foreground', className)}>
      <header className="flex items-start justify-between gap-3 border-b px-4 py-3">
        <div className="min-w-0">
          <h2 className="truncate text-sm font-semibold">{title}</h2>
          {subtitle ? (
            <p className="mt-0.5 text-xs text-muted-foreground">{subtitle}</p>
          ) : null}
        </div>
        {actions ? <div className="shrink-0 text-sm">{actions}</div> : null}
      </header>
      <div className={cn('p-4', bodyClassName)}>{children}</div>
    </section>
  )
}
