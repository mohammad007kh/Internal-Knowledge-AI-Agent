# T-084 · Session Management UI

**Phase:** 5 — Chat Frontend  
**Depends on:** T-080 (layout), T-076 (chat API)  
**Blocks:** T-086

---

## Context

```
Python 3.12 | FastAPI · SQLAlchemy 2.x · Pydantic v2 · dependency-injector
Next.js 15 App Router · shadcn/ui · Tailwind CSS v4
React Context · TanStack Query v5 · react-hook-form · Zod
PostgreSQL 16 + pgvector · HNSW m=16 ef_construction=64 · UUID PKs · soft-delete + audit columns
Alembic versioned migrations
Celery + Redis · Beat replicas=1 STRICT
MinIO · presigned PUT pattern
JWT 15-min access + 7-day rotating httpOnly refresh cookie · bcrypt · RBAC (admin/user)
Fernet (connection configs at rest)
LangGraph 8-node · interrupt() for clarification · SSE streaming
Langfuse self-hosted · every pipeline run must emit a trace
RFC 7807 Problem Details — all non-2xx API responses
Structured logging · INFO level · X-Request-ID correlation
CORS strict · CSRF SameSite=Strict httpOnly · CSP moderate · rate-limit IP
Dark mode · responsive · WCAG-AA · no animations · Lucide icons · Sonner toasts
snake_case vars/files/tables · PascalCase classes · SCREAMING_SNAKE_CASE constants
pytest + httpx + Playwright · ≥80% coverage
Docker Compose 9 services: frontend, backend, worker, beat, db, redis, minio, langfuse, langfuse-db
```

---

## Objective

Build the session list sidebar and session management actions:

- **Create** a new session (POST `/chat/sessions`)
- **Select** a session (highlights and loads the message thread)
- **Rename** a session (PATCH `/chat/sessions/{id}`)
- **Delete** a session (DELETE `/chat/sessions/{id}` with soft-delete confirmation)
- **Search/filter** sessions by title

---

## 1. `SessionList` Component

### `src/components/chat/SessionList.tsx`

