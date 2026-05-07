'use client'

/**
 * Shared per-row Rename / Delete affordances for chat-session lists.
 *
 * Exposes a single source of truth for:
 *  - the rename + delete mutations (with `['chat-sessions']` invalidation)
 *  - inline edit state (isEditing, editTitle, startEdit, commitEdit, cancelEdit)
 *  - kebab menu open state
 *  - delete-confirmation dialog state
 *
 * Consumed by both `<SessionList>` (the "All chats" sheet) and
 * `<ChatSidebarGroup>` (sidebar recent-chats list) so the UX stays
 * identical across surfaces — three-dots kebab → Popover with Rename
 * and Delete menuitems, AlertDialog confirm for destructive deletes.
 *
 * No new dependencies: built on the existing `@radix-ui/react-popover`
 * and `@radix-ui/react-alert-dialog` primitives that are already
 * vendored under `@/components/ui/*`.
 */
import {
  AlertDialog,
  AlertDialogAction,
  AlertDialogCancel,
  AlertDialogContent,
  AlertDialogDescription,
  AlertDialogFooter,
  AlertDialogHeader,
  AlertDialogTitle,
} from '@/components/ui/alert-dialog'
import { Button } from '@/components/ui/button'
import { Input } from '@/components/ui/input'
import { Popover, PopoverContent, PopoverTrigger } from '@/components/ui/popover'
import { apiClient } from '@/lib/api-client'
import { cn } from '@/lib/utils'
import { useMutation, useQueryClient } from '@tanstack/react-query'
import { MoreHorizontalIcon, PencilIcon, Trash2Icon } from 'lucide-react'
import { useCallback, useEffect, useRef, useState } from 'react'
import { toast } from 'sonner'
import { useSelectedSession } from './SelectedSessionContext'

export interface ChatSessionLike {
  id: string
  title: string
}

const sessionsApi = {
  rename: async (id: string, title: string): Promise<void> => {
    await apiClient.patch(`/api/v1/chat/sessions/${id}`, { title })
  },
  delete: async (id: string): Promise<void> => {
    await apiClient.delete(`/api/v1/chat/sessions/${id}`)
  },
}

export interface SessionRowActions {
  // Edit state
  isEditing: boolean
  editTitle: string
  setEditTitle: (next: string) => void
  startEdit: () => void
  commitEdit: () => void
  cancelEdit: () => void

  // Menu state
  menuOpen: boolean
  setMenuOpen: (next: boolean) => void

  // Delete-confirm state
  deleteOpen: boolean
  setDeleteOpen: (next: boolean) => void
  confirmDelete: () => void

  // Mutation flags (useful for disabling controls)
  isRenaming: boolean
  isDeleting: boolean
}

/**
 * Per-row actions hook. Owns rename + delete mutations and all the
 * transient UI state (inline edit, menu open, delete dialog open).
 *
 * Cancels any in-flight chat stream bound to the active session before
 * clearing the selection on delete so no stale tokens arrive after the
 * session is gone. Skips redundant PATCH calls when the rename input
 * is empty or unchanged.
 */
