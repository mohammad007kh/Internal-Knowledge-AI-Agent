'use client'
import { Button } from '@/components/ui/button'
import { Input } from '@/components/ui/input'
import { ScrollArea } from '@/components/ui/scroll-area'
import { apiClient } from '@/lib/api-client'
import { cn } from '@/lib/utils'
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { MessageSquareIcon, PlusIcon, SearchIcon } from 'lucide-react'
import { useState } from 'react'
import { toast } from 'sonner'
import { useSelectedSession } from './SelectedSessionContext'
import {
  SessionDeleteDialog,
  SessionEditInput,
  SessionRowKebab,
  useSessionRowActions,
} from './SessionRowActions'

interface ChatSession {
  id: string
  title: string
  created_at: string
  updated_at: string
  message_count: number
}

interface SessionsResponse {
  items: ChatSession[]
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
}

interface SessionItemProps {
  session: ChatSession
  isActive: boolean
  onSelect: () => void
}

/**
 * One row in the All-chats list. Uses the shared `useSessionRowActions`
 * hook for rename + delete state so the UX matches `<ChatSidebarGroup>`
 * exactly (kebab → Popover menu → AlertDialog confirm).
 */
function SessionItem({ session, isActive, onSelect }: SessionItemProps) {
  const actions = useSessionRowActions(session)
  return (
    <li>
      <div
        className={cn(
          'group flex items-center gap-1.5 rounded-md px-2 py-1.5 text-sm',
          'cursor-pointer select-none',
          isActive ? 'bg-accent text-accent-foreground' : 'hover:bg-muted text-foreground'
        )}
        onClick={() => {
          if (!actions.isEditing) onSelect()
        }}
        aria-current={isActive ? 'page' : undefined}
        role="button"
        tabIndex={0}
        aria-label={`Chat session: ${session.title}`}
        onKeyDown={(e) => {
          if (e.key === 'Enter' && !actions.isEditing) onSelect()
        }}
      >
        <MessageSquareIcon
          className="h-3.5 w-3.5 shrink-0 text-muted-foreground"
          aria-hidden="true"
        />
        {actions.isEditing ? (
          <div
            className="flex flex-1 items-center gap-1"
            onClick={(e) => e.stopPropagation()}
            onKeyDown={(e) => e.stopPropagation()}
          >
            <SessionEditInput
              initialTitle={session.title}
              value={actions.editTitle}
              onChange={actions.setEditTitle}
              onCommit={actions.commitEdit}
              onCancel={actions.cancelEdit}
            />
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
            <SessionRowKebab session={session} actions={actions} />
          </>
        )}
      </div>
      <SessionDeleteDialog
        open={actions.deleteOpen}
        onOpenChange={actions.setDeleteOpen}
        onConfirm={actions.confirmDelete}
        title={session.title}
      />
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
  const { sessionId, setSessionId } = useSelectedSession()
  const queryClient = useQueryClient()

  const [search, setSearch] = useState('')

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
    },
    onError: () => toast.error('Failed to create session.'),
  })

  const sessions: ChatSession[] = data?.items ?? []
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
                onSelect={() => {
                  setSessionId(session.id)
                  onSelect?.(session.id)
                }}
              />
            ))}
          </ul>
        )}
      </ScrollArea>
    </div>
  )
}
