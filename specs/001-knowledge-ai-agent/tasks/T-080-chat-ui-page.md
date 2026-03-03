# T-080 Â· Chat UI Page â€” Split-Pane Layout

**Status:** Done

**Phase:** 5 â€” Chat Frontend  
**Depends on:** T-076 (chat API), T-075 (schemas)  
**Blocks:** T-081, T-082, T-086

---

## Context

```
Python 3.12 | FastAPI Â· SQLAlchemy 2.x Â· Pydantic v2 Â· dependency-injector
Next.js 15 App Router Â· shadcn/ui Â· Tailwind CSS v4
React Context Â· TanStack Query v5 Â· react-hook-form Â· Zod
PostgreSQL 16 + pgvector Â· HNSW m=16 ef_construction=64 Â· UUID PKs Â· soft-delete + audit columns
Alembic versioned migrations
Celery + Redis Â· Beat replicas=1 STRICT
MinIO Â· presigned PUT pattern
JWT 15-min access + 7-day rotating httpOnly refresh cookie Â· bcrypt Â· RBAC (admin/user)
Fernet (connection configs at rest)
LangGraph 8-node Â· interrupt() for clarification Â· SSE streaming
Langfuse self-hosted Â· every pipeline run must emit a trace
RFC 7807 Problem Details â€” all non-2xx API responses
Structured logging Â· INFO level Â· X-Request-ID correlation
CORS strict Â· CSRF SameSite=Strict httpOnly Â· CSP moderate Â· rate-limit IP
Dark mode Â· responsive Â· WCAG-AA Â· no animations Â· Lucide icons Â· Sonner toasts
snake_case vars/files/tables Â· PascalCase classes Â· SCREAMING_SNAKE_CASE constants
pytest + httpx + Playwright Â· â‰¥80% coverage
Docker Compose 9 services: frontend, backend, worker, beat, db, redis, minio, langfuse, langfuse-db
```

---

## Objective

Build the chat page with a responsive split-pane layout:  
- **Left:** session list sidebar with "New Chat" button + per-session delete  
- **Right:** message thread + (T-081) input bar at bottom  

No animations. WCAG-AA. Dark-mode ready.

---

## 1. Route Page

### `src/app/(dashboard)/chat/page.tsx`

```tsx
import { ChatLayout } from "@/components/chat/ChatLayout";
import { SelectedSessionProvider } from "@/components/chat/SelectedSessionContext";

export const metadata = { title: "Chat â€” Internal Knowledge AI" };

export default function ChatPage() {
  return (
    <SelectedSessionProvider>
      <ChatLayout />
    </SelectedSessionProvider>
  );
}
```

---

## 2. Selected-Session Context

### `src/components/chat/SelectedSessionContext.tsx`

```tsx
"use client";

import {
  createContext,
  useCallback,
  useContext,
  useMemo,
  useState,
} from "react";

interface SelectedSessionContextValue {
  sessionId: string | null;
  setSessionId: (id: string | null) => void;
}

const SelectedSessionContext = createContext<SelectedSessionContextValue>({
  sessionId: null,
  setSessionId: () => {},
});

export function SelectedSessionProvider({
  children,
}: {
  children: React.ReactNode;
}) {
  const [sessionId, setSessionIdState] = useState<string | null>(null);

  const setSessionId = useCallback((id: string | null) => {
    setSessionIdState(id);
  }, []);

  const value = useMemo(
    () => ({ sessionId, setSessionId }),
    [sessionId, setSessionId],
  );

  return (
    <SelectedSessionContext.Provider value={value}>
      {children}
    </SelectedSessionContext.Provider>
  );
}

export function useSelectedSession() {
  return useContext(SelectedSessionContext);
}
```

---

## 3. Chat Layout

### `src/components/chat/ChatLayout.tsx`

