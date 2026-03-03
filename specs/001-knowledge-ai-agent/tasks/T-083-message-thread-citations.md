# T-083 Â· Message Thread & Citation Viewer

**Status:** Done

**Phase:** 5 â€” Chat Frontend  
**Depends on:** T-080 (layout), T-081 (streaming), T-074 (sources API)  
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

Render the persisted message thread and provide an inline citation panel. Each assistant message may contain citations referencing source documents â€” clicking a citation opens a slide-over panel showing the source document excerpt, title, source name, and a link to the original document.

---

## 1. Types

### `src/components/chat/types.ts`

```ts
export interface Citation {
  id: string;
  document_id: string;
  source_id: string;
  source_name: string;
  document_title: string;
  excerpt: string;
  score: number;
  url?: string | null;
}

export interface Message {
  id: string;
  role: "user" | "assistant" | "system";
  content: string;
  created_at: string;
  citations?: Citation[];
}

export interface SessionMessagesResponse {
  session: {
    id: string;
    title: string;
    source_ids: string[];
  };
  messages: Message[];
}
```

---

## 2. `MessageThread` Component

### `src/components/chat/MessageThread.tsx`

```tsx
"use client";

import { useEffect, useRef, useState } from "react";
import { useQuery } from "@tanstack/react-query";
import { BotIcon, UserIcon } from "lucide-react";
import { cn } from "@/lib/utils";
import { apiClient } from "@/lib/api-client";
import { CitationPanel } from "./CitationPanel";
import type { Citation, Message, SessionMessagesResponse } from "./types";

interface MessageThreadProps {
  sessionId: string | null;
  streamingToken?: string;
  isStreaming?: boolean;
  extraMessages?: Message[];
}

async function fetchMessages(id: string): Promise<SessionMessagesResponse> {
  const res = await apiClient.get<SessionMessagesResponse>(
    `/chat/sessions/${id}`,
  );
  return res.data;
}

export function MessageThread({
  sessionId,
  streamingToken = "",
  isStreaming = false,
  extraMessages = [],
}: MessageThreadProps) {
  const bottomRef = useRef<HTMLDivElement>(null);
  const [openCitation, setOpenCitation] = useState<Citation | null>(null);

  const { data } = useQuery({
    queryKey: ["chat-session-messages", sessionId],
    queryFn: () => fetchMessages(sessionId!),
    enabled: !!sessionId,
    staleTime: 5_000,
  });

  const persisted: Message[] = data?.messages ?? [];
  const allMessages: Message[] = [...persisted, ...extraMessages];

  // Auto-scroll on new messages or streaming tokens
  useEffect(() => {
    bottomRef.current?.scrollIntoView({ behavior: "smooth" });
  }, [allMessages.length, streamingToken]);

  if (!sessionId) {
    return (
      <div className="flex flex-1 items-center justify-center">
        <p className="text-sm text-muted-foreground">
          Select or create a session to start chatting.
        </p>
      </div>
    );
  }

  return (
    <>
      <div
        className="flex flex-1 flex-col gap-4 overflow-y-auto px-4 py-4"
        role="log"
        aria-live="polite"
        aria-label="Conversation"
      >
        {allMessages.length === 0 && !isStreaming && (
          <p className="mt-8 text-center text-sm text-muted-foreground">
            No messages yet. Ask a question below.
          </p>
        )}

        {allMessages.map((msg) => (
          <MessageBubble
            key={msg.id}
            message={msg}
            onCitationClick={setOpenCitation}
          />
        ))}

        {/* Streaming bubble */}
        {isStreaming && (
          <div className="flex items-start gap-3">
            <div className="flex h-7 w-7 shrink-0 items-center justify-center rounded-full bg-muted">
              <BotIcon className="h-4 w-4 text-muted-foreground" />
            </div>
            <div className="max-w-[75%] rounded-2xl rounded-tl-sm bg-muted px-4 py-2.5">
              <p className="whitespace-pre-wrap break-words text-sm">
                {streamingToken}
                <span
                  className="ml-0.5 inline-block h-3.5 w-0.5 bg-foreground align-middle"
                  aria-hidden="true"
                />
              </p>
            </div>
          </div>
        )}

        <div ref={bottomRef} aria-hidden="true" />
      </div>

      {/* Citation side-panel */}
      <CitationPanel
        citation={openCitation}
        onClose={() => setOpenCitation(null)}
      />
    </>
  );
}

interface MessageBubbleProps {
  message: Message;
  onCitationClick: (c: Citation) => void;
}

function MessageBubble({ message, onCitationClick }: MessageBubbleProps) {
  const isUser = message.role === "user";

  return (
    <div
      className={cn(
        "flex items-start gap-3",
        isUser && "flex-row-reverse",
      )}
    >
      {/* Avatar */}
      <div
        className={cn(
          "flex h-7 w-7 shrink-0 items-center justify-center rounded-full",
          isUser ? "bg-primary" : "bg-muted",
        )}
        aria-hidden="true"
      >
        {isUser ? (
          <UserIcon className="h-4 w-4 text-primary-foreground" />
        ) : (
          <BotIcon className="h-4 w-4 text-muted-foreground" />
        )}
      </div>

      {/* Bubble */}
      <div
        className={cn(
          "max-w-[75%] rounded-2xl px-4 py-2.5",
          isUser
            ? "rounded-tr-sm bg-primary text-primary-foreground"
            : "rounded-tl-sm bg-muted",
        )}
      >
        <p className="whitespace-pre-wrap break-words text-sm">
          {message.content}
        </p>

        {/* Citations */}
        {!isUser && message.citations && message.citations.length > 0 && (
          <div
            className="mt-2 flex flex-wrap gap-1.5"
            role="list"
            aria-label="Citations"
          >
            {message.citations.map((c, idx) => (
              <button
                key={c.id}
                role="listitem"
                className={cn(
                  "inline-flex h-5 w-5 items-center justify-center rounded-full",
                  "bg-background/60 text-[10px] font-medium text-foreground",
                  "hover:bg-background focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring",
                )}
                onClick={() => onCitationClick(c)}
                aria-label={`View citation ${idx + 1}: ${c.document_title}`}
              >
                {idx + 1}
              </button>
            ))}
          </div>
        )}

        <time
          className={cn(
            "mt-1 block text-[10px]",
            isUser ? "text-primary-foreground/70" : "text-muted-foreground",
          )}
          dateTime={message.created_at}
          aria-label={new Date(message.created_at).toLocaleString()}
        >
          {new Date(message.created_at).toLocaleTimeString([], {
            hour: "2-digit",
            minute: "2-digit",
          })}
        </time>
      </div>
    </div>
  );
}
```

