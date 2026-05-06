'use client'
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
import { ScrollArea } from '@/components/ui/scroll-area'
import { apiClient } from '@/lib/api-client'
import { cn } from '@/lib/utils'
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import {
  CheckIcon,
  MessageSquareIcon,
  PencilIcon,
  PlusIcon,
  SearchIcon,
  Trash2Icon,
  XIcon,
} from 'lucide-react'
import { useCallback, useState } from 'react'
import { toast } from 'sonner'
import { useSelectedSession } from './SelectedSessionContext'

interface ChatSession {
  id: string
  title: string
  created_at: string
  updated_at: string
  message_count: number
}

interface SessionsResponse {
  // Backend returns `{sessions, total}` for chat sessions (the only paginated
  // envelope in the project that doesn't use `items` — see
  // backend/src/schemas/chat.py::ChatSessionListResponse). Match the wire
  // shape exactly; reading `items` here was silently empty.
  sessions: ChatSession[]
  total: number
}

const sessionsApi = {
  list: async (): Promise<SessionsResponse> => {
    const res = await apiClient.get<SessionsResponse>('/api/v1/chat/sessions?limit=100')
    return res.data
  },
  create: async (title: string): Promise<ChatSession> => {
    const res = await apiClient.post<ChatSession>('/api/v1/chat/sessions', { title })
    return res.data
  },
  rename: async (id: string, title: string): Promise<ChatSession> => {
    const res = await apiClient.patch<ChatSession>(`/api/v1/chat/sessions/${id}`, { title })
    return res.data
  },
  delete: async (id: string): Promise<void> => {
    await apiClient.delete(`/api/v1/chat/sessions/${id}`)
  },
}

interface SessionItemProps {
  session: ChatSession
  isActive: boolean
  isEditing: boolean
  editTitle: string
  onSelect: () => void
  onStartEdit: () => void
  onEditChange: (v: string) => void
  onCommitEdit: () => void
  onCancelEdit: () => void
  onDelete: () => void
}

function SessionItem({
  session,
  isActive,
  isEditing,
  editTitle,
  onSelect,
  onStartEdit,
  onEditChange,
  onCommitEdit,
  onCancelEdit,
  onDelete,
}: SessionItemProps) {
  return (
    <li>
      <div
        className={cn(
          'group flex items-center gap-1.5 rounded-md px-2 py-1.5 text-sm',
          'cursor-pointer select-none',
          isActive ? 'bg-accent text-accent-foreground' : 'hover:bg-muted text-foreground'
        )}
        onClick={() => {
          if (!isEditing) onSelect()
        }}
        aria-current={isActive ? 'page' : undefined}
        role="button"
        tabIndex={0}
        aria-label={`Chat session: ${session.title}`}
        onKeyDown={(e) => {
          if (e.key === 'Enter' && !isEditing) onSelect()
        }}
      >
        <MessageSquareIcon
          className="h-3.5 w-3.5 shrink-0 text-muted-foreground"
          aria-hidden="true"
        />
        {isEditing ? (
          <div
            className="flex flex-1 items-center gap-1"
            onClick={(e) => e.stopPropagation()}
            onKeyDown={(e) => e.stopPropagation()}
          >
            <Input
              value={editTitle}
              onChange={(e) => onEditChange(e.target.value)}
              className="h-6 flex-1 px-1.5 text-xs"
              autoFocus
              maxLength={100}
              onKeyDown={(e) => {
                if (e.key === 'Enter') onCommitEdit()
                if (e.key === 'Escape') onCancelEdit()
              }}
              aria-label="Rename session"
            />
            <Button
              size="icon"
              variant="ghost"
              className="h-5 w-5 shrink-0"
              onClick={onCommitEdit}
              aria-label="Confirm rename"
            >
              <CheckIcon className="h-3 w-3" />
            </Button>
            <Button
              size="icon"
              variant="ghost"
              className="h-5 w-5 shrink-0"
              onClick={onCancelEdit}
              aria-label="Cancel rename"
            >
              <XIcon className="h-3 w-3" />
            </Button>
          </div>
        ) : (
          <>
            <span className="flex-1 truncate text-xs">{session.title}</span>
            {session.message_count > 0 && (
              <span
                className="ml-auto shrink-0 rounded-full bg-muted px-1.5 py-0.5 text-[10px] text-muted-foreground"
                aria-label={`${session.message_count} messages`}
              >
                {session.message_count}
              </span>
            )}
            <div
              className="ml-1 hidden shrink-0 items-center gap-0.5 group-hover:flex"
              onClick={(e) => e.stopPropagation()}
              onKeyDown={(e) => e.stopPropagation()}
            >
              <Button
                size="icon"
                variant="ghost"
                className="h-5 w-5"
                onClick={onStartEdit}
                aria-label={`Rename: ${session.title}`}
              >
                <PencilIcon className="h-3 w-3" />
              </Button>
              <Button
                size="icon"
                variant="ghost"
                className="h-5 w-5 text-destructive hover:bg-destructive/10"
                onClick={onDelete}
                aria-label={`Delete: ${session.title}`}
              >
                <Trash2Icon className="h-3 w-3" />
              </Button>
            </div>
          </>
        )}
      </div>
    </li>
  )
}

export interface SessionListProps {
  /**
   * Optional callback fired after a session is selected (clicked in the list).
   * Used by `<SessionListSheet>` to close the slide-over once the user picks
   * a chat. Not invoked when a new session is created via the "+" button —
   * that path keeps focus on the rename input.
   */
  onSelect?: (sessionId: string) => void
}

