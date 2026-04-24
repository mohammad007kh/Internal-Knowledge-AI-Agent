'use client'

import { Tooltip, TooltipContent, TooltipTrigger } from '@/components/ui/tooltip'
import { cn } from '@/lib/utils'
import { PanelLeftCloseIcon, PanelLeftOpenIcon } from 'lucide-react'
import { useSidebar } from './SidebarProvider'

export interface SidebarToggleButtonProps {
  className?: string
}

/** Desktop-only collapse/expand button. Hidden on mobile (sheet has its own close). */
export function SidebarToggleButton({ className }: SidebarToggleButtonProps) {
  const { collapsed, toggle, isMobile } = useSidebar()
  if (isMobile) return null

  const Icon = collapsed ? PanelLeftOpenIcon : PanelLeftCloseIcon
  const label = collapsed ? 'Expand sidebar' : 'Collapse sidebar'

  return (
    <Tooltip delayDuration={250}>
      <TooltipTrigger asChild>
        <button
          type="button"
          onClick={toggle}
          aria-label={label}
          aria-expanded={!collapsed}
          className={cn(
            'inline-flex h-8 w-8 items-center justify-center rounded-md text-muted-foreground transition-colors hover:bg-accent hover:text-foreground focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring',
            className
          )}
        >
          <Icon className="h-4 w-4" aria-hidden />
        </button>
      </TooltipTrigger>
      <TooltipContent side="right">{label} (Ctrl/Cmd+B)</TooltipContent>
    </Tooltip>
  )
}
