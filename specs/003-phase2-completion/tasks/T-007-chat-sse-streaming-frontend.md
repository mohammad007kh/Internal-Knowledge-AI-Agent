# T-007: Chat SSE Streaming + Message Thread

**Status**: Not Started
**Created**: 2026-04-21
**User Story**: US-2
**Requirement**: FR-014, FR-015, FR-019, FR-020
**Priority**: P0
**Feature**: Phase 2 — Product Completion (Internal Knowledge AI Agent)
**Branch**: `003-phase2-completion`
**Platform**: Web (Next.js 15 App Router frontend)

---

## 📋 Embedded Context

### Feature Summary
Phase 2 closes the gap between the current working skeleton and the full product vision. This task implements the interactive chat experience: real-time SSE token streaming, a session sidebar with rename/delete, a source selector for scoping queries, and a chat input with send/stop controls. Streaming is delivered via `fetch()` + `ReadableStream` so the frontend can include the Bearer JWT on a POST request (EventSource supports only GET without custom headers and is therefore unusable).

### Registry Standards (Project Defaults — Locked)
| Key | Value |
|-----|-------|
| `architecture.pattern` | modular_monolith |
| `architecture.layers` | clean |
| `frontend.framework` | nextjs (v15, App Router) |
| `frontend.ui_library` | shadcn/ui |
| `frontend.styling` | tailwind (v4) |
| `frontend.state_management` | context + TanStack Query |
| `frontend.data_fetching` | tanstack-query |
| `frontend.form_library` | react-hook-form |
| `frontend.validation_library` | zod |
| `frontend.routing` | next-router (App Router) |
| `ui_specs.icons` | lucide-react |
| `ui_specs.notifications` | sonner |
| `ui_specs.dark_mode` | true |
| `ui_specs.responsive` | true |
| `ui_specs.accessibility` | wcag-aa |
| `conventions.files` | kebab-case (Next.js components) |
| `conventions.classes` | PascalCase |
| `backend.sse_pattern` | fetch() + ReadableStream (NOT EventSource — EventSource is GET-only, cannot send JWT) |
| `api.versioning` | /api/v1/ |
| `api.auth_header` | bearer (Authorization: Bearer <token>) |

