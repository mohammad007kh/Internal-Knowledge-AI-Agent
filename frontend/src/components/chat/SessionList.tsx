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
  AlertDialogTrigger,
} from '@/components/ui/alert-dialog'
import { Button } from '@/components/ui/button'
import { ScrollArea } from '@/components/ui/scroll-area'
import { apiClient } from '@/lib/api-client'
import { cn } from '@/lib/utils'
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { PlusIcon, Trash2Icon } from 'lucide-react'
import { useCallback } from 'react'
import { toast } from 'sonner'
import { useSelectedSession } from './SelectedSessionContext'

interface ChatSession {
  id: string
  title: string
  updated_at: string
  message_count: number
}

interface ChatSessionListResponse {
  items: ChatSession[]
  total: number
  limit: number
  offset: number
}

const SESSIONS_QUERY_KEY = ['chat-sessions']

async function fetchSessions(): Promise<ChatSessionListResponse> {
  const res = await apiClient.get('/chat/sessions?limit=50&offset=0')
  return res.data
}

async function createSession(): Promise<ChatSession> {
  const res = await apiClient.post('/chat/sessions', {
    title: 'New Chat',
    source_ids: [],
  })
  return res.data
}

async function deleteSession(sessionId: string): Promise<void> {
  await apiClient.delete(`/chat/sessions/${sessionId}`)
}

export function SessionList() {
  const { sessionId, setSessionId } = useSelectedSession()
  const queryClient = useQueryClient()

  const { data, isLoading } = useQuery({
    queryKey: SESSIONS_QUERY_KEY,
    queryFn: fetchSessions,
    staleTime: 30_000,
  })

  const createMutation = useMutation({
    mutationFn: createSession,
    onSuccess: (newSession) => {
      queryClient.invalidateQueries({ queryKey: SESSIONS_QUERY_KEY })
      setSessionId(newSession.id)
    },
    onError: () => toast.error('Failed to create session.'),
  })

  const deleteMutation = useMutation({
    mutationFn: deleteSession,
    onSuccess: (_data, deletedId) => {
      queryClient.invalidateQueries({ queryKey: SESSIONS_QUERY_KEY })
      if (sessionId === deletedId) setSessionId(null)
    },
    onError: () => toast.error('Failed to delete session.'),
  })

  const handleNewChat = useCallback(() => {
    createMutation.mutate()
  }, [createMutation])

  const sessions: ChatSession[] = data?.items ?? []

  return (
    <div className="flex h-full flex-col">
      <div className="flex items-center justify-between border-b border-border px-4 py-3">
        <h2 className="text-sm font-semibold text-muted-foreground uppercase tracking-wide">
          Sessions
        </h2>
        <Button
          size="sm"
          variant="ghost"
          aria-label="New chat"
          onClick={handleNewChat}
          disabled={createMutation.isPending}
        >
          <PlusIcon className="h-4 w-4" />
        </Button>
      </div>
      <ScrollArea className="flex-1">
        {isLoading ? (
          <div className="p-4 text-sm text-muted-foreground">Loading…</div>
        ) : sessions.length === 0 ? (
          <div className="p-4 text-sm text-muted-foreground">
            No sessions yet. Click + to start.
          </div>
        ) : (
          <ul className="py-1">
            {sessions.map((s) => (
              <SessionItem
                key={s.id}
                session={s}
                isActive={s.id === sessionId}
                onSelect={() => setSessionId(s.id)}
                onDelete={() => deleteMutation.mutate(s.id)}
                isDeleting={deleteMutation.isPending && deleteMutation.variables === s.id}
              />
            ))}
          </ul>
        )}
      </ScrollArea>
    </div>
  )
}

interface SessionItemProps {
  session: ChatSession
  isActive: boolean
  onSelect: () => void
  onDelete: () => void
  isDeleting: boolean
}

function SessionItem({ session, isActive, onSelect, onDelete, isDeleting }: SessionItemProps) {
  return (
    <li
      className={cn(
        'group flex items-center mx-1 rounded-sm hover:bg-accent',
        isActive && 'bg-accent'
      )}
    >
      <button
        type="button"
        className="flex flex-1 min-w-0 items-center gap-2 px-3 py-2 cursor-pointer"
        onClick={onSelect}
        aria-current={isActive ? 'page' : undefined}
      >
        <span className="flex-1 truncate text-sm text-left">{session.title}</span>
        <span className="text-xs text-muted-foreground shrink-0">{session.message_count}</span>
      </button>
      <AlertDialog>
        <AlertDialogTrigger asChild>
          <Button
            size="icon"
            variant="ghost"
            className="h-6 w-6 shrink-0 opacity-0 group-hover:opacity-100 focus:opacity-100 mr-1"
            aria-label={`Delete session: ${session.title}`}
            disabled={isDeleting}
          >
            <Trash2Icon className="h-3.5 w-3.5" />
          </Button>
        </AlertDialogTrigger>
        <AlertDialogContent>
          <AlertDialogHeader>
            <AlertDialogTitle>Delete session?</AlertDialogTitle>
            <AlertDialogDescription>
              This will permanently delete &ldquo;{session.title}&rdquo; and all its messages. This
              action cannot be undone.
            </AlertDialogDescription>
          </AlertDialogHeader>
          <AlertDialogFooter>
            <AlertDialogCancel onClick={(e) => e.stopPropagation()}>Cancel</AlertDialogCancel>
            <AlertDialogAction
              onClick={(e) => {
                e.stopPropagation()
                onDelete()
              }}
              className="bg-destructive text-destructive-foreground hover:bg-destructive/90"
            >
              Delete
            </AlertDialogAction>
          </AlertDialogFooter>
        </AlertDialogContent>
      </AlertDialog>
    </li>
  )
}
