'use client'

import { Sheet, SheetContent, SheetTitle } from '@/components/ui/sheet'
import { useEffect } from 'react'
import { SessionList } from './SessionList'

export interface SessionListSheetProps {
  open: boolean
  onOpenChange: (next: boolean) => void
}

/**
 * Slide-over panel that surfaces the full SessionList (search, rename, delete)
 * on demand. Triggered from the sidebar "All chats" entry or the global
 * `Ctrl/Cmd+\` shortcut. Reuses the existing `<SessionList>` so a single
 * source of truth handles create/rename/delete/search behaviour.
 */
export function SessionListSheet({ open, onOpenChange }: SessionListSheetProps) {
  useEffect(() => {
    const handler = (event: KeyboardEvent) => {
      const isModifier = event.metaKey || event.ctrlKey
      if (!isModifier) return
      if (event.key !== '\\') return

      const target = event.target as HTMLElement | null
      const tag = target?.tagName
      const isEditable =
        target?.isContentEditable || tag === 'INPUT' || tag === 'TEXTAREA' || tag === 'SELECT'
      if (isEditable) return

      event.preventDefault()
      onOpenChange(!open)
    }
    window.addEventListener('keydown', handler)
    return () => window.removeEventListener('keydown', handler)
  }, [open, onOpenChange])

  return (
    <Sheet open={open} onOpenChange={onOpenChange}>
      <SheetContent side="left" className="w-80 max-w-[85vw] p-0">
        <SheetTitle className="sr-only">All chat sessions</SheetTitle>
        <div className="flex h-full flex-col">
          <SessionList onSelect={() => onOpenChange(false)} />
        </div>
      </SheetContent>
    </Sheet>
  )
}
