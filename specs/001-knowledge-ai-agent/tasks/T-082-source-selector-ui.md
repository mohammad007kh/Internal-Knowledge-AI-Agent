# T-082 · Source Selector & Conversation Context UI

**Phase:** 5 — Chat Frontend  
**Depends on:** T-080 (layout), T-074 (sources API)  
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

Allow users to scope a chat session to one or more knowledge sources. Implement:

1. **Source Selector Popover** — appears when creating a new session or editing an existing one  
2. **Source Chips** — show selected sources below the chat input bar  
3. **PATCH /chat/sessions/{id}** call to update `source_ids` on the session  

---

## 1. Source Selector Popover

### `src/components/chat/SourceSelector.tsx`

```tsx
"use client";

import { useCallback, useState } from "react";
import { useQuery } from "@tanstack/react-query";
import {
  CheckIcon,
  ChevronDownIcon,
  DatabaseIcon,
  SearchIcon,
} from "lucide-react";
import { Button } from "@/components/ui/button";
import {
  Popover,
  PopoverContent,
  PopoverTrigger,
} from "@/components/ui/popover";
import { Input } from "@/components/ui/input";
import { ScrollArea } from "@/components/ui/scroll-area";
import { Badge } from "@/components/ui/badge";
import { cn } from "@/lib/utils";
import { apiClient } from "@/lib/api-client";

export interface SourceSummary {
  id: string;
  name: string;
  type: string;
  document_count: number;
}

interface SourceResponse {
  items: SourceSummary[];
  total: number;
}

interface SourceSelectorProps {
  selectedIds: string[];
  onChange: (ids: string[]) => void;
  disabled?: boolean;
}

async function fetchSources(): Promise<SourceResponse> {
  const res = await apiClient.get("/sources?limit=100&status=ready");
  return res.data;
}

export function SourceSelector({
  selectedIds,
  onChange,
  disabled,
}: SourceSelectorProps) {
  const [open, setOpen] = useState(false);
  const [search, setSearch] = useState("");

  const { data } = useQuery({
    queryKey: ["sources-list"],
    queryFn: fetchSources,
    staleTime: 60_000,
    enabled: open,
  });

  const sources: SourceSummary[] = data?.items ?? [];
  const filtered = sources.filter((s) =>
    s.name.toLowerCase().includes(search.toLowerCase()),
  );

  const toggle = useCallback(
    (id: string) => {
      if (selectedIds.includes(id)) {
        onChange(selectedIds.filter((x) => x !== id));
      } else {
        onChange([...selectedIds, id]);
      }
    },
    [selectedIds, onChange],
  );

  const selectedCount = selectedIds.length;

  return (
    <Popover open={open} onOpenChange={setOpen}>
      <PopoverTrigger asChild>
        <Button
          variant="outline"
          size="sm"
          className="h-7 gap-1.5 rounded-full text-xs"
          disabled={disabled}
          aria-label={
            selectedCount > 0
              ? `${selectedCount} source${selectedCount !== 1 ? "s" : ""} selected`
              : "Select knowledge sources"
          }
        >
          <DatabaseIcon className="h-3.5 w-3.5" />
          {selectedCount > 0 ? (
            <span>
              {selectedCount} source{selectedCount !== 1 ? "s" : ""}
            </span>
          ) : (
            <span>All sources</span>
          )}
          <ChevronDownIcon className="h-3 w-3 text-muted-foreground" />
        </Button>
      </PopoverTrigger>

      <PopoverContent
        className="w-72 p-0"
        align="start"
        role="dialog"
        aria-label="Select knowledge sources"
      >
        {/* Search */}
        <div className="flex items-center border-b border-border px-3 py-2">
          <SearchIcon className="mr-2 h-4 w-4 shrink-0 text-muted-foreground" />
          <Input
            value={search}
            onChange={(e) => setSearch(e.target.value)}
            placeholder="Search sources…"
            className="h-7 border-0 p-0 text-sm shadow-none focus-visible:ring-0"
            aria-label="Search sources"
          />
        </div>

        {/* List */}
        <ScrollArea className="max-h-64">
          {filtered.length === 0 ? (
            <div className="p-4 text-center text-sm text-muted-foreground">
              {sources.length === 0 ? "No sources available." : "No matches."}
            </div>
          ) : (
            <ul role="listbox" aria-multiselectable="true" className="py-1">
              {filtered.map((source) => {
                const isSelected = selectedIds.includes(source.id);
                return (
                  <li
                    key={source.id}
                    role="option"
                    aria-selected={isSelected}
                    className={cn(
                      "flex cursor-pointer items-center gap-2 px-3 py-2 hover:bg-accent",
                      isSelected && "bg-accent/50",
                    )}
                    onClick={() => toggle(source.id)}
                  >
                    <div
                      className={cn(
                        "flex h-4 w-4 shrink-0 items-center justify-center rounded border border-border",
                        isSelected && "bg-primary border-primary",
                      )}
                      aria-hidden="true"
                    >
                      {isSelected && (
                        <CheckIcon className="h-3 w-3 text-primary-foreground" />
                      )}
                    </div>
                    <div className="flex-1 min-w-0">
                      <p className="truncate text-sm">{source.name}</p>
                      <p className="text-xs text-muted-foreground">
                        {source.type} · {source.document_count} docs
                      </p>
                    </div>
                  </li>
                );
              })}
            </ul>
          )}
        </ScrollArea>

        {/* Footer actions */}
        {selectedCount > 0 && (
          <div className="border-t border-border px-3 py-2">
            <Button
              variant="ghost"
              size="sm"
              className="h-7 w-full text-xs"
              onClick={() => onChange([])}
            >
              Clear selection
            </Button>
          </div>
        )}
      </PopoverContent>
    </Popover>
  );
}
```