```tsx
"use client";

import { useMediaQuery } from "@/hooks/useMediaQuery";
import { MessageThread } from "./MessageThread";
import { SessionList } from "./SessionList";
import { useSelectedSession } from "./SelectedSessionContext";
import { Tabs, TabsContent, TabsList, TabsTrigger } from "@/components/ui/tabs";

export function ChatLayout() {
  const { sessionId } = useSelectedSession();
  const isDesktop = useMediaQuery("(min-width: 768px)");

  if (isDesktop) {
    return (
      <div className="grid h-[calc(100vh-4rem)] grid-cols-[280px_1fr] divide-x divide-border bg-background">
        <aside className="flex flex-col overflow-hidden">
          <SessionList />
        </aside>
        <main className="flex flex-col overflow-hidden">
          <MessageThread sessionId={sessionId} />
        </main>
      </div>
    );
  }

  // Mobile: tabs
  return (
    <div className="flex h-[calc(100vh-4rem)] flex-col">
      <Tabs defaultValue="chat" className="flex flex-1 flex-col overflow-hidden">
        <TabsList className="mx-4 mt-2 shrink-0">
          <TabsTrigger value="sessions" className="flex-1">
            Sessions
          </TabsTrigger>
          <TabsTrigger value="chat" className="flex-1">
            Chat
          </TabsTrigger>
        </TabsList>
        <TabsContent
          value="sessions"
          className="flex-1 overflow-hidden data-[state=inactive]:hidden"
        >
          <SessionList />
        </TabsContent>
        <TabsContent
          value="chat"
          className="flex flex-1 flex-col overflow-hidden data-[state=inactive]:hidden"
        >
          <MessageThread sessionId={sessionId} />
        </TabsContent>
      </Tabs>
    </div>
  );
}
```

---

## 4. useMediaQuery Hook

### `src/hooks/useMediaQuery.ts`

```ts
"use client";

import { useEffect, useState } from "react";

export function useMediaQuery(query: string): boolean {
  const [matches, setMatches] = useState(false);

  useEffect(() => {
    const mql = window.matchMedia(query);
    setMatches(mql.matches);

    const handler = (e: MediaQueryListEvent) => setMatches(e.matches);
    mql.addEventListener("change", handler);
    return () => mql.removeEventListener("change", handler);
  }, [query]);

  return matches;
}
```

---

## 5. Session List

### `src/components/chat/SessionList.tsx`