```tsx
"use client";

import { useCallback, useState } from "react";
import { useQuery, useMutation, useQueryClient } from "@tanstack/react-query";
import {
  PlusIcon,
  SearchIcon,
  Trash2Icon,
  PencilIcon,
  MessageSquareIcon,
  CheckIcon,
  XIcon,
} from "lucide-react";
import { toast } from "sonner";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { ScrollArea } from "@/components/ui/scroll-area";
import {
  AlertDialog,
  AlertDialogAction,
  AlertDialogCancel,
  AlertDialogContent,
  AlertDialogDescription,
  AlertDialogFooter,
  AlertDialogHeader,
  AlertDialogTitle,
} from "@/components/ui/alert-dialog";
import { cn } from "@/lib/utils";
import { apiClient } from "@/lib/api-client";
import { useSelectedSession } from "./SelectedSessionContext";

// ─── Types ──────────────────────────────────────────────────────────────────

interface ChatSession {
  id: string;
  title: string;
  created_at: string;
  updated_at: string;
  message_count: number;
}

interface SessionsResponse {
  items: ChatSession[];
  total: number;
}

// ─── API helpers ─────────────────────────────────────────────────────────────

const sessionsApi = {
  list: async (): Promise<SessionsResponse> => {
    const res = await apiClient.get<SessionsResponse>("/chat/sessions?limit=100");
    return res.data;
  },
  create: async (title: string): Promise<ChatSession> => {
    const res = await apiClient.post<ChatSession>("/chat/sessions", { title });
    return res.data;
  },
  rename: async (id: string, title: string): Promise<ChatSession> => {
    const res = await apiClient.patch<ChatSession>(`/chat/sessions/${id}`, {
      title,
    });
    return res.data;
  },
  delete: async (id: string): Promise<void> => {
    await apiClient.delete(`/chat/sessions/${id}`);
  },
};

// ─── Component ───────────────────────────────────────────────────────────────

export function SessionList() {
  const { sessionId, setSessionId } = useSelectedSession();
  const queryClient = useQueryClient();

  const [search, setSearch] = useState("");
  const [editingId, setEditingId] = useState<string | null>(null);
  const [editTitle, setEditTitle] = useState("");
  const [deletingId, setDeletingId] = useState<string | null>(null);

  // ── Queries ──────────────────────────────────────────────────────────────

  const { data, isLoading } = useQuery({
    queryKey: ["chat-sessions"],
    queryFn: sessionsApi.list,
    staleTime: 15_000,
    refetchOnWindowFocus: true,
  });

  const sessions: ChatSession[] = data?.items ?? [];
  const filtered = sessions.filter((s) =>
    s.title.toLowerCase().includes(search.toLowerCase()),
  );

  // ── Mutations ─────────────────────────────────────────────────────────────

  const createMutation = useMutation({
    mutationFn: () => sessionsApi.create("New chat"),
    onSuccess: (session) => {
      queryClient.invalidateQueries({ queryKey: ["chat-sessions"] });
      setSessionId(session.id);
      // Immediately open rename mode for the new session
      setEditingId(session.id);
      setEditTitle(session.title);
    },
    onError: () => toast.error("Failed to create session."),
  });

  const renameMutation = useMutation({
    mutationFn: ({ id, title }: { id: string; title: string }) =>
      sessionsApi.rename(id, title),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ["chat-sessions"] });
      setEditingId(null);
    },
    onError: () => toast.error("Failed to rename session."),
  });

  const deleteMutation = useMutation({
    mutationFn: (id: string) => sessionsApi.delete(id),
    onSuccess: (_, deletedId) => {
      queryClient.invalidateQueries({ queryKey: ["chat-sessions"] });
      if (sessionId === deletedId) setSessionId(null);
      setDeletingId(null);
      toast.success("Session deleted.");
    },
    onError: () => toast.error("Failed to delete session."),
  });

  // ── Handlers ─────────────────────────────────────────────────────────────

  const startEdit = useCallback((session: ChatSession) => {
    setEditingId(session.id);
    setEditTitle(session.title);
  }, []);

  const commitEdit = useCallback(
    (id: string) => {
      const trimmed = editTitle.trim();
      if (!trimmed) {
        setEditingId(null);
        return;
      }
      renameMutation.mutate({ id, title: trimmed });
    },
    [editTitle, renameMutation],
  );

  const cancelEdit = useCallback(() => setEditingId(null), []);

  // ── Render ────────────────────────────────────────────────────────────────

  return (
    <div className="flex h-full flex-col bg-background">
      {/* Header */}
      <div className="flex items-center justify-between border-b border-border px-3 py-3">
        <h2 className="text-sm font-semibold text-foreground">Sessions</h2>
        <Button
          size="icon"
          variant="ghost"
          className="h-7 w-7"
          onClick={() => createMutation.mutate()}
          disabled={createMutation.isPending}
          aria-label="New chat session"
        >
          <PlusIcon className="h-4 w-4" />
        </Button>
      </div>

      {/* Search */}
      <div className="px-3 py-2">
        <div className="relative">
          <SearchIcon className="absolute left-2.5 top-1/2 h-3.5 w-3.5 -translate-y-1/2 text-muted-foreground" />
          <Input
            value={search}
            onChange={(e) => setSearch(e.target.value)}
            placeholder="Search sessions…"
            className="h-8 pl-8 text-xs"
            aria-label="Search sessions"
          />
        </div>
      </div>

      {/* List */}
      <ScrollArea className="flex-1">
        {isLoading ? (
          <div className="flex flex-col gap-1 px-3 py-2">
            {Array.from({ length: 5 }).map((_, i) => (
              <div
                key={i}
                className="h-9 w-full animate-pulse rounded-md bg-muted"
                aria-hidden="true"
              />
            ))}
          </div>
        ) : filtered.length === 0 ? (
          <div className="flex flex-col items-center gap-2 px-3 py-8">
            <MessageSquareIcon className="h-8 w-8 text-muted-foreground/50" />
            <p className="text-center text-xs text-muted-foreground">
              {sessions.length === 0
                ? "No sessions yet. Start a new chat."
                : "No sessions match your search."}
            </p>
          </div>
        ) : (
          <ul role="list" className="flex flex-col gap-0.5 px-2 py-1">
            {filtered.map((session) => (
              <SessionItem
                key={session.id}
                session={session}
                isActive={sessionId === session.id}
                isEditing={editingId === session.id}
                editTitle={editTitle}
                onSelect={() => setSessionId(session.id)}
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

      {/* Delete confirmation */}
      <AlertDialog
        open={!!deletingId}
        onOpenChange={(o) => !o && setDeletingId(null)}
      >
        <AlertDialogContent>
          <AlertDialogHeader>
            <AlertDialogTitle>Delete session?</AlertDialogTitle>
            <AlertDialogDescription>
              All messages in this session will be permanently deleted. This
              action cannot be undone.
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
  );
}

// ─── Session Item ─────────────────────────────────────────────────────────────

interface SessionItemProps {
  session: ChatSession;
  isActive: boolean;
  isEditing: boolean;
  editTitle: string;
  onSelect: () => void;
  onStartEdit: () => void;
  onEditChange: (v: string) => void;
  onCommitEdit: () => void;
  onCancelEdit: () => void;
  onDelete: () => void;
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
    <li role="listitem">
      <div
        className={cn(
          "group flex items-center gap-1.5 rounded-md px-2 py-1.5 text-sm",
          "cursor-pointer select-none",
          isActive
            ? "bg-accent text-accent-foreground"
            : "hover:bg-muted text-foreground",
        )}
        onClick={() => {
          if (!isEditing) onSelect();
        }}
        aria-current={isActive ? "page" : undefined}
        role="button"
        tabIndex={0}
        aria-label={`Chat session: ${session.title}`}
        onKeyDown={(e) => {
          if (e.key === "Enter" && !isEditing) onSelect();
        }}
      >
        <MessageSquareIcon
          className="h-3.5 w-3.5 shrink-0 text-muted-foreground"
          aria-hidden="true"
        />

        {isEditing ? (
          <div className="flex flex-1 items-center gap-1" onClick={(e) => e.stopPropagation()}>
            <Input
              value={editTitle}
              onChange={(e) => onEditChange(e.target.value)}
              className="h-6 flex-1 px-1.5 text-xs"
              autoFocus
              maxLength={100}
              onKeyDown={(e) => {
                if (e.key === "Enter") onCommitEdit();
                if (e.key === "Escape") onCancelEdit();
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
            {/* Badge: message count */}
            {session.message_count > 0 && (
              <span
                className="ml-auto shrink-0 rounded-full bg-muted px-1.5 py-0.5 text-[10px] text-muted-foreground"
                aria-label={`${session.message_count} messages`}
              >
                {session.message_count}
              </span>
            )}
            {/* Action icons: visible on hover/focus */}
            <div
              className="ml-1 hidden shrink-0 items-center gap-0.5 group-hover:flex"
              onClick={(e) => e.stopPropagation()}
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
  );
}
```

