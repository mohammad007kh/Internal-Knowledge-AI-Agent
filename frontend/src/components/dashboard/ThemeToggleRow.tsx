'use client'

import { ThemeToggle } from '@/components/theme-toggle'
import { useSidebar } from './SidebarProvider'

export function ThemeToggleRow() {
  const { collapsed, isMobile } = useSidebar()
  const isCollapsed = !isMobile && collapsed

  if (isCollapsed) {
    return (
      <div className="flex items-center justify-center px-1">
        <ThemeToggle />
      </div>
    )
  }

  return (
    <div className="flex items-center justify-between px-1">
      <span className="text-xs text-muted-foreground">Theme</span>
      <ThemeToggle />
    </div>
  )
}