```tsx
"use client";

import { useCallback } from "react";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { PlusIcon, Trash2Icon } from "lucide-react";
import { toast } from "sonner";
import { Button } from "@/components/ui/button";
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
} from "@/components/ui/alert-dialog";
import { ScrollArea } from "@/components/ui/scroll-area";
import { cn } from "@/lib/utils";
import { apiClient } from "@/lib/api-client";
import { useSelectedSession } from "./SelectedSessionContext";

interface ChatSession {
  id: string;
  title: string;
  updated_at: string;
  message_count: number;
}

interface ChatSessionListResponse {
  items: ChatSession[];
  total: number;
  limit: number;
  offset: number;
}

const SESSIONS_QUERY_KEY = ["chat-sessions"];

async function fetchSessions(): Promise<ChatSessionListResponse> {
  const res = await apiClient.get("/chat/sessions?limit=50&offset=0");
  return res.data;
}

async function createSession(): Promise<ChatSession> {
  const res = await apiClient.post("/chat/sessions", {
    title: "New Chat",
    source_ids: [],
  });
  return res.data;
}

async function deleteSession(sessionId: string): Promise<void> {
  await apiClient.delete(`/chat/sessions/${sessionId}`);
}

export function SessionList() {
  const { sessionId, setSessionId } = useSelectedSession();
  const queryClient = useQueryClient();

  const { data, isLoading } = useQuery({
    queryKey: SESSIONS_QUERY_KEY,
    queryFn: fetchSessions,
    staleTime: 30_000,
  });

  const createMutation = useMutation({
    mutationFn: createSession,
    onSuccess: (newSession) => {
      queryClient.invalidateQueries({ queryKey: SESSIONS_QUERY_KEY });
      setSessionId(newSession.id);
    },
    onError: () => toast.error("Failed to create session."),
  });

  const deleteMutation = useMutation({
    mutationFn: deleteSession,
    onSuccess: (_data, deletedId) => {
      queryClient.invalidateQueries({ queryKey: SESSIONS_QUERY_KEY });
      if (sessionId === deletedId) setSessionId(null);
    },
    onError: () => toast.error("Failed to delete session."),
  });

  const handleNewChat = useCallback(() => {
    createMutation.mutate();
  }, [createMutation]);

  const sessions: ChatSession[] = data?.items ?? [];

  return (
    <div className="flex h-full flex-col">
      {/* Header */}
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

      {/* List */}
      <ScrollArea className="flex-1">
        {isLoading ? (
          <div className="p-4 text-sm text-muted-foreground">Loadingâ€¦</div>
        ) : sessions.length === 0 ? (
          <div className="p-4 text-sm text-muted-foreground">
            No sessions yet. Click + to start.
          </div>
        ) : (
          <ul role="list" className="py-1">
            {sessions.map((s) => (
              <SessionItem
                key={s.id}
                session={s}
                isActive={s.id === sessionId}
                onSelect={() => setSessionId(s.id)}
                onDelete={() => deleteMutation.mutate(s.id)}
                isDeleting={
                  deleteMutation.isPending &&
                  deleteMutation.variables === s.id
                }
              />
            ))}
          </ul>
        )}
      </ScrollArea>
    </div>
  );
}

interface SessionItemProps {
  session: ChatSession;
  isActive: boolean;
  onSelect: () => void;
  onDelete: () => void;
  isDeleting: boolean;
}

function SessionItem({
  session,
  isActive,
  onSelect,
  onDelete,
  isDeleting,
}: SessionItemProps) {
  return (
    <li
      className={cn(
        "group flex items-center gap-2 px-3 py-2 cursor-pointer rounded-sm mx-1 hover:bg-accent",
        isActive && "bg-accent",
      )}
      onClick={onSelect}
      aria-current={isActive ? "page" : undefined}
    >
      <span className="flex-1 truncate text-sm">{session.title}</span>
      <span className="text-xs text-muted-foreground shrink-0">
        {session.message_count}
      </span>

      <AlertDialog>
        <AlertDialogTrigger asChild>
          <Button
            size="icon"
            variant="ghost"
            className="h-6 w-6 shrink-0 opacity-0 group-hover:opacity-100 focus:opacity-100"
            aria-label={`Delete session: ${session.title}`}
            onClick={(e) => e.stopPropagation()}
            disabled={isDeleting}
          >
            <Trash2Icon className="h-3.5 w-3.5" />
          </Button>
        </AlertDialogTrigger>
        <AlertDialogContent>
          <AlertDialogHeader>
            <AlertDialogTitle>Delete session?</AlertDialogTitle>
            <AlertDialogDescription>
              This will permanently delete &ldquo;{session.title}&rdquo; and all
              its messages. This action cannot be undone.
            </AlertDialogDescription>
          </AlertDialogHeader>
          <AlertDialogFooter>
            <AlertDialogCancel onClick={(e) => e.stopPropagation()}>
              Cancel
            </AlertDialogCancel>
            <AlertDialogAction
              onClick={(e) => {
                e.stopPropagation();
                onDelete();
              }}
              className="bg-destructive text-destructive-foreground hover:bg-destructive/90"
            >
              Delete
            </AlertDialogAction>
          </AlertDialogFooter>
        </AlertDialogContent>
      </AlertDialog>
    </li>
  );
}
```

---

## 6. Message Thread

### `src/components/chat/MessageThread.tsx`