---

## 3. Citation Panel

### `src/components/chat/CitationPanel.tsx`

```tsx
"use client";

import { useEffect, useRef } from "react";
import {
  ExternalLinkIcon,
  FileTextIcon,
  XIcon,
} from "lucide-react";
import { Button } from "@/components/ui/button";
import { Badge } from "@/components/ui/badge";
import { ScrollArea } from "@/components/ui/scroll-area";
import { cn } from "@/lib/utils";
import type { Citation } from "./types";

interface CitationPanelProps {
  citation: Citation | null;
  onClose: () => void;
}

export function CitationPanel({ citation, onClose }: CitationPanelProps) {
  const closeRef = useRef<HTMLButtonElement>(null);

  // Focus close button when opened
  useEffect(() => {
    if (citation) closeRef.current?.focus();
  }, [citation]);

  // Close on Escape
  useEffect(() => {
    const handler = (e: KeyboardEvent) => {
      if (e.key === "Escape" && citation) onClose();
    };
    document.addEventListener("keydown", handler);
    return () => document.removeEventListener("keydown", handler);
  }, [citation, onClose]);

  return (
    <div
      className={cn(
        "fixed inset-y-0 right-0 z-50 flex w-full max-w-sm flex-col border-l border-border bg-background shadow-lg",
        "transition-transform duration-200",
        citation ? "translate-x-0" : "translate-x-full",
      )}
      role="complementary"
      aria-label="Citation details"
      aria-hidden={!citation}
    >
      {citation && (
        <>
          {/* Header */}
          <div className="flex items-start justify-between gap-2 border-b border-border px-4 py-3">
            <div className="flex min-w-0 flex-col">
              <p className="text-xs text-muted-foreground">Source document</p>
              <h2 className="truncate text-sm font-medium">
                {citation.document_title}
              </h2>
            </div>
            <Button
              ref={closeRef}
              size="icon"
              variant="ghost"
              className="h-8 w-8 shrink-0"
              onClick={onClose}
              aria-label="Close citation panel"
            >
              <XIcon className="h-4 w-4" />
            </Button>
          </div>

          {/* Body */}
          <ScrollArea className="flex-1 px-4 py-4">
            {/* Meta */}
            <div className="mb-4 flex flex-wrap items-center gap-2">
              <Badge variant="outline" className="gap-1 text-xs">
                <FileTextIcon className="h-3 w-3" />
                {citation.source_name}
              </Badge>
              <Badge variant="secondary" className="text-xs">
                Relevance: {Math.round(citation.score * 100)}%
              </Badge>
            </div>

            {/* Excerpt */}
            <blockquote
              className={cn(
                "rounded-md border-l-4 border-primary/40 bg-muted p-3",
                "text-sm leading-relaxed text-foreground",
              )}
            >
              {citation.excerpt}
            </blockquote>

            {/* External link */}
            {citation.url && (
              <a
                href={citation.url}
                target="_blank"
                rel="noopener noreferrer"
                className={cn(
                  "mt-4 inline-flex items-center gap-1.5 text-sm text-primary underline-offset-4",
                  "hover:underline focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring",
                )}
              >
                <ExternalLinkIcon className="h-3.5 w-3.5" />
                View original document
              </a>
            )}
          </ScrollArea>
        </>
      )}
    </div>
  );
}
```

