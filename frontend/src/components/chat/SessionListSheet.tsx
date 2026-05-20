'use client'

import { Button } from '@/components/ui/button'
import { Sheet, SheetContent, SheetDescription, SheetTitle } from '@/components/ui/sheet'
import { PlusIcon } from 'lucide-react'
import { useEffect } from 'react'
import { useSelectedSession } from './SelectedSessionContext'
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
  const { setSessionId } = useSelectedSession()

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

  // U15 lazy creation: the "New chat" CTA no longer fires POST /sessions.
  // It just clears the active session so the URL is `/chat`, where the
  // empty-hero composer kicks in — the row is only persisted once the
  // user sends their first message.
  const handleNewChat = () => {
    setSessionId(null, { replace: true })
    onOpenChange(false)
  }

  return (
    <Sheet open={open} onOpenChange={onOpenChange}>
      <SheetContent side="left" className="w-80 max-w-[85vw] p-0">
        <div className="flex h-full flex-col">
          {/* Visible header — replaces the previous sr-only title so users
              can see the panel context and discover the primary CTA. The
              right-side "X" close button is rendered by SheetContent. */}
          <div className="flex items-center justify-between border-b border-border px-4 py-3 pr-12">
            <SheetTitle className="text-base">Chats</SheetTitle>
            {/* Required by Radix Dialog a11y contract — without it the
                primitive logs `Missing Description or aria-describedby` to
                the console. The list itself conveys the panel's purpose
                visually so we hide the description from sighted users. */}
            <SheetDescription className="sr-only">
              Browse, search, rename, and delete your chat sessions.
            </SheetDescription>
            <Button
              size="sm"
              variant="default"
              className="gap-1.5"
              onClick={handleNewChat}
            >
              <PlusIcon className="h-3.5 w-3.5" aria-hidden />
              New chat
            </Button>
          </div>
          <div className="flex-1 overflow-hidden">
            <SessionList onSelect={() => onOpenChange(false)} />
          </div>
        </div>
      </SheetContent>
    </Sheet>
  )
}