```tsx
"use client";

import { useEffect, useRef } from "react";
import { useQuery } from "@tanstack/react-query";
import { apiClient } from "@/lib/api-client";
import { cn } from "@/lib/utils";

export interface Message {
  id: string;
  role: "user" | "assistant";
  content: string;
  created_at: string;
}

interface SessionWithMessages {
  session: { id: string; title: string };
  messages: Message[];
}

interface MessageThreadProps {
  sessionId: string | null;
  streamingToken?: string;
  isStreaming?: boolean;
  extraMessages?: Message[];
}

async function fetchSession(id: string): Promise<SessionWithMessages> {
  const res = await apiClient.get(`/chat/sessions/${id}`);
  return res.data;
}

export function MessageThread({
  sessionId,
  streamingToken = "",
  isStreaming = false,
  extraMessages = [],
}: MessageThreadProps) {
  const bottomRef = useRef<HTMLDivElement>(null);

  const { data } = useQuery({
    queryKey: ["chat-session-messages", sessionId],
    queryFn: () => fetchSession(sessionId!),
    enabled: !!sessionId,
    staleTime: 5_000,
  });

  const persistedMessages: Message[] = data?.messages ?? [];
  const allMessages = [...persistedMessages, ...extraMessages];

  // Auto-scroll to bottom when messages change or during streaming
  useEffect(() => {
    bottomRef.current?.scrollIntoView({ behavior: "instant" });
  }, [allMessages.length, streamingToken]);

  if (!sessionId) {
    return (
      <div className="flex flex-1 items-center justify-center text-muted-foreground text-sm">
        Select a session or start a new chat.
      </div>
    );
  }

  return (
    <div
      className="flex flex-1 flex-col overflow-y-auto px-4 py-4 space-y-4"
      aria-live="polite"
      aria-label="Chat messages"
    >
      {allMessages.length === 0 && !isStreaming ? (
        <div className="flex flex-1 items-center justify-center text-muted-foreground text-sm">
          Start a conversation.
        </div>
      ) : (
        allMessages.map((msg) => (
          <MessageBubble key={msg.id} message={msg} />
        ))
      )}

      {/* Streaming assistant bubble */}
      {isStreaming && (
        <div className="flex justify-start">
          <div
            className={cn(
              "max-w-[75%] rounded-2xl px-4 py-2.5 text-sm",
              "bg-muted text-muted-foreground",
            )}
            aria-live="polite"
            aria-label="Assistant is typing"
          >
            {streamingToken || (
              <span className="inline-block h-4 w-4 animate-pulse rounded-full bg-current opacity-50" />
            )}
            {streamingToken && (
              <span className="ml-0.5 inline-block h-3.5 w-0.5 bg-current opacity-75" />
            )}
          </div>
        </div>
      )}

      <div ref={bottomRef} />
    </div>
  );
}

function MessageBubble({ message }: { message: Message }) {
  const isUser = message.role === "user";
  return (
    <div className={cn("flex", isUser ? "justify-end" : "justify-start")}>
      <div
        className={cn(
          "max-w-[75%] rounded-2xl px-4 py-2.5 text-sm whitespace-pre-wrap break-words",
          isUser
            ? "bg-primary text-primary-foreground"
            : "bg-muted text-muted-foreground",
        )}
      >
        {message.content}
      </div>
    </div>
  );
}
```

---

## 7. Wire ChatLayout to accept streaming props from T-081

`ChatLayout` will be updated in T-081 to pass `streamingToken`, `isStreaming`, and `extraMessages` down from `useChat`. The split in two tasks keeps each file focused.

---

## 8. Navigation Link

### Patch: `src/components/layout/sidebar-nav.tsx` (or equivalent)

Add a "Chat" nav item:

```tsx
{ href: "/chat", label: "Chat", icon: MessageCircleIcon }
```

Ensure the link appears for all authenticated users (not admin-only).

---

## 9. Tests

### `src/components/chat/__tests__/SessionList.test.tsx`