---

## 2. Source Chips Bar

### `src/components/chat/SourceChips.tsx`

```tsx
"use client";

import { XIcon } from "lucide-react";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import type { SourceSummary } from "./SourceSelector";

interface SourceChipsProps {
  sources: SourceSummary[];
  onRemove: (id: string) => void;
  disabled?: boolean;
}

export function SourceChips({ sources, onRemove, disabled }: SourceChipsProps) {
  if (sources.length === 0) return null;

  return (
    <div
      className="flex flex-wrap gap-1.5 border-t border-border bg-background px-4 py-2"
      role="list"
      aria-label="Selected sources"
    >
      {sources.map((s) => (
        <Badge
          key={s.id}
          variant="secondary"
          className="flex items-center gap-1 pr-1"
          role="listitem"
        >
          <span className="max-w-[120px] truncate text-xs">{s.name}</span>
          <Button
            size="icon"
            variant="ghost"
            className="h-4 w-4 shrink-0 hover:bg-transparent"
            onClick={() => onRemove(s.id)}
            disabled={disabled}
            aria-label={`Remove source: ${s.name}`}
          >
            <XIcon className="h-3 w-3" />
          </Button>
        </Badge>
      ))}
    </div>
  );
}
```

---

## 3. `useSessionSources` Hook

### `src/components/chat/useSessionSources.ts`

