'use client'

import { cn } from '@/lib/utils'
import { useSidebar } from './SidebarProvider'

export interface SidebarSectionProps {
  label: string
  className?: string
  /** Render as a thin divider when collapsed (mobile sheet ignores collapsed). */
  collapsedAsDivider?: boolean
}

export function SidebarSection({
  label,
  className,
  collapsedAsDivider = true,
}: SidebarSectionProps) {
  const { collapsed, isMobile } = useSidebar()
  const isCollapsed = !isMobile && collapsed

  if (isCollapsed) {
    if (!collapsedAsDivider) return null
    return <div className="my-2 border-t border-border" aria-hidden />
  }

  return (
    <div
      className={cn(
        'px-3 pb-1 pt-3 text-xs font-semibold uppercase tracking-wider text-muted-foreground',
        className
      )}
    >
      {label}
    </div>
  )
}
