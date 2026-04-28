'use client'

import { Button } from '@/components/ui/button'
import { Sheet, SheetContent, SheetTitle } from '@/components/ui/sheet'
import { apiClient } from '@/lib/api-client'
import { useMutation, useQueryClient } from '@tanstack/react-query'
import { PlusIcon } from 'lucide-react'
import { useEffect } from 'react'
import { toast } from 'sonner'
import { useSelectedSession } from './SelectedSessionContext'
import { SessionList } from './SessionList'

interface CreatedSession {
  id: string
  title: string
}

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
  const queryClient = useQueryClient()

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

  const createMutation = useMutation({
    mutationFn: async (): Promise<CreatedSession> => {
      const res = await apiClient.post<CreatedSession>('/api/v1/chat/sessions', {
        title: 'New chat',
      })
      return res.data
    },
    onSuccess: (session) => {
      queryClient.invalidateQueries({ queryKey: ['chat-sessions'] })
      setSessionId(session.id)
      onOpenChange(false)
    },
    onError: () => toast.error('Failed to create session.'),
  })

  return (
    <Sheet open={open} onOpenChange={onOpenChange}>
      <SheetContent side="left" className="w-80 max-w-[85vw] p-0">
        <div className="flex h-full flex-col">
          {/* Visible header — replaces the previous sr-only title so users
              can see the panel context and discover the primary CTA. The
              right-side "X" close button is rendered by SheetContent. */}
          <div className="flex items-center justify-between border-b border-border px-4 py-3 pr-12">
            <SheetTitle className="text-base">Chats</SheetTitle>
            <Button
              size="sm"
              variant="default"
              className="gap-1.5"
              disabled={createMutation.isPending}
              onClick={() => createMutation.mutate()}
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
