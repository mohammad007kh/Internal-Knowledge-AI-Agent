# T-081 Â· Chat Input Bar & SSE Streaming

**Status:** Done

**Phase:** 5 â€” Chat Frontend  
**Depends on:** T-080 (layout/thread), T-076 (chat API)  
**Blocks:** T-086

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

Build the chat input bar and real-time SSE streaming integration.

The backend streams `POST /chat/sessions/{id}/stream` (EventSource) with events:

| Event name | Payload |
|---|---|
| `token` | `{ token: string }` |
| `done` | `{ message_id: string }` |
| `error` | `{ detail: string }` |
| `clarification_needed` | `{ question: string, message_id: string }` |

The frontend must:
1. Show optimistic user message immediately
2. Open SSE, accumulate tokens into a streaming bubble
3. On `done` â€” invalidate session query (persisted message appears)
4. On `clarification_needed` â€” show inline clarification card instead of full response
5. On `error` â€” show Sonner toast, remove optimistic message

---

## 1. `useChat` Hook

### `src/components/chat/useChat.ts`

```ts
"use client";

import { useCallback, useRef, useState } from "react";
import { useQueryClient } from "@tanstack/react-query";
import { toast } from "sonner";
import type { Message } from "./MessageThread";

interface UseChatOptions {
  sessionId: string | null;
}

interface ClarificationState {
  question: string;
  messageId: string;
}

interface UseChatReturn {
  send: (text: string) => void;
  isPending: boolean;
  streamingToken: string;
  isStreaming: boolean;
  optimisticMessages: Message[];
  clarification: ClarificationState | null;
  dismissClarification: () => void;
}

export function useChat({ sessionId }: UseChatOptions): UseChatReturn {
  const queryClient = useQueryClient();
  const abortRef = useRef<AbortController | null>(null);

  const [isPending, setIsPending] = useState(false);
  const [isStreaming, setIsStreaming] = useState(false);
  const [streamingToken, setStreamingToken] = useState("");
  const [optimisticMessages, setOptimisticMessages] = useState<Message[]>([]);
  const [clarification, setClarification] = useState<ClarificationState | null>(
    null,
  );

  const send = useCallback(
    (text: string) => {
      if (!sessionId || isPending) return;

      // Abort any in-flight SSE
      abortRef.current?.abort();
      abortRef.current = new AbortController();

      const optimisticId = crypto.randomUUID();
      const optimisticMsg: Message = {
        id: optimisticId,
        role: "user",
        content: text,
        created_at: new Date().toISOString(),
      };

      setOptimisticMessages([optimisticMsg]);
      setStreamingToken("");
      setIsStreaming(false);
      setIsPending(true);
      setClarification(null);

      const url = `${process.env.NEXT_PUBLIC_API_URL}/chat/sessions/${sessionId}/stream`;

      // We use fetch + ReadableStream to support auth headers
      // (EventSource does not support custom headers)
      fetch(url, {
        method: "POST",
        headers: {
          "Content-Type": "application/json",
          // Credentials: cookies (httpOnly) are sent automatically with
          // same-origin requests; for cross-origin we rely on withCredentials
        },
        credentials: "include",
        body: JSON.stringify({ message: text }),
        signal: abortRef.current.signal,
      })
        .then(async (res) => {
          if (!res.ok) {
            const problem = await res.json().catch(() => ({}));
            throw new Error(
              (problem as { detail?: string }).detail ??
                `HTTP ${res.status}`,
            );
          }
          if (!res.body) throw new Error("No response body");

          setIsStreaming(true);
          let accumulated = "";

          const reader = res.body.getReader();
          const decoder = new TextDecoder();

          // SSE parsing over ReadableStream
          let buffer = "";
          while (true) {
            const { done, value } = await reader.read();
            if (done) break;

            buffer += decoder.decode(value, { stream: true });

            // Split on double-newline SSE boundaries
            const parts = buffer.split("\n\n");
            buffer = parts.pop() ?? "";

            for (const part of parts) {
              if (!part.trim()) continue;
              const lines = part.split("\n");
              let eventName = "message";
              let data = "";

              for (const line of lines) {
                if (line.startsWith("event: ")) {
                  eventName = line.slice(7).trim();
                } else if (line.startsWith("data: ")) {
                  data = line.slice(6).trim();
                }
              }

              try {
                const payload = JSON.parse(data);
                if (eventName === "token") {
                  accumulated += (payload as { token: string }).token;
                  setStreamingToken(accumulated);
                } else if (eventName === "done") {
                  setIsStreaming(false);
                  setStreamingToken("");
                  setOptimisticMessages([]);
                  queryClient.invalidateQueries({
                    queryKey: ["chat-session-messages", sessionId],
                  });
                  queryClient.invalidateQueries({
                    queryKey: ["chat-sessions"],
                  });
                } else if (eventName === "clarification_needed") {
                  const p = payload as { question: string; message_id: string };
                  setIsStreaming(false);
                  setStreamingToken("");
                  setClarification({
                    question: p.question,
                    messageId: p.message_id,
                  });
                } else if (eventName === "error") {
                  const p = payload as { detail: string };
                  throw new Error(p.detail);
                }
              } catch (parseErr) {
                if (
                  parseErr instanceof Error &&
                  parseErr.message.startsWith("HTTP")
                ) {
                  throw parseErr;
                }
                // Silently skip malformed SSE frames
              }
            }
          }
        })
        .catch((err: unknown) => {
          if (err instanceof Error && err.name === "AbortError") return;
          setIsStreaming(false);
          setStreamingToken("");
          setOptimisticMessages([]);
          toast.error(
            err instanceof Error ? err.message : "Chat request failed.",
          );
        })
        .finally(() => {
          setIsPending(false);
        });
    },
    [sessionId, isPending, queryClient],
  );

  const dismissClarification = useCallback(() => setClarification(null), []);

  return {
    send,
    isPending,
    streamingToken,
    isStreaming,
    optimisticMessages,
    clarification,
    dismissClarification,
  };
}
```