---

## 2. `SelectedSessionContext`

### `src/components/chat/SelectedSessionContext.tsx`

```tsx
"use client";

import { createContext, useContext, useState } from "react";

interface SelectedSessionContextValue {
  sessionId: string | null;
  setSessionId: (id: string | null) => void;
}

const SelectedSessionContext = createContext<SelectedSessionContextValue>({
  sessionId: null,
  setSessionId: () => undefined,
});

export function SelectedSessionProvider({
  children,
}: {
  children: React.ReactNode;
}) {
  const [sessionId, setSessionId] = useState<string | null>(null);
  return (
    <SelectedSessionContext.Provider value={{ sessionId, setSessionId }}>
      {children}
    </SelectedSessionContext.Provider>
  );
}

export function useSelectedSession() {
  return useContext(SelectedSessionContext);
}
```

---

## 3. Wrap app layout

`src/app/(app)/chat/layout.tsx`:

```tsx
import { SelectedSessionProvider } from "@/components/chat/SelectedSessionContext";

export default function ChatLayout({
  children,
}: {
  children: React.ReactNode;
}) {
  return <SelectedSessionProvider>{children}</SelectedSessionProvider>;
}
```

---

## 4. Tests

### `src/components/chat/__tests__/SessionList.test.tsx`

```tsx
import { render, screen, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { SessionList } from "../SessionList";
import { SelectedSessionProvider } from "../SelectedSessionContext";
import { vi } from "vitest";

const mockSessions = [
  {
    id: "s1",
    title: "Project alpha",
    created_at: new Date().toISOString(),
    updated_at: new Date().toISOString(),
    message_count: 3,
  },
  {
    id: "s2",
    title: "Security review",
    created_at: new Date().toISOString(),
    updated_at: new Date().toISOString(),
    message_count: 0,
  },
];

vi.mock("@/lib/api-client", () => ({
  apiClient: {
    get: vi.fn().mockResolvedValue({ data: { items: mockSessions, total: 2 } }),
    post: vi.fn().mockResolvedValue({
      data: {
        id: "s3",
        title: "New chat",
        message_count: 0,
        created_at: new Date().toISOString(),
        updated_at: new Date().toISOString(),
      },
    }),
    patch: vi.fn().mockResolvedValue({ data: { ...mockSessions[0], title: "Renamed" } }),
    delete: vi.fn().mockResolvedValue({ data: {} }),
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

test("renders session list", async () => {
  render(<SessionList />, { wrapper });
  expect(await screen.findByText("Project alpha")).toBeInTheDocument();
  expect(screen.getByText("Security review")).toBeInTheDocument();
});

test("filters sessions by search", async () => {
  render(<SessionList />, { wrapper });
  await screen.findByText("Project alpha");
  await userEvent.type(screen.getByRole("textbox", { name: /search/i }), "security");
  expect(screen.queryByText("Project alpha")).not.toBeInTheDocument();
  expect(screen.getByText("Security review")).toBeInTheDocument();
});

test("new session button fires create mutation", async () => {
  const { apiClient } = await import("@/lib/api-client");
  render(<SessionList />, { wrapper });
  await screen.findByText("Project alpha");
  await userEvent.click(screen.getByRole("button", { name: /new chat session/i }));
  expect(apiClient.post).toHaveBeenCalledWith("/chat/sessions", { title: "New chat" });
});

test("shows delete confirmation dialog", async () => {
  render(<SessionList />, { wrapper });
  await screen.findByText("Project alpha");
  const item = screen.getByRole("button", { name: /chat session: project alpha/i });
  // Hover to reveal actions
  await userEvent.hover(item);
  const deleteBtn = await screen.findByRole("button", { name: /delete: project alpha/i });
  await userEvent.click(deleteBtn);
  expect(
    screen.getByText(/all messages in this session will be permanently deleted/i),
  ).toBeInTheDocument();
});

test("Escape closes rename mode", async () => {
  render(<SessionList />, { wrapper });
  await screen.findByText("Project alpha");
  const item = screen.getByRole("button", { name: /chat session: project alpha/i });
  await userEvent.hover(item);
  await userEvent.click(
    await screen.findByRole("button", { name: /rename: project alpha/i }),
  );
  expect(screen.getByRole("textbox", { name: /rename session/i })).toBeInTheDocument();
  await userEvent.keyboard("{Escape}");
  expect(
    screen.queryByRole("textbox", { name: /rename session/i }),
  ).not.toBeInTheDocument();
});
```

---

## Acceptance Criteria

- [ ] Session list renders all sessions from `GET /chat/sessions`
- [ ] Sessions filtered in real time as user types in search input
- [ ] "+" New button creates a session via `POST /chat/sessions` and auto-selects it
- [ ] New session immediately enters rename mode (inline input)
- [ ] Rename committed on Enter or ✓ button; cancelled on Escape or ✗ button
- [ ] Rename calls `PATCH /chat/sessions/{id}` with new title
- [ ] Hover/focus on item reveals Rename (pencil) and Delete (trash) icon buttons
- [ ] Delete shows `AlertDialog` confirmation before `DELETE /chat/sessions/{id}`
- [ ] Deleting the active session clears `sessionId` and shows empty thread state
- [ ] Message count badge shown when `message_count > 0`
- [ ] Active session highlighted with `aria-current="page"`
- [ ] Skeleton loading shown while sessions query is loading
- [ ] Empty state with icon when no sessions exist
- [ ] Keyboard navigation: Enter to select, Escape to cancel rename
- [ ] All unit tests pass: `pnpm test`