export function useSessionRowActions(session: ChatSessionLike): SessionRowActions {
  const queryClient = useQueryClient()
  const { sessionId, setSessionId, abortStream } = useSelectedSession()

  const [isEditing, setIsEditing] = useState(false)
  const [editTitle, setEditTitle] = useState(session.title)
  const [menuOpen, setMenuOpen] = useState(false)
  const [deleteOpen, setDeleteOpen] = useState(false)

  const renameMutation = useMutation({
    mutationFn: ({ id, title }: { id: string; title: string }) => sessionsApi.rename(id, title),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ['chat-sessions'] })
      setIsEditing(false)
    },
    onError: () => toast.error('Failed to rename session.'),
  })

  const deleteMutation = useMutation({
    mutationFn: (id: string) => sessionsApi.delete(id),
    onSuccess: (_, deletedId) => {
      queryClient.invalidateQueries({ queryKey: ['chat-sessions'] })
      if (sessionId === deletedId) {
        // Cancel any in-flight stream before clearing the selection so
        // no stale tokens or completion events arrive after the session
        // is gone.
        abortStream()
        setSessionId(null)
      }
      setDeleteOpen(false)
      toast.success('Session deleted.')
    },
    onError: () => toast.error('Failed to delete session.'),
  })

  const startEdit = useCallback(() => {
    setEditTitle(session.title)
    setIsEditing(true)
  }, [session.title])

  const commitEdit = useCallback(() => {
    const trimmed = editTitle.trim()
    // Empty input → silent revert. Unchanged title → no-op (don't burn
    // an API call for a no-op rename).
    if (!trimmed || trimmed === session.title.trim()) {
      setIsEditing(false)
      return
    }
    renameMutation.mutate({ id: session.id, title: trimmed })
  }, [editTitle, renameMutation, session.id, session.title])

  const cancelEdit = useCallback(() => {
    setIsEditing(false)
  }, [])

  const confirmDelete = useCallback(() => {
    deleteMutation.mutate(session.id)
  }, [deleteMutation, session.id])

  return {
    isEditing,
    editTitle,
    setEditTitle,
    startEdit,
    commitEdit,
    cancelEdit,
    menuOpen,
    setMenuOpen,
    deleteOpen,
    setDeleteOpen,
    confirmDelete,
    isRenaming: renameMutation.isPending,
    isDeleting: deleteMutation.isPending,
  }
}

interface SessionEditInputProps {
  initialTitle: string
  value: string
  onChange: (next: string) => void
  onCommit: () => void
  onCancel: () => void
  /** Optional className override for the input element. */
  className?: string
}

/**
 * Inline rename input. Auto-focuses + selects the existing title on mount
 * (Claude.ai/ChatGPT pattern) so users can immediately type to replace.
 *
 * Commit policy: Enter or blur-with-changes commits. Escape or
 * blur-without-changes (or empty input) cancels.
 *
 * Focus is grabbed across rAF + microtask + setTimeout because the
 * Popover trigger that opened this editor restores focus to itself when
 * it closes — we need to land *after* Radix finishes its return-focus
 * cycle. jsdom doesn't reliably run rAF, hence the setTimeout fallback.
 */
export function SessionEditInput({
  initialTitle,
  value,
  onChange,
  onCommit,
  onCancel,
  className,
}: SessionEditInputProps) {
  const inputRef = useRef<HTMLInputElement>(null)

  useEffect(() => {
    const el = inputRef.current
    if (!el) return
    const grab = () => {
      el.focus()
      el.select()
    }
    grab()
    const raf = window.requestAnimationFrame(grab)
    const t = window.setTimeout(grab, 0)
    return () => {
      window.cancelAnimationFrame(raf)
      window.clearTimeout(t)
    }
  }, [])

  const handleBlur = () => {
    if (value.trim() === initialTitle.trim() || !value.trim()) {
      onCancel()
      return
    }
    onCommit()
  }

  return (
    <Input
      ref={inputRef}
      value={value}
      onChange={(e) => onChange(e.target.value)}
      onBlur={handleBlur}
      className={cn('h-6 flex-1 px-1.5 text-xs', className)}
      maxLength={100}
      onKeyDown={(e) => {
        if (e.key === 'Enter') {
          e.preventDefault()
          onCommit()
        }
        if (e.key === 'Escape') {
          e.preventDefault()
          onCancel()
        }
      }}
      aria-label="Rename session"
    />
  )
}

interface SessionRowKebabProps {
  session: ChatSessionLike
  actions: SessionRowActions
  /**
   * Container className override. Defaults to a hover-only wrapper that
   * is always visible on mobile (where hover is unreliable) and on
   * desktop while the menu is open.
   */
  className?: string
}