---

## 2. Chat Input Bar

### `src/components/chat/ChatInputBar.tsx`

```tsx
"use client";

import { useCallback, useRef } from "react";
import { SendHorizonalIcon } from "lucide-react";
import { Button } from "@/components/ui/button";
import { Textarea } from "@/components/ui/textarea";
import { cn } from "@/lib/utils";

interface ChatInputBarProps {
  onSend: (text: string) => void;
  disabled?: boolean;
  sessionId: string | null;
}

const MAX_CHARS = 4000;

export function ChatInputBar({ onSend, disabled, sessionId }: ChatInputBarProps) {
  const textareaRef = useRef<HTMLTextAreaElement>(null);

  const handleSend = useCallback(() => {
    const value = textareaRef.current?.value.trim();
    if (!value || disabled || !sessionId) return;
    onSend(value);
    if (textareaRef.current) textareaRef.current.value = "";
  }, [disabled, onSend, sessionId]);

  const handleKeyDown = useCallback(
    (e: React.KeyboardEvent<HTMLTextAreaElement>) => {
      if (e.key === "Enter" && !e.shiftKey) {
        e.preventDefault();
        handleSend();
      }
    },
    [handleSend],
  );

  return (
    <form
      className="flex items-end gap-2 border-t border-border bg-background px-4 py-3"
      onSubmit={(e) => {
        e.preventDefault();
        handleSend();
      }}
      aria-label="Chat input"
    >
      <Textarea
        ref={textareaRef}
        placeholder={
          sessionId ? "Ask a questionâ€¦ (Enter to send, Shift+Enter for newline)" : "Select a session firstâ€¦"
        }
        className={cn(
          "max-h-40 min-h-[2.75rem] flex-1 resize-none rounded-xl",
        )}
        rows={1}
        maxLength={MAX_CHARS}
        disabled={disabled || !sessionId}
        onKeyDown={handleKeyDown}
        aria-label="Chat message input"
      />
      <Button
        type="submit"
        size="icon"
        disabled={disabled || !sessionId}
        aria-label="Send message"
        className="shrink-0"
      >
        <SendHorizonalIcon className="h-4 w-4" />
      </Button>
    </form>
  );
}
```

---

## 3. Clarification Card

### `src/components/chat/ClarificationCard.tsx`