```ts
"use client";

import { useCallback, useEffect, useState } from "react";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { toast } from "sonner";
import { apiClient } from "@/lib/api-client";
import type { SourceSummary } from "./SourceSelector";

interface UseSessionSourcesOptions {
  sessionId: string | null;
}

interface SessionResponse {
  session: { id: string; source_ids: string[] };
  messages: unknown[];
}

async function fetchSession(id: string): Promise<SessionResponse> {
  const res = await apiClient.get<SessionResponse>(`/chat/sessions/${id}`);
  return res.data;
}

async function updateSessionSources(
  id: string,
  sourceIds: string[],
): Promise<void> {
  await apiClient.patch(`/chat/sessions/${id}`, { source_ids: sourceIds });
}

async function fetchSourcesByIds(ids: string[]): Promise<SourceSummary[]> {
  if (ids.length === 0) return [];
  const qs = ids.map((id) => `ids=${id}`).join("&");
  const res = await apiClient.get<{ items: SourceSummary[] }>(
    `/sources?${qs}&limit=${ids.length}`,
  );
  return res.data.items;
}

export function useSessionSources({ sessionId }: UseSessionSourcesOptions) {
  const queryClient = useQueryClient();
  const [selectedIds, setSelectedIds] = useState<string[]>([]);
  const [selectedSources, setSelectedSources] = useState<SourceSummary[]>([]);

  // Load source IDs from session
  const { data: sessionData } = useQuery({
    queryKey: ["chat-session-messages", sessionId],
    queryFn: () => fetchSession(sessionId!),
    enabled: !!sessionId,
    staleTime: 10_000,
  });

  // Sync selected IDs from session data
  useEffect(() => {
    const ids = sessionData?.session.source_ids ?? [];
    setSelectedIds(ids);
  }, [sessionData?.session.source_ids]);

  // Fetch source details for chips display
  useEffect(() => {
    if (selectedIds.length === 0) {
      setSelectedSources([]);
      return;
    }
    fetchSourcesByIds(selectedIds)
      .then(setSelectedSources)
      .catch(() => setSelectedSources([]));
  }, [selectedIds]);

  const updateMutation = useMutation({
    mutationFn: (ids: string[]) => updateSessionSources(sessionId!, ids),
    onSuccess: () => {
      queryClient.invalidateQueries({
        queryKey: ["chat-session-messages", sessionId],
      });
    },
    onError: () => toast.error("Failed to update sources."),
  });

  const handleChange = useCallback(
    (ids: string[]) => {
      setSelectedIds(ids);
      if (sessionId) updateMutation.mutate(ids);
    },
    [sessionId, updateMutation],
  );

  const handleRemove = useCallback(
    (id: string) => {
      handleChange(selectedIds.filter((x) => x !== id));
    },
    [handleChange, selectedIds],
  );

  return {
    selectedIds,
    selectedSources,
    handleChange,
    handleRemove,
    isUpdating: updateMutation.isPending,
  };
}
```

---

## 4. Wire into ChatLayout / ChatInputBar

### `src/components/chat/ChatInputBar.tsx` — updated

Add source selector row above the textarea:

```tsx
"use client";

import { useCallback, useRef } from "react";
import { SendHorizonalIcon } from "lucide-react";
import { Button } from "@/components/ui/button";
import { Textarea } from "@/components/ui/textarea";
import { cn } from "@/lib/utils";
import { SourceSelector } from "./SourceSelector";
import { SourceChips } from "./SourceChips";
import { useSessionSources } from "./useSessionSources";

interface ChatInputBarProps {
  onSend: (text: string) => void;
  disabled?: boolean;
  sessionId: string | null;
}

const MAX_CHARS = 4000;

export function ChatInputBar({ onSend, disabled, sessionId }: ChatInputBarProps) {
  const textareaRef = useRef<HTMLTextAreaElement>(null);
  const { selectedIds, selectedSources, handleChange, handleRemove, isUpdating } =
    useSessionSources({ sessionId });

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
    <div className="border-t border-border bg-background">
      {/* Source chips */}
      <SourceChips
        sources={selectedSources}
        onRemove={handleRemove}
        disabled={disabled || isUpdating}
      />

      {/* Input row */}
      <form
        className="flex items-end gap-2 px-4 py-3"
        onSubmit={(e) => {
          e.preventDefault();
          handleSend();
        }}
        aria-label="Chat input"
      >
        <SourceSelector
          selectedIds={selectedIds}
          onChange={handleChange}
          disabled={disabled || !sessionId || isUpdating}
        />
        <Textarea
          ref={textareaRef}
          placeholder={
            sessionId
              ? "Ask a question… (Enter to send)"
              : "Select a session first…"
          }
          className={cn("max-h-40 min-h-[2.75rem] flex-1 resize-none rounded-xl")}
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
    </div>
  );
}
```