export function SessionList({ onSelect }: SessionListProps = {}) {
  const { sessionId, setSessionId, abortStream } = useSelectedSession()
  const queryClient = useQueryClient()

  const [search, setSearch] = useState('')
  const [editingId, setEditingId] = useState<string | null>(null)
  const [editTitle, setEditTitle] = useState('')
  const [deletingId, setDeletingId] = useState<string | null>(null)

  const { data, isLoading } = useQuery({
    queryKey: ['chat-sessions'],
    queryFn: sessionsApi.list,
    staleTime: 15_000,
    refetchOnWindowFocus: true,
  })

  const createMutation = useMutation({
    mutationFn: () => sessionsApi.create('New chat'),
    onSuccess: (session) => {
      queryClient.invalidateQueries({ queryKey: ['chat-sessions'] })
      setSessionId(session.id)
      setEditingId(session.id)
      setEditTitle(session.title)
    },
    onError: () => toast.error('Failed to create session.'),
  })

  const renameMutation = useMutation({
    mutationFn: ({ id, title }: { id: string; title: string }) => sessionsApi.rename(id, title),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ['chat-sessions'] })
      setEditingId(null)
    },
    onError: () => toast.error('Failed to rename session.'),
  })

  const deleteMutation = useMutation({
    mutationFn: (id: string) => sessionsApi.delete(id),
    onSuccess: (_, deletedId) => {
      queryClient.invalidateQueries({ queryKey: ['chat-sessions'] })
      if (sessionId === deletedId) {
        // Cancel any in-flight stream bound to the session we just deleted
        // before clearing the selection so no stale tokens or completion
        // events arrive after the session is gone.
        abortStream()
        setSessionId(null)
      }
      setDeletingId(null)
      toast.success('Session deleted.')
    },
    onError: () => toast.error('Failed to delete session.'),
  })

  const startEdit = useCallback((session: ChatSession) => {
    setEditingId(session.id)
    setEditTitle(session.title)
  }, [])

  const commitEdit = useCallback(
    (id: string) => {
      const trimmed = editTitle.trim()
      if (!trimmed) {
        setEditingId(null)
        return
      }
      renameMutation.mutate({ id, title: trimmed })
    },
    [editTitle, renameMutation]
  )

  const cancelEdit = useCallback(() => setEditingId(null), [])

  const sessions: ChatSession[] = data?.sessions ?? []
  const filtered = search.trim()
    ? sessions.filter((s) => s.title.toLowerCase().includes(search.toLowerCase()))
    : sessions

  return (
    <div className="flex h-full flex-col">
      <div className="flex items-center justify-between border-b border-border px-3 py-2">
        <h2 className="text-xs font-semibold uppercase tracking-wide text-muted-foreground">
          Sessions
        </h2>
        <Button
          size="icon"
          variant="ghost"
          className="h-6 w-6"
          aria-label="New chat session"
          disabled={createMutation.isPending}
          onClick={() => createMutation.mutate()}
        >
          <PlusIcon className="h-3.5 w-3.5" />
        </Button>
      </div>
      <div className="relative px-2 py-1.5">
        <SearchIcon
          className="absolute left-4 top-1/2 h-3.5 w-3.5 -translate-y-1/2 text-muted-foreground"
          aria-hidden="true"
        />
        <Input
          aria-label="Search sessions"
          placeholder="Search sessions…"
          className="h-8 pl-8 text-xs"
          value={search}
          onChange={(e) => setSearch(e.target.value)}
        />
      </div>
      <ScrollArea className="flex-1">
        {isLoading ? (
          ['sk-0', 'sk-1', 'sk-2', 'sk-3', 'sk-4'].map((skKey) => (
            <div
              key={skKey}
              className="h-9 w-full animate-pulse rounded-md bg-muted"
              aria-hidden="true"
            />
          ))
        ) : filtered.length === 0 ? (
          <div className="flex flex-col items-center gap-2 px-4 py-8 text-center text-xs text-muted-foreground">
            <MessageSquareIcon className="h-6 w-6 opacity-40" aria-hidden="true" />
            <span>
              {search.trim()
                ? 'No sessions match your search.'
                : 'No sessions yet. Start a new chat.'}
            </span>
          </div>
        ) : (
          <ul>
            {filtered.map((session) => (
              <SessionItem
                key={session.id}
                session={session}
                isActive={session.id === sessionId}
                isEditing={editingId === session.id}
                editTitle={editTitle}
                onSelect={() => {
                  setSessionId(session.id)
                  onSelect?.(session.id)
                }}
                onStartEdit={() => startEdit(session)}
                onEditChange={setEditTitle}
                onCommitEdit={() => commitEdit(session.id)}
                onCancelEdit={cancelEdit}
                onDelete={() => setDeletingId(session.id)}
              />
            ))}
          </ul>
        )}
      </ScrollArea>
      <AlertDialog open={!!deletingId} onOpenChange={(o) => !o && setDeletingId(null)}>
        <AlertDialogContent>
          <AlertDialogHeader>
            <AlertDialogTitle>Delete session?</AlertDialogTitle>
            <AlertDialogDescription>
              All messages in this session will be permanently deleted. This action cannot be
              undone.
            </AlertDialogDescription>
          </AlertDialogHeader>
          <AlertDialogFooter>
            <AlertDialogCancel>Cancel</AlertDialogCancel>
            <AlertDialogAction
              onClick={() => deletingId && deleteMutation.mutate(deletingId)}
              className="bg-destructive text-destructive-foreground hover:bg-destructive/90"
            >
              Delete
            </AlertDialogAction>
          </AlertDialogFooter>
        </AlertDialogContent>
      </AlertDialog>
    </div>
  )
}