```tsx
"use client";

import { useCallback, useRef } from "react";
import { HelpCircleIcon, SendHorizonalIcon, XIcon } from "lucide-react";
import { Button } from "@/components/ui/button";
import { Textarea } from "@/components/ui/textarea";

interface ClarificationCardProps {
  question: string;
  onDismiss: () => void;
  onReply: (answer: string) => void;
  disabled?: boolean;
}

export function ClarificationCard({
  question,
  onDismiss,
  onReply,
  disabled,
}: ClarificationCardProps) {
  const textareaRef = useRef<HTMLTextAreaElement>(null);

  const handleReply = useCallback(() => {
    const val = textareaRef.current?.value.trim();
    if (!val) return;
    onReply(val);
    if (textareaRef.current) textareaRef.current.value = "";
  }, [onReply]);

  return (
    <div
      className="mx-4 mb-3 rounded-xl border border-border bg-muted p-4"
      role="region"
      aria-label="Clarification needed"
    >
      <div className="mb-2 flex items-start justify-between gap-2">
        <div className="flex items-start gap-2">
          <HelpCircleIcon className="mt-0.5 h-4 w-4 shrink-0 text-muted-foreground" />
          <p className="text-sm text-foreground">{question}</p>
        </div>
        <Button
          size="icon"
          variant="ghost"
          className="h-6 w-6 shrink-0"
          onClick={onDismiss}
          aria-label="Dismiss clarification"
        >
          <XIcon className="h-3.5 w-3.5" />
        </Button>
      </div>

      <div className="flex items-end gap-2">
        <Textarea
          ref={textareaRef}
          placeholder="Your answerâ€¦"
          className="max-h-28 min-h-[2.25rem] flex-1 resize-none rounded-lg"
          rows={1}
          disabled={disabled}
          aria-label="Clarification reply"
          onKeyDown={(e) => {
            if (e.key === "Enter" && !e.shiftKey) {
              e.preventDefault();
              handleReply();
            }
          }}
        />
        <Button
          size="icon"
          className="shrink-0"
          disabled={disabled}
          onClick={handleReply}
          aria-label="Send clarification reply"
        >
          <SendHorizonalIcon className="h-4 w-4" />
        </Button>
      </div>
    </div>
  );
}
```

---

## 4. Updated ChatLayout (wires T-080 + T-081)

### `src/components/chat/ChatLayout.tsx` â€” update

Replace the body of `ChatLayout` to wire `useChat`:

```tsx
"use client";

import { useMediaQuery } from "@/hooks/useMediaQuery";
import { MessageThread } from "./MessageThread";
import { SessionList } from "./SessionList";
import { useSelectedSession } from "./SelectedSessionContext";
import { Tabs, TabsContent, TabsList, TabsTrigger } from "@/components/ui/tabs";
import { ChatInputBar } from "./ChatInputBar";
import { ClarificationCard } from "./ClarificationCard";
import { useChat } from "./useChat";

export function ChatLayout() {
  const { sessionId } = useSelectedSession();
  const isDesktop = useMediaQuery("(min-width: 768px)");
  const {
    send,
    isPending,
    streamingToken,
    isStreaming,
    optimisticMessages,
    clarification,
    dismissClarification,
  } = useChat({ sessionId });

  const chatPane = (
    <div className="flex flex-1 flex-col overflow-hidden">
      <MessageThread
        sessionId={sessionId}
        streamingToken={streamingToken}
        isStreaming={isStreaming}
        extraMessages={optimisticMessages}
      />
      {clarification && (
        <ClarificationCard
          question={clarification.question}
          onDismiss={dismissClarification}
          onReply={(answer) => send(answer)}
          disabled={isPending}
        />
      )}
      <ChatInputBar
        onSend={send}
        disabled={isPending}
        sessionId={sessionId}
      />
    </div>
  );

  if (isDesktop) {
    return (
      <div className="grid h-[calc(100vh-4rem)] grid-cols-[280px_1fr] divide-x divide-border bg-background">
        <aside className="flex flex-col overflow-hidden">
          <SessionList />
        </aside>
        <main className="flex flex-col overflow-hidden">{chatPane}</main>
      </div>
    );
  }

  return (
    <div className="flex h-[calc(100vh-4rem)] flex-col">
      <Tabs defaultValue="chat" className="flex flex-1 flex-col overflow-hidden">
        <TabsList className="mx-4 mt-2 shrink-0">
          <TabsTrigger value="sessions" className="flex-1">Sessions</TabsTrigger>
          <TabsTrigger value="chat" className="flex-1">Chat</TabsTrigger>
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
          {chatPane}
        </TabsContent>
      </Tabs>
    </div>
  );
}
```