---

## 4. Export barrel

### `src/components/chat/index.ts` (add exports)

```ts
export { MessageThread } from "./MessageThread";
export { CitationPanel } from "./CitationPanel";
export type { Citation, Message, SessionMessagesResponse } from "./types";
```

---

## 5. Tests

### `src/components/chat/__tests__/MessageThread.test.tsx`

```tsx
import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { MessageThread } from "../MessageThread";
import { vi } from "vitest";

vi.mock("@/lib/api-client", () => ({
  apiClient: {
    get: vi.fn().mockResolvedValue({
      data: {
        session: { id: "s1", title: "Test", source_ids: [] },
        messages: [
          {
            id: "m1",
            role: "user",
            content: "Hello",
            created_at: new Date().toISOString(),
          },
          {
            id: "m2",
            role: "assistant",
            content: "Hi there!",
            created_at: new Date().toISOString(),
            citations: [
              {
                id: "c1",
                document_id: "d1",
                source_id: "src1",
                source_name: "Wiki",
                document_title: "Getting Started",
                excerpt: "This guide explainsâ€¦",
                score: 0.92,
                url: null,
              },
            ],
          },
        ],
      },
    }),
  },
}));

function wrapper({ children }: { children: React.ReactNode }) {
  const qc = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  return <QueryClientProvider client={qc}>{children}</QueryClientProvider>;
}

test("renders persisted messages", async () => {
  render(<MessageThread sessionId="s1" />, { wrapper });
  expect(await screen.findByText("Hello")).toBeInTheDocument();
  expect(await screen.findByText("Hi there!")).toBeInTheDocument();
});

test("shows citation badge on assistant message", async () => {
  render(<MessageThread sessionId="s1" />, { wrapper });
  const citationBtn = await screen.findByRole("button", {
    name: /view citation 1/i,
  });
  expect(citationBtn).toBeInTheDocument();
});

test("opens citation panel on citation click", async () => {
  render(<MessageThread sessionId="s1" />, { wrapper });
  const citationBtn = await screen.findByRole("button", {
    name: /view citation 1/i,
  });
  await userEvent.click(citationBtn);
  expect(screen.getByText("Getting Started")).toBeInTheDocument();
  expect(screen.getByText(/This guide explains/)).toBeInTheDocument();
});

test("renders streaming bubble when isStreaming=true", () => {
  render(
    <MessageThread
      sessionId="s1"
      isStreaming
      streamingToken="Thinking about"
    />,
    { wrapper },
  );
  expect(screen.getByText(/Thinking about/)).toBeInTheDocument();
});

test("shows placeholder when no sessionId", () => {
  render(<MessageThread sessionId={null} />, { wrapper });
  expect(screen.getByText(/select or create a session/i)).toBeInTheDocument();
});
```

