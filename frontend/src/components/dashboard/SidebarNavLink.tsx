'use client'

import { Tooltip, TooltipContent, TooltipTrigger } from '@/components/ui/tooltip'
import { cn } from '@/lib/utils'
import Link from 'next/link'
import { usePathname } from 'next/navigation'
import { useSidebar } from './SidebarProvider'
import { type IconType, isActivePath } from './nav-config'

export interface SidebarNavLinkProps {
  href: string
  label: string
  icon: IconType
  /**
   * Force collapsed/expanded rendering. When omitted the desktop collapsed
   * flag from `useSidebar()` is used (mobile sheet always renders expanded).
   */
  collapsed?: boolean
  onNavigate?: () => void
}

export function SidebarNavLink({
  href,
  label,
  icon: Icon,
  collapsed: collapsedOverride,
  onNavigate,
}: SidebarNavLinkProps) {
  const pathname = usePathname()
  const { collapsed: ctxCollapsed, isMobile } = useSidebar()
  const collapsed = collapsedOverride ?? (isMobile ? false : ctxCollapsed)
  const active = isActivePath(pathname, href)

  const expandedLink = (
    <Link
      href={href}
      onClick={onNavigate}
      aria-current={active ? 'page' : undefined}
      className={cn(
        'relative flex items-center gap-2.5 rounded-md px-3 py-2.5 text-sm font-medium transition-colors',
        active
          ? 'bg-accent text-accent-foreground before:absolute before:left-0 before:top-1/2 before:h-5 before:w-0.5 before:-translate-y-1/2 before:rounded-r-full before:bg-primary'
          : 'text-muted-foreground hover:bg-accent/50 hover:text-foreground'
      )}
    >
      <Icon className={cn('h-4 w-4 shrink-0', active && 'text-primary')} aria-hidden />
      <span className="truncate">{label}</span>
    </Link>
  )

  if (!collapsed) {
    return expandedLink
  }

  const collapsedLink = (
    <Link
      href={href}
      onClick={onNavigate}
      aria-label={label}
      aria-current={active ? 'page' : undefined}
      className={cn(
        'relative mx-auto flex h-9 w-9 items-center justify-center rounded-md transition-colors',
        active
          ? 'bg-accent text-accent-foreground before:absolute before:left-0 before:top-1/2 before:h-5 before:w-0.5 before:-translate-y-1/2 before:rounded-r-full before:bg-primary'
          : 'text-muted-foreground hover:bg-accent/50 hover:text-foreground'
      )}
    >
      <Icon className={cn('h-4 w-4', active && 'text-primary')} aria-hidden />
    </Link>
  )

  return (
    <Tooltip delayDuration={0}>
      <TooltipTrigger asChild>{collapsedLink}</TooltipTrigger>
      <TooltipContent side="right">{label}</TooltipContent>
    </Tooltip>
  )
}