---

## 5. Tests

### `src/components/chat/__tests__/ChatInputBar.test.tsx`

```tsx
import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { ChatInputBar } from "../ChatInputBar";
import { vi } from "vitest";

test("calls onSend with trimmed text on Enter", async () => {
  const onSend = vi.fn();
  render(<ChatInputBar onSend={onSend} disabled={false} sessionId="s1" />);
  const textarea = screen.getByRole("textbox");
  await userEvent.type(textarea, "Hello world");
  await userEvent.keyboard("{Enter}");
  expect(onSend).toHaveBeenCalledWith("Hello world");
});

test("Shift+Enter does not send", async () => {
  const onSend = vi.fn();
  render(<ChatInputBar onSend={onSend} disabled={false} sessionId="s1" />);
  const textarea = screen.getByRole("textbox");
  await userEvent.type(textarea, "Line1");
  await userEvent.keyboard("{Shift>}{Enter}{/Shift}");
  expect(onSend).not.toHaveBeenCalled();
});

test("send button is disabled when no sessionId", () => {
  render(<ChatInputBar onSend={vi.fn()} disabled={false} sessionId={null} />);
  expect(screen.getByRole("button", { name: /send/i })).toBeDisabled();
});
```

### `src/components/chat/__tests__/useChat.test.ts`

```ts
import { renderHook, act, waitFor } from "@testing-library/react";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { useChat } from "../useChat";
import { vi } from "vitest";

// Minimal SSE fetch mock
const makeSseMock = (frames: string) => {
  const encoder = new TextEncoder();
  const encoded = encoder.encode(frames);
  const stream = new ReadableStream({
    start(controller) {
      controller.enqueue(encoded);
      controller.close();
    },
  });
  return Promise.resolve(new Response(stream, { status: 200 }));
};

vi.stubGlobal(
  "fetch",
  vi.fn().mockImplementation(() =>
    makeSseMock(
      'event: token\ndata: {"token":"Hi"}\n\nevent: done\ndata: {"message_id":"m1"}\n\n',
    ),
  ),
);

function wrapper({ children }: { children: React.ReactNode }) {
  const qc = new QueryClient();
  return (
    // eslint-disable-next-line @typescript-eslint/no-explicit-any
    <QueryClientProvider client={qc}>{children as any}</QueryClientProvider>
  );
}

test("send sets isStreaming then clears on done", async () => {
  const { result } = renderHook(() => useChat({ sessionId: "s1" }), {
    wrapper,
  });

  act(() => result.current.send("Hello"));

  await waitFor(() => expect(result.current.isPending).toBe(false));
  expect(result.current.streamingToken).toBe("");
  expect(result.current.isStreaming).toBe(false);
});
```

---

## 6. Env Var

Ensure `.env.local` / Docker Compose frontend environment includes:

```env
NEXT_PUBLIC_API_URL=http://localhost:8000/api/v1
```

---

## Acceptance Criteria

- [ ] Typing a message and pressing Enter sends `POST /chat/sessions/{id}/stream` with `credentials: "include"`
- [ ] Optimistic user message appears immediately in thread
- [ ] Assistant tokens accumulate in a streaming bubble in real time
- [ ] On `done` event: streaming bubble disappears, persisted messages appear via query invalidation
- [ ] On `clarification_needed`: `ClarificationCard` appears with the question
- [ ] Clarification reply triggers new `send()` call
- [ ] On `error` SSE event: Sonner toast shown, optimistic message removed
- [ ] Shift+Enter inserts newline (does not send)
- [ ] Send button is aria-labelled and focusable
- [ ] Input is disabled while `isPending`
- [ ] All unit tests pass: `pnpm test`