/**
 * The hover-revealed three-dots kebab + Popover menu (Rename / Delete).
 *
 * Visibility model:
 *  - Mobile (`<md`): always visible (hover-on-touch is unreliable).
 *  - Desktop (`>=md`): hidden by default, revealed on row hover or focus,
 *    and pinned visible while the menu is open so users don't lose the
 *    trigger mid-interaction.
 *
 * The wrapper stops propagation so kebab clicks don't bubble up to a
 * row-level click handler that would navigate to the chat.
 */
export function SessionRowKebab({ session, actions, className }: SessionRowKebabProps) {
  const { menuOpen, setMenuOpen, startEdit, setDeleteOpen } = actions
  return (
    <div
      className={cn(
        'ml-1 shrink-0 items-center md:group-hover:flex md:focus-within:flex',
        menuOpen ? 'flex' : 'flex md:hidden',
        className
      )}
      onClick={(e) => e.stopPropagation()}
      onKeyDown={(e) => e.stopPropagation()}
    >
      <Popover open={menuOpen} onOpenChange={setMenuOpen}>
        <PopoverTrigger asChild>
          <Button
            size="icon"
            variant="ghost"
            className="h-5 w-5"
            aria-label={`Open menu: ${session.title}`}
            aria-haspopup="menu"
          >
            <MoreHorizontalIcon className="h-3.5 w-3.5" />
          </Button>
        </PopoverTrigger>
        <PopoverContent align="end" side="bottom" sideOffset={4} className="w-36 p-1" role="menu">
          <button
            type="button"
            role="menuitem"
            aria-label={`Rename: ${session.title}`}
            onClick={() => {
              setMenuOpen(false)
              startEdit()
            }}
            className="flex w-full items-center gap-2 rounded-sm px-2 py-1.5 text-xs text-foreground hover:bg-accent hover:text-accent-foreground focus:bg-accent focus:outline-none"
          >
            <PencilIcon className="h-3 w-3" aria-hidden />
            Rename
          </button>
          <button
            type="button"
            role="menuitem"
            aria-label={`Delete: ${session.title}`}
            onClick={() => {
              setMenuOpen(false)
              setDeleteOpen(true)
            }}
            className="flex w-full items-center gap-2 rounded-sm px-2 py-1.5 text-xs text-destructive hover:bg-destructive/10 focus:bg-destructive/10 focus:outline-none"
          >
            <Trash2Icon className="h-3 w-3" aria-hidden />
            Delete
          </button>
        </PopoverContent>
      </Popover>
    </div>
  )
}

interface SessionDeleteDialogProps {
  open: boolean
  onOpenChange: (next: boolean) => void
  onConfirm: () => void
  /** Reserved for future use — kept for API symmetry with the kebab. */
  title?: string
}

/**
 * Destructive-confirm dialog for deleting a session. Identical copy to
 * what was previously inlined in SessionList — extracted here so both
 * the sheet and the sidebar group can share it. The `title` prop is
 * intentionally not surfaced in the body copy yet to preserve test
 * compatibility; we can iterate later if we want per-row title echo.
 */
export function SessionDeleteDialog({ open, onOpenChange, onConfirm }: SessionDeleteDialogProps) {
  return (
    <AlertDialog open={open} onOpenChange={onOpenChange}>
      <AlertDialogContent>
        <AlertDialogHeader>
          <AlertDialogTitle>Delete session?</AlertDialogTitle>
          <AlertDialogDescription>
            All messages in this session will be permanently deleted. This action cannot be undone.
          </AlertDialogDescription>
        </AlertDialogHeader>
        <AlertDialogFooter>
          <AlertDialogCancel>Cancel</AlertDialogCancel>
          <AlertDialogAction
            onClick={onConfirm}
            className="bg-destructive text-destructive-foreground hover:bg-destructive/90"
          >
            Delete
          </AlertDialogAction>
        </AlertDialogFooter>
      </AlertDialogContent>
    </AlertDialog>
  )
}