```tsx
import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { SessionList } from "../SessionList";
import { SelectedSessionProvider } from "../SelectedSessionContext";
import { vi } from "vitest";

// Mock apiClient
vi.mock("@/lib/api-client", () => ({
  apiClient: {
    get: vi.fn().mockResolvedValue({
      data: {
        items: [
          { id: "s1", title: "Test Chat", updated_at: "2024-01-01T00:00:00Z", message_count: 3 },
        ],
        total: 1,
        limit: 50,
        offset: 0,
      },
    }),
    post: vi.fn().mockResolvedValue({
      data: { id: "s2", title: "New Chat", updated_at: "2024-01-02T00:00:00Z", message_count: 0 },
    }),
    delete: vi.fn().mockResolvedValue({}),
  },
}));

function wrapper({ children }: { children: React.ReactNode }) {
  const qc = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  return (
    <QueryClientProvider client={qc}>
      <SelectedSessionProvider>{children}</SelectedSessionProvider>
    </QueryClientProvider>
  );
}

test("renders session list item", async () => {
  render(<SessionList />, { wrapper });
  expect(await screen.findByText("Test Chat")).toBeInTheDocument();
});

test("new chat button calls createSession", async () => {
  const { apiClient } = await import("@/lib/api-client");
  render(<SessionList />, { wrapper });
  await userEvent.click(screen.getByRole("button", { name: /new chat/i }));
  expect(apiClient.post).toHaveBeenCalledWith(
    "/chat/sessions",
    expect.objectContaining({ title: "New Chat" }),
  );
});
```

### `src/components/chat/__tests__/MessageThread.test.tsx`

```tsx
import { render, screen } from "@testing-library/react";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { MessageThread } from "../MessageThread";
import { vi } from "vitest";

vi.mock("@/lib/api-client", () => ({
  apiClient: {
    get: vi.fn().mockResolvedValue({
      data: {
        session: { id: "s1", title: "Test" },
        messages: [
          { id: "m1", role: "user", content: "Hello", created_at: "2024-01-01T00:00:00Z" },
          { id: "m2", role: "assistant", content: "Hi there!", created_at: "2024-01-01T00:00:01Z" },
        ],
      },
    }),
  },
}));

function wrapper({ children }: { children: React.ReactNode }) {
  const qc = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  return <QueryClientProvider client={qc}>{children}</QueryClientProvider>;
}

test("renders messages for a session", async () => {
  render(<MessageThread sessionId="s1" />, { wrapper });
  expect(await screen.findByText("Hello")).toBeInTheDocument();
  expect(screen.getByText("Hi there!")).toBeInTheDocument();
});

test("shows empty state when no session", () => {
  render(<MessageThread sessionId={null} />, { wrapper });
  expect(
    screen.getByText(/select a session or start a new chat/i),
  ).toBeInTheDocument();
});

test("shows streaming cursor when isStreaming=true", () => {
  render(<MessageThread sessionId="s1" isStreaming streamingToken="" />, {
    wrapper,
  });
  // The pulsing cursor span should be in the DOM
  const cursor = document.querySelector(".animate-pulse");
  expect(cursor).not.toBeNull();
});
```

---

## Acceptance Criteria

- [ ] `/chat` route renders without JS errors
- [ ] Desktop: 280px sidebar + main panel layout visible
- [ ] Mobile (â‰¤767px): Tabs UI visible
- [ ] SessionList shows sessions sorted by `updated_at DESC`
- [ ] "New Chat" button creates a session and selects it
- [ ] Delete button shows confirm dialog; confirmed delete removes session
- [ ] Active session highlighted with `bg-accent`
- [ ] MessageThread auto-scrolls to bottom on new message
- [ ] `aria-live="polite"` on MessageThread container
- [ ] Streaming cursor visible when `isStreaming=true`
- [ ] Dark mode: all surfaces use CSS variable colours
- [ ] No animation classes except the streaming pulse cursor
- [ ] Unit tests pass: `pnpm test`