### Domain Rules (frontend-developer + typescript-pro)
- All API calls go through `apiClient` in `src/lib/api-client.ts` — never use raw `fetch` or axios directly in components
- **Exception**: SSE streaming must use vanilla `fetch()` (or a thin wrapper) to access `response.body.getReader()`; Bearer token MUST still be attached manually via an auth header helper
- Define typed API functions in `src/lib/api/` directory
- TanStack Query for ALL server state — never store server data in `useState`
- Use `useQuery` and `useMutation` for all API interactions (SSE is orchestrated via a custom hook + `useMutation`'s `mutationFn`)
- SSE streaming uses `fetch()` with `ReadableStream` — NOT `EventSource`
- Forms use React Hook Form + Zod schema validation
- All new pages use shadcn/ui components
- Accessibility: all interactive elements need proper `aria-label` or visible label

### API Contracts
```
GET /api/v1/chat/sessions
  Response: { items: Session[], total, limit, offset }

POST /api/v1/chat/sessions
  Body: { title?: string, source_ids?: string[] }
  Response 201: { id, title, created_at }

PATCH /api/v1/chat/sessions/{id}
  Body: { title: string }
  Response: Session

DELETE /api/v1/chat/sessions/{id}
  Response 204

GET /api/v1/chat/sessions/{id}/messages
  Response: { items: Message[], total }

POST /api/v1/chat/sessions/{id}/messages
  Body: { content: string, source_ids?: string[] }
  Response: text/event-stream
  SSE Events:
    - token      → { delta: string }
    - citations  → { items: Citation[] }
    - clarification_needed → { question: string }
    - guardrail_blocked    → { message: string }
    - done       → { message_id: string, is_partial: boolean }
    - error      → { error: string }

GET /api/v1/users/me/sources (or GET /api/v1/sources)
  Response: { items: Source[] }
```

### Gate Criteria
- TypeScript strict mode compiles without new errors
- `useChatStream` abort correctly cancels the fetch request and marks message `is_partial`
- Tokens render progressively (no buffering until `done`)
- Session sidebar correctly renders title + last message preview + relative timestamp
- Source selector persists to session on first message
- Stop button replaces Send button during streaming and triggers abort
- Character counter appears only at 2000+ chars
- WCAG AA: input labeled, streaming status announced via `aria-live="polite"`

---

## 🎯 Objective

Implement the complete interactive chat surface: users can create sessions, select scoping sources, send a message, watch tokens stream in real-time, stop generation mid-stream, and manage past sessions from a sidebar. The SSE event loop handles `token`, `citations`, `clarification_needed`, `guardrail_blocked`, `done`, and `error` events — the latter three are rendered by T-008 but surfaced by this hook.

---

## 🛠️ Implementation Details

### Files to Create

1. **`frontend/src/lib/api/chat.ts`** — Typed API functions
   ```typescript
   import { apiClient } from '@/lib/api-client'

   export interface Session {
     id: string
     title: string
     source_ids: string[]
     created_at: string
     updated_at: string
     last_message_preview?: string
   }

   export interface Message {
     id: string
     session_id: string
     role: 'user' | 'assistant'
     content: string
     citations?: Citation[]
     is_partial?: boolean
     created_at: string
   }

   export interface Citation {
     index: number
     source_id: string
     source_name: string
     excerpt: string
     page?: number
   }

   export interface CreateSessionInput {
     title?: string
     source_ids?: string[]
   }

   export async function getSessions(): Promise<Session[]> {
     const r = await apiClient.get<{ items: Session[] }>('/api/v1/chat/sessions')
     return r.items
   }

   export async function createSession(data: CreateSessionInput): Promise<Session> {
     return apiClient.post('/api/v1/chat/sessions', data)
   }

   export async function renameSession(id: string, title: string): Promise<Session> {
     return apiClient.patch(`/api/v1/chat/sessions/${id}`, { title })
   }

   export async function deleteSession(id: string): Promise<void> {
     return apiClient.delete(`/api/v1/chat/sessions/${id}`)
   }

   export async function getMessages(sessionId: string): Promise<Message[]> {
     const r = await apiClient.get<{ items: Message[] }>(
       `/api/v1/chat/sessions/${sessionId}/messages`
     )
     return r.items
   }

   /**
    * Opens an SSE stream by POSTing to the messages endpoint.
    * Must use vanilla fetch() because EventSource cannot send POST bodies or custom headers.
    * Returns the raw Response — caller is responsible for draining response.body.
    */
   export async function openMessageStream(
     sessionId: string,
     content: string,
     sourceIds: string[],
     signal: AbortSignal,
     getAuthToken: () => string | null
   ): Promise<Response> {
     const token = getAuthToken()
     const response = await fetch(
       `/api/v1/chat/sessions/${sessionId}/messages`,
       {
         method: 'POST',
         headers: {
           'Content-Type': 'application/json',
           Accept: 'text/event-stream',
           ...(token ? { Authorization: `Bearer ${token}` } : {})
         },
         body: JSON.stringify({ content, source_ids: sourceIds }),
         signal
       }
     )
     if (!response.ok) throw new Error(`Stream request failed: ${response.status}`)
     if (!response.body) throw new Error('Response body is null')
     return response
   }
   ```

2. **`frontend/src/hooks/useChatStream.ts`** — Custom hook managing SSE connection
   ```typescript
   import { useState, useRef, useCallback } from 'react'
   import { openMessageStream, Citation } from '@/lib/api/chat'
   import { getAuthToken } from '@/lib/auth' // existing helper

   type StreamEvent =
     | { type: 'token'; delta: string }
     | { type: 'citations'; items: Citation[] }
     | { type: 'clarification_needed'; question: string }
     | { type: 'guardrail_blocked'; message: string }
     | { type: 'done'; message_id: string; is_partial: boolean }
     | { type: 'error'; error: string }

   export interface ChatStreamState {
     tokens: string          // accumulated streamed text
     citations: Citation[]
     isStreaming: boolean
     clarificationQuestion: string | null
     guardrailMessage: string | null
     error: string | null
     isPartial: boolean
   }

   export function useChatStream() {
     const [state, setState] = useState<ChatStreamState>({
       tokens: '', citations: [], isStreaming: false,
       clarificationQuestion: null, guardrailMessage: null,
       error: null, isPartial: false
     })
     const controllerRef = useRef<AbortController | null>(null)

     const send = useCallback(async (
       sessionId: string, content: string, sourceIds: string[]
     ) => {
       controllerRef.current?.abort()
       const controller = new AbortController()
       controllerRef.current = controller

       setState({
         tokens: '', citations: [], isStreaming: true,
         clarificationQuestion: null, guardrailMessage: null,
         error: null, isPartial: false
       })

       try {
         const response = await openMessageStream(
           sessionId, content, sourceIds, controller.signal, getAuthToken
         )
         const reader = response.body!.getReader()
         const decoder = new TextDecoder()
         let buffer = ''

         while (true) {
           const { done, value } = await reader.read()
           if (done) break
           buffer += decoder.decode(value, { stream: true })
           const events = buffer.split('\n\n')
           buffer = events.pop() ?? ''
           for (const raw of events) {
             const evt = parseSseEvent(raw)
             if (!evt) continue
             applyEvent(evt, setState)
           }
         }
       } catch (err) {
         if ((err as Error).name === 'AbortError') {
           setState(s => ({ ...s, isStreaming: false, isPartial: true }))
         } else {
           setState(s => ({
             ...s, isStreaming: false,
             error: (err as Error).message
           }))
         }
       } finally {
         setState(s => ({ ...s, isStreaming: false }))
       }
     }, [])

     const abort = useCallback(() => {
       controllerRef.current?.abort()
     }, [])

     return { ...state, send, abort }
   }

   function parseSseEvent(raw: string): StreamEvent | null {
     const lines = raw.split('\n')
     let eventType = 'message'
     let dataStr = ''
     for (const line of lines) {
       if (line.startsWith('event:')) eventType = line.slice(6).trim()
       else if (line.startsWith('data:')) dataStr += line.slice(5).trim()
     }
     if (!dataStr) return null
     try {
       const data = JSON.parse(dataStr)
       return { type: eventType as StreamEvent['type'], ...data } as StreamEvent
     } catch {
       return null
     }
   }

   function applyEvent(
     evt: StreamEvent,
     setState: React.Dispatch<React.SetStateAction<ChatStreamState>>
   ) {
     switch (evt.type) {
       case 'token':
         setState(s => ({ ...s, tokens: s.tokens + evt.delta }))
         break
       case 'citations':
         setState(s => ({ ...s, citations: evt.items }))
         break
       case 'clarification_needed':
         setState(s => ({ ...s, clarificationQuestion: evt.question, isStreaming: false }))
         break
       case 'guardrail_blocked':
         setState(s => ({ ...s, guardrailMessage: evt.message, isStreaming: false }))
         break
       case 'done':
         setState(s => ({ ...s, isStreaming: false, isPartial: evt.is_partial }))
         break
       case 'error':
         setState(s => ({ ...s, error: evt.error, isStreaming: false }))
         break
     }
   }
   ```

### Files to Update

3. **`frontend/src/components/chat/MessageThread.tsx`** — Full streaming display
   - Render list of past messages + the currently-streaming assistant message
   - User messages: right-aligned bubble, `bg-primary text-primary-foreground`
   - Assistant messages: left-aligned, `bg-muted`
   - While streaming: append `tokens` from `useChatStream` to a synthetic assistant message
   - Show blinking cursor glyph (`▋` or a span with `animate-pulse`) at end of streamed text while `isStreaming`
   - Auto-scroll to bottom on new token; detect user scroll-up (compare `scrollTop` against previous) and disable auto-scroll until user scrolls to bottom again
   - Skeleton loader (shadcn Skeleton component) for first ~400ms after send, before the first `token` arrives
   - Accept prop: `streamState: ChatStreamState` (or consume hook internally if thread owns the streaming)
   - Render T-008 components (CitationPanel, ClarificationCard, GuardrailCard) — those files are owned by T-008; this file imports and places them

4. **`frontend/src/components/chat/SessionList.tsx`** — Sidebar
   - `useQuery(['chat', 'sessions'], getSessions)` for session list
   - Sort client-side by `updated_at` desc
   - Each row: title (truncate-ellipsis), `last_message_preview` truncated to 60 chars, relative time (e.g., `date-fns` `formatDistanceToNow`)
   - "New Chat" button at top — opens `createSession` mutation with no args, then `router.push('/chat/[new-id]')`
   - Hover reveals a shadcn `DropdownMenu` trigger (3-dots icon) with Rename and Delete
   - Rename: inline edit using a Dialog with Input + confirm button
   - Delete: shadcn AlertDialog confirmation
   - `useMutation` for rename/delete with `queryClient.invalidateQueries({ queryKey: ['chat', 'sessions'] })`
   - If >50 sessions: infinite scroll using TanStack Query `useInfiniteQuery`; otherwise load all in one page

5. **`frontend/src/components/chat/ChatInputBar.tsx`** — Composer (create if it doesn't exist at this exact path; reuse existing name otherwise)
   - Auto-resizing `<Textarea>` (max 5 rows, default 1 row); use `onInput` to adjust height via `style.height = 'auto'; style.height = scrollHeight + 'px'`
   - Enter → send; Shift+Enter → newline
   - Send button (shadcn Button, lucide `Send` icon)
   - While `isStreaming`: Send button is replaced by a Stop button (lucide `Square` icon, `variant="destructive"`) that calls `abort()` from `useChatStream`
   - Character counter rendered below input when `content.length >= 2000`: e.g., `2134 / 8000` in `text-xs text-muted-foreground`
   - Disabled state: empty content, or `isStreaming` and send button specifically
   - Props: `{ isStreaming: boolean, onSend: (content: string) => void, onStop: () => void }`

6. **`frontend/src/components/chat/SourceSelector.tsx`** — Multi-select dropdown
   - `useQuery(['sources'], getAccessibleSources)` — list of user-accessible sources
   - Use shadcn `Popover` + `Command` multi-select combobox pattern
   - Each option: source type icon (match T-006 icon map: Database/FileText/Globe/Plug) + name + small type label
   - Default state: no selection → label reads "All accessible sources"
   - When any selected: label reads "N sources selected"
   - On first message after selection: session's `source_ids` is updated via `createSession` or patch
   - Props: `{ value: string[], onChange: (ids: string[]) => void, disabled?: boolean }`

### Code / Logic Requirements

- **SSE parsing**: correctly handle chunks that split mid-event (buffer until `\n\n`)
- **AbortController lifecycle**: one controller per send; always abort prior in-flight stream when a new send starts
- **is_partial**: when user aborts, backend sets `is_partial = true` on the persisted message; frontend reflects this visually (italic "[aborted]" marker after the streamed text)
- **Immutability**: state updates always return new objects; never mutate arrays in place (use spread)
- **Error surfacing**: `error` event + fetch failures → `sonner` `toast.error`
- **Memoization**: memoize the message list rendering via `React.memo` + stable keys; streaming text is a separate component so the past messages don't re-render on every token
- **Performance**: debounce auto-scroll to ~60fps (`requestAnimationFrame`)
- **File size**: keep each component under 300 lines; extract helpers if needed

---

## 🔌 Wiring Checklist (Web)

- [ ] `useChatStream` imported by `MessageThread.tsx` (or by the chat page that passes state down)
- [ ] `openMessageStream` imported only by `useChatStream` — never called directly from components
- [ ] `SessionList.tsx` imports `getSessions`, `createSession`, `renameSession`, `deleteSession`
- [ ] `ChatInputBar.tsx` consumes `isStreaming` + `abort` from the stream hook (via props)
- [ ] `SourceSelector.tsx` imports a sources API function (reuse `@/lib/api/sources` from T-006)
- [ ] Chat page layout renders: `<SessionList>` (sidebar) + `<SourceSelector>` (header) + `<MessageThread>` + `<ChatInputBar>`
- [ ] TanStack Query cache invalidated on session mutations: `['chat', 'sessions']` and `['chat', 'messages', sessionId]`
- [ ] All `apiClient` calls send `Authorization: Bearer <token>` (via existing interceptor)
- [ ] `openMessageStream` manually attaches Bearer token — do not assume a global fetch interceptor

---

## ✅ Verification

### Verification Command
```bash
cd frontend && npx tsc --noEmit 2>&1 | grep -E "error TS" | head -10
```
**Expected**: No new TypeScript errors related to chat files.

### Manual Verification
1. Navigate to `/chat` — session sidebar loads
2. Click "New Chat" → new session created, URL updates
3. Select 2 sources from SourceSelector → label reads "2 sources selected"
4. Type a question and press Enter → skeleton appears, then tokens stream progressively
5. During streaming: Send button becomes Stop; click Stop → stream aborts, message shows "[aborted]" marker
6. Refresh page → past messages load via `getMessages`; aborted message still shows `is_partial`
7. Hover a session in sidebar → 3-dot menu appears; click Rename → dialog opens; rename works
8. Delete a session → confirmation dialog; confirms remove session from list
9. Type 2000+ characters → character counter appears
10. Press Shift+Enter → inserts newline; Enter alone → sends

### Accessibility Checklist
- [ ] Chat input has visible label or `aria-label="Message"`
- [ ] Send button has `aria-label="Send message"`, Stop has `aria-label="Stop generation"`
- [ ] Streaming region has `aria-live="polite"` so screen readers announce new tokens
- [ ] Session list items are `<button>` elements with `aria-current="page"` for active session
- [ ] Source selector combobox has `role="combobox"` and proper `aria-expanded`
- [ ] Rename dialog focus-trapped; Delete dialog focus-trapped with destructive action labeled

---

## 📝 Completion Log

<!-- To be filled during /atomicspec.implement -->

- **Started**:
- **Completed**:
- **Files Changed**:
- **Verification Output**:
- **Notes**:
