'use client'

import { SidebarNavLink } from '@/components/dashboard/SidebarNavLink'
import { useSidebar } from '@/components/dashboard/SidebarProvider'
import { Tooltip, TooltipContent, TooltipTrigger } from '@/components/ui/tooltip'
import { apiClient } from '@/lib/api-client'
import { cn } from '@/lib/utils'
import { useQuery, useQueryClient } from '@tanstack/react-query'
import {
  ChevronRightIcon,
  ListIcon,
  MessageCircleIcon,
  MessageSquareIcon,
  PlusIcon,
} from 'lucide-react'
import { usePathname } from 'next/navigation'
import { useCallback, useEffect, useMemo, useState } from 'react'
import { useSelectedSession } from './SelectedSessionContext'
import { SessionListSheet } from './SessionListSheet'
import {
  SessionDeleteDialog,
  SessionEditInput,
  SessionRowKebab,
  useSessionRowActions,
} from './SessionRowActions'
import type { Message, SessionMessagesResponse } from './types'

interface ChatSession {
  id: string
  // Nullable since U15 (lazy creation): a brand-new session may exist for
  // a few hundred ms with no title yet. The sidebar falls back to a
  // preview of the first user message in that window.
  title: string | null
  created_at: string
  updated_at: string
  message_count: number
}

/** Characters to slice off the first user message for the fallback label. */
const FALLBACK_TITLE_CHARS = 30
const FALLBACK_PLACEHOLDER = 'New chat'

/**
 * Compose the label rendered for a session row. Prefers the real title;
 * when the row was created via U15 lazy-creation and the titler hasn't yet
 * landed, falls back to the first user message read from the cached
 * messages query, truncated to a short preview.
 */
function useSessionLabel(session: ChatSession): string {
  const queryClient = useQueryClient()
  return useMemo(() => {
    if (session.title) return session.title
    const cached = queryClient.getQueryData<SessionMessagesResponse>([
      'chat-session-messages',
      session.id,
    ])
    const firstUser = cached?.messages?.find((m: Message) => m.role === 'user')
    const preview = firstUser?.content?.trim()
    if (preview) {
      return preview.length > FALLBACK_TITLE_CHARS
        ? `${preview.slice(0, FALLBACK_TITLE_CHARS).trimEnd()}…`
        : preview
    }
    return FALLBACK_PLACEHOLDER
  }, [session.id, session.title, queryClient])
}

interface SessionsResponse {
  // Backend chat-sessions envelope is `{sessions, total}` — the lone outlier
  // in our paginated APIs. See backend/src/schemas/chat.py.
  sessions: ChatSession[]
  total: number
}

interface ChatSidebarGroupProps {
  onNavigate?: () => void
}

interface SidebarSessionRowProps {
  session: ChatSession
  isActive: boolean
  onSelect: () => void
}

/**
 * Single recent-chat row in the sidebar disclosure. Owns its own
 * `useSessionRowActions` so the kebab + inline rename input are
 * fully self-contained — the parent group just hands us the session
 * and the select callback.
 *
 * The dialog is rendered alongside each row (rather than once at the
 * group level) because each row owns its own dialog-open state via the
 * shared hook. Only one can be open at a time in practice — clicking
 * Delete on row B while row A's dialog is open reuses A's state slot
 * via the kebab close, but each row is a stable component instance and
 * the dialog is portalled, so this is safe.
 */
function SidebarSessionRow({ session, isActive, onSelect }: SidebarSessionRowProps) {
  const actions = useSessionRowActions(session)
  const label = useSessionLabel(session)

  return (
    <li>
      <div
        className={cn(
          'group flex w-full items-center gap-2 rounded-md px-3 py-1.5 text-left text-xs transition-colors',
          isActive
            ? 'bg-accent text-accent-foreground'
            : 'text-muted-foreground hover:bg-accent/50 hover:text-foreground'
        )}
      >
        <MessageSquareIcon className="h-3 w-3 shrink-0 opacity-70" aria-hidden />
        {actions.isEditing ? (
          <div
            className="flex flex-1 items-center gap-1"
            onClick={(e) => e.stopPropagation()}
            onKeyDown={(e) => e.stopPropagation()}
          >
            <SessionEditInput
              initialTitle={session.title ?? ''}
              value={actions.editTitle}
              onChange={actions.setEditTitle}
              onCommit={actions.commitEdit}
              onCancel={actions.cancelEdit}
            />
          </div>
        ) : (
          <>
            <button
              type="button"
              onClick={onSelect}
              aria-current={isActive ? 'page' : undefined}
              aria-label={`Chat session: ${label}`}
              className="min-w-0 flex-1 truncate text-left"
            >
              {label}
            </button>
            <SessionRowKebab session={session} actions={actions} />
          </>
        )}
      </div>
      <SessionDeleteDialog
        open={actions.deleteOpen}
        onOpenChange={actions.setDeleteOpen}
        onConfirm={actions.confirmDelete}
        title={label}
      />
    </li>
  )
}

const STORAGE_KEY = 'ui:nav-group-chat'
const MAX_INLINE_SESSIONS = 8

function readStored(fallback: boolean): boolean {
  if (typeof window === 'undefined') return fallback
  try {
    const value = window.localStorage.getItem(STORAGE_KEY)
    if (value === '1') return true
    if (value === '0') return false
    return fallback
  } catch {
    return fallback
  }
}

function writeStored(value: boolean): void {
  if (typeof window === 'undefined') return
  try {
    window.localStorage.setItem(STORAGE_KEY, value ? '1' : '0')
  } catch {
    // ignore storage failures
  }
}

/**
 * Sidebar nav group for the user shell that:
 *
 * - Renders the "Chat" entry as a collapsible disclosure.
 * - Lists up to N most recently updated sessions inline (matches the
 *   ChatGPT/Claude.ai mental model — see design rationale in chat layout
 *   refactor).
 * - Provides a "+ New chat" affordance and an "All chats…" entry that opens
 *   the full searchable list via `<SessionListSheet>`.
 *
 * Replaces the previous dedicated 280px sessions column on `/chat`.
 */
export function ChatSidebarGroup({ onNavigate }: ChatSidebarGroupProps) {
  const pathname = usePathname()
  const { collapsed: ctxCollapsed, isMobile } = useSidebar()
  const collapsed = isMobile ? false : ctxCollapsed

  const { sessionId, setSessionId } = useSelectedSession()

  const [sheetOpen, setSheetOpen] = useState(false)
  const [userExpanded, setUserExpanded] = useState<boolean>(false)

  const onChatRoute = pathname?.startsWith('/chat') ?? false

  // Mount-only: read the persisted expanded state once. We deliberately omit
  // `onChatRoute` from the deps because it only seeds the *fallback* value
  // when no preference has been written yet — re-reading on every route
  // change would clobber a user's manual collapse.
  // biome-ignore lint/correctness/useExhaustiveDependencies: see comment above
  useEffect(() => {
    setUserExpanded(readStored(onChatRoute))
  }, [])

  const expanded = onChatRoute || userExpanded

  const toggle = useCallback(() => {
    setUserExpanded((prev) => {
      const next = !prev
      writeStored(next)
      return next
    })
  }, [])

  const { data } = useQuery({
    queryKey: ['chat-sessions'],
    queryFn: async (): Promise<SessionsResponse> => {
      const res = await apiClient.get<SessionsResponse>('/api/v1/chat/sessions?limit=100')
      return res.data
    },
    staleTime: 15_000,
    refetchOnWindowFocus: true,
  })

  const sessions = useMemo(() => {
    const items = data?.sessions ?? []
    return [...items]
      .sort((a, b) => (a.updated_at < b.updated_at ? 1 : -1))
      .slice(0, MAX_INLINE_SESSIONS)
  }, [data])

  const totalSessions = data?.total ?? 0
  const hasMore = totalSessions > MAX_INLINE_SESSIONS

  // U15 lazy creation: the "+" button no longer fires `POST /sessions`.
  // It just clears any active selection so the URL lands on `/chat`,
  // where the empty-hero composer is ready to accept the first message.
  // The actual session row is created server-side when the user sends.
  const handleNewChat = useCallback(() => {
    setSessionId(null, { replace: true })
    onNavigate?.()
  }, [setSessionId, onNavigate])

  const handleSelect = useCallback(
    (id: string) => {
      // `setSessionId` is now URL-driven and will navigate to `/chat/<id>`
      // from any route in the user shell — no manual `router.push('/chat')`
      // needed.
      setSessionId(id)
      onNavigate?.()
    },
    [setSessionId, onNavigate]
  )

  const openAllChats = useCallback(() => {
    setSheetOpen(true)
  }, [])

  // --- Collapsed sidebar: tooltip on the parent icon, no inline children ---
  if (collapsed) {
    return (
      <>
        <SidebarNavLink href="/chat" label="Chat" icon={MessageCircleIcon} collapsed />
        <Tooltip delayDuration={0}>
          <TooltipTrigger asChild>
            <button
              type="button"
              aria-label="All chats"
              aria-current={onChatRoute ? 'page' : undefined}
              onClick={openAllChats}
              className={cn(
                'relative mx-auto flex h-9 w-9 items-center justify-center rounded-md transition-colors',
                onChatRoute
                  ? 'bg-accent text-accent-foreground before:absolute before:left-0 before:top-1/2 before:h-5 before:w-0.5 before:-translate-y-1/2 before:rounded-r-full before:bg-primary'
                  : 'text-muted-foreground hover:bg-accent/50 hover:text-foreground'
              )}
            >
              <ListIcon className={cn('h-4 w-4', onChatRoute && 'text-primary')} aria-hidden />
            </button>
          </TooltipTrigger>
          <TooltipContent side="right">All chats (Ctrl+\)</TooltipContent>
        </Tooltip>
        <SessionListSheet open={sheetOpen} onOpenChange={setSheetOpen} />
      </>
    )
  }

  // --- Expanded sidebar: disclosure with inline recent sessions ---
  // The disclosure header is a row of independently-focusable controls — a
  // <button> nested inside another <button> is invalid HTML and breaks
  // keyboard navigation/screen readers. The toggle wraps the icon+label and
  // the chevron only; the "+" sits beside it as a sibling.
  return (
    <div className="space-y-1">
      <div
        className={cn(
          'flex w-full items-center gap-1 rounded-md pr-1 text-sm font-medium transition-colors',
          onChatRoute
            ? 'text-foreground'
            : 'text-muted-foreground hover:bg-accent/50 hover:text-foreground'
        )}
      >
        <button
          type="button"
          aria-expanded={expanded}
          aria-controls="nav-group-chat"
          onClick={toggle}
          className="flex flex-1 items-center gap-2.5 rounded-md px-3 py-2.5 text-left"
        >
          <MessageCircleIcon
            className={cn('h-4 w-4 shrink-0', onChatRoute && 'text-primary')}
            aria-hidden
          />
          <span className="flex-1 truncate">Chat</span>
          <ChevronRightIcon
            className={cn(
              'h-3.5 w-3.5 shrink-0 text-muted-foreground transition-transform',
              expanded && 'rotate-90'
            )}
            aria-hidden
          />
        </button>
        <button
          type="button"
          aria-label="New chat"
          onClick={handleNewChat}
          // 44x44 hit target on mobile per WCAG 2.5.5; condenses to 24x24
          // visually on desktop where pointer precision is higher.
          className="flex h-11 w-11 items-center justify-center rounded-md text-muted-foreground hover:bg-accent hover:text-foreground md:h-6 md:w-6"
        >
          <PlusIcon className="h-3.5 w-3.5" aria-hidden />
        </button>
      </div>

      {expanded ? (
        <div id="nav-group-chat" className="ml-3 space-y-0.5 border-l border-border/60 pl-2">
          {sessions.length === 0 ? (
            <p className="px-3 py-2 text-xs text-muted-foreground">
              No chats yet. Click + to start.
            </p>
          ) : (
            <ul className="space-y-0.5">
              {sessions.map((session) => (
                <SidebarSessionRow
                  key={session.id}
                  session={session}
                  isActive={session.id === sessionId && onChatRoute}
                  onSelect={() => handleSelect(session.id)}
                />
              ))}
            </ul>
          )}

          <button
            type="button"
            onClick={openAllChats}
            className="mt-1 flex w-full items-center justify-between gap-2 rounded-md px-3 py-1.5 text-xs text-muted-foreground transition-colors hover:bg-accent/50 hover:text-foreground"
          >
            <span className="inline-flex items-center gap-2">
              <ListIcon className="h-3 w-3" aria-hidden />
              {hasMore ? `All chats (${totalSessions})` : 'All chats'}
            </span>
            <kbd className="rounded border border-border bg-muted px-1 py-0.5 text-[10px] font-medium text-muted-foreground">
              Ctrl \
            </kbd>
          </button>
        </div>
      ) : null}

      <SessionListSheet open={sheetOpen} onOpenChange={setSheetOpen} />
    </div>
  )
}