---

## 5. Tests

### `src/components/chat/__tests__/SourceSelector.test.tsx`

```tsx
import { render, screen, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { SourceSelector } from "../SourceSelector";
import { vi } from "vitest";

vi.mock("@/lib/api-client", () => ({
  apiClient: {
    get: vi.fn().mockResolvedValue({
      data: {
        items: [
          { id: "src1", name: "Confluence Wiki", type: "confluence", document_count: 45 },
          { id: "src2", name: "Jira Tickets", type: "jira", document_count: 120 },
        ],
        total: 2,
      },
    }),
  },
}));

function wrapper({ children }: { children: React.ReactNode }) {
  const qc = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  return <QueryClientProvider client={qc}>{children}</QueryClientProvider>;
}

test("renders trigger with 'All sources' when nothing selected", () => {
  render(<SourceSelector selectedIds={[]} onChange={vi.fn()} />, { wrapper });
  expect(screen.getByRole("button", { name: /all sources/i })).toBeInTheDocument();
});

test("opens popover and lists sources", async () => {
  render(<SourceSelector selectedIds={[]} onChange={vi.fn()} />, { wrapper });
  await userEvent.click(screen.getByRole("button", { name: /all sources/i }));
  expect(await screen.findByText("Confluence Wiki")).toBeInTheDocument();
  expect(screen.getByText("Jira Tickets")).toBeInTheDocument();
});

test("calls onChange when a source is toggled", async () => {
  const onChange = vi.fn();
  render(<SourceSelector selectedIds={[]} onChange={onChange} />, { wrapper });
  await userEvent.click(screen.getByRole("button", { name: /all sources/i }));
  const item = await screen.findByRole("option", { name: /confluence wiki/i });
  await userEvent.click(item);
  expect(onChange).toHaveBeenCalledWith(["src1"]);
});
```

### `src/components/chat/__tests__/SourceChips.test.tsx`

```tsx
import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { SourceChips } from "../SourceChips";
import { vi } from "vitest";

const sources = [
  { id: "s1", name: "Confluence Wiki", type: "confluence", document_count: 10 },
  { id: "s2", name: "Jira", type: "jira", document_count: 5 },
];

test("renders source badges", () => {
  render(<SourceChips sources={sources} onRemove={vi.fn()} />);
  expect(screen.getByText("Confluence Wiki")).toBeInTheDocument();
  expect(screen.getByText("Jira")).toBeInTheDocument();
});

test("calls onRemove when X clicked", async () => {
  const onRemove = vi.fn();
  render(<SourceChips sources={sources} onRemove={onRemove} />);
  await userEvent.click(
    screen.getByRole("button", { name: /remove source: confluence wiki/i }),
  );
  expect(onRemove).toHaveBeenCalledWith("s1");
});

test("renders nothing when sources is empty", () => {
  const { container } = render(<SourceChips sources={[]} onRemove={vi.fn()} />);
  expect(container.firstChild).toBeNull();
});
```

---

## Acceptance Criteria

- [ ] Source selector popover opens from chat input bar
- [ ] Popover lists only `status=ready` sources
- [ ] Selecting a source updates `session.source_ids` via `PATCH /chat/sessions/{id}`
- [ ] Source chips appear below selector for selected sources
- [ ] Removing a chip deselects the source and patches the session
- [ ] "All sources" label shown when no source selected (means unrestricted search)
- [ ] Empty state message when no sources available
- [ ] Selector and chips are disabled while a message is pending
- [ ] ARIA roles: popover list is `role="listbox"`, items `role="option"` with `aria-selected`
- [ ] Unit tests pass: `pnpm test`