### `src/components/chat/__tests__/CitationPanel.test.tsx`

```tsx
import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { CitationPanel } from "../CitationPanel";
import { vi } from "vitest";

const citation = {
  id: "c1",
  document_id: "d1",
  source_id: "src1",
  source_name: "Confluence",
  document_title: "Architecture Overview",
  excerpt: "Our microservices follow clean architecture principles.",
  score: 0.88,
  url: "https://docs.example.com/arch",
};

test("renders citation content when open", () => {
  render(<CitationPanel citation={citation} onClose={vi.fn()} />);
  expect(screen.getByText("Architecture Overview")).toBeInTheDocument();
  expect(screen.getByText(/microservices follow/)).toBeInTheDocument();
  expect(screen.getByText(/88%/)).toBeInTheDocument();
});

test("calls onClose when close button clicked", async () => {
  const onClose = vi.fn();
  render(<CitationPanel citation={citation} onClose={onClose} />);
  await userEvent.click(screen.getByRole("button", { name: /close/i }));
  expect(onClose).toHaveBeenCalled();
});

test("calls onClose on Escape key", async () => {
  const onClose = vi.fn();
  render(<CitationPanel citation={citation} onClose={onClose} />);
  await userEvent.keyboard("{Escape}");
  expect(onClose).toHaveBeenCalled();
});

test("shows external link when url provided", () => {
  render(<CitationPanel citation={citation} onClose={vi.fn()} />);
  const link = screen.getByRole("link", { name: /view original/i });
  expect(link).toHaveAttribute("href", citation.url);
});

test("does not show external link when url is null", () => {
  render(
    <CitationPanel citation={{ ...citation, url: null }} onClose={vi.fn()} />,
  );
  expect(
    screen.queryByRole("link", { name: /view original/i }),
  ).not.toBeInTheDocument();
});

test("hidden when citation is null", () => {
  render(<CitationPanel citation={null} onClose={vi.fn()} />);
  const panel = screen.getByRole("complementary");
  expect(panel).toHaveAttribute("aria-hidden", "true");
});
```

---

## Acceptance Criteria

- [ ] Message thread renders `user` and `assistant` bubbles with correct alignment
- [ ] User messages: right-aligned, primary background
- [ ] Assistant messages: left-aligned, muted background
- [ ] Timestamps shown on every message bubble
- [ ] Streaming bubble appears in real time during SSE, removed on `done`
- [ ] Inline citation badges (numbered) shown on assistant messages
- [ ] Citation panel slides in from right-edge when badge clicked
- [ ] Citation panel shows: document title, source name, relevance%, excerpt, external link (if any)
- [ ] Citation panel closes via close button, clicking Escape, or opening a new citation
- [ ] Thread auto-scrolls to bottom on new message or streaming token
- [ ] `role="log"` and `aria-live="polite"` on thread container
- [ ] Citation panel is `role="complementary"` with `aria-hidden` when closed
- [ ] Zero layout shift when panel opens (panel overlays, doesn't reflow message list)
- [ ] All unit tests pass: `pnpm test`
