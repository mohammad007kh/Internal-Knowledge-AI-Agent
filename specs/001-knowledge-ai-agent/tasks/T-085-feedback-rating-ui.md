# T-085 · Feedback & Rating UI

**Phase:** 5 — Chat Frontend  
**Depends on:** T-083 (message thread), T-076 (chat API)  
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

Allow users to rate any **assistant** message as helpful (👍) or unhelpful (👎) and optionally add a short comment. The rating is stored via `POST /chat/sessions/{session_id}/messages/{message_id}/feedback`.

The rating also flows to Langfuse as a score on the pipeline trace linked to that message.

---

## 1. API Contract

```
POST /chat/sessions/{session_id}/messages/{message_id}/feedback
Body: { "rating": 1 | -1, "comment": string | null }
Response 201: { "id": string, "rating": 1 | -1, "comment": string | null }
Response 409: Already rated (allow updating — PATCH, or 409 + toast)
```

The frontend uses an **optimistic** toggle: clicking 👍 on an already-👍-rated message removes the rating (sets to null).

---

## 2. `FeedbackButtons` Component

### `src/components/chat/FeedbackButtons.tsx`

```tsx
"use client";

import { useCallback, useState } from "react";
import { ThumbsDownIcon, ThumbsUpIcon } from "lucide-react";
import { useMutation } from "@tanstack/react-query";
import { toast } from "sonner";
import { Button } from "@/components/ui/button";
import {
  Popover,
  PopoverContent,
  PopoverTrigger,
} from "@/components/ui/popover";
import { Textarea } from "@/components/ui/textarea";
import { cn } from "@/lib/utils";
import { apiClient } from "@/lib/api-client";

// ─── Types ───────────────────────────────────────────────────────────────────

type Rating = 1 | -1 | null;

interface FeedbackPayload {
  rating: 1 | -1;
  comment: string | null;
}

interface FeedbackResponse {
  id: string;
  rating: 1 | -1;
  comment: string | null;
}

// ─── API ──────────────────────────────────────────────────────────────────────

async function submitFeedback(
  sessionId: string,
  messageId: string,
  payload: FeedbackPayload,
): Promise<FeedbackResponse> {
  const res = await apiClient.post<FeedbackResponse>(
    `/chat/sessions/${sessionId}/messages/${messageId}/feedback`,
    payload,
  );
  return res.data;
}

// ─── Component ───────────────────────────────────────────────────────────────

interface FeedbackButtonsProps {
  sessionId: string;
  messageId: string;
  /** Pre-existing rating to show on mount (from persisted data) */
  initialRating?: Rating;
}

const MAX_COMMENT = 500;

export function FeedbackButtons({
  sessionId,
  messageId,
  initialRating = null,
}: FeedbackButtonsProps) {
  const [rating, setRating] = useState<Rating>(initialRating);
  const [comment, setComment] = useState("");
  const [thumbsDownOpen, setThumbsDownOpen] = useState(false);

  const mutation = useMutation({
    mutationFn: (payload: FeedbackPayload) =>
      submitFeedback(sessionId, messageId, payload),
    onSuccess: (data) => {
      setRating(data.rating);
      setThumbsDownOpen(false);
      setComment("");
    },
    onError: () => toast.error("Failed to save feedback."),
  });

  // Thumbs-up: toggles between 1 and null
  const handleThumbsUp = useCallback(() => {
    if (mutation.isPending) return;
    if (rating === 1) {
      // Toggle OFF: not supported by simple POST API — show as already submitted
      // We keep the optimistic state; API doesn't deactivate ratings.
      return;
    }
    setRating(1); // optimistic
    mutation.mutate({ rating: 1, comment: null });
  }, [rating, mutation]);

  // Thumbs-down: opens popover to collect comment (optional)
  const handleThumbsDownSubmit = useCallback(() => {
    if (mutation.isPending) return;
    mutation.mutate({ rating: -1, comment: comment.trim() || null });
  }, [comment, mutation]);

  return (
    <div className="mt-1 flex items-center gap-0.5" aria-label="Message feedback">
      {/* Thumbs up */}
      <Button
        size="icon"
        variant="ghost"
        className={cn(
          "h-6 w-6",
          rating === 1 && "text-green-600 dark:text-green-400",
        )}
        onClick={handleThumbsUp}
        disabled={mutation.isPending || rating !== null}
        aria-label="Mark as helpful"
        aria-pressed={rating === 1}
      >
        <ThumbsUpIcon className="h-3.5 w-3.5" />
      </Button>

      {/* Thumbs down with comment popover */}
      <Popover
        open={thumbsDownOpen}
        onOpenChange={(o) => {
          if (rating !== null) return; // already rated
          setThumbsDownOpen(o);
        }}
      >
        <PopoverTrigger asChild>
          <Button
            size="icon"
            variant="ghost"
            className={cn(
              "h-6 w-6",
              rating === -1 && "text-red-600 dark:text-red-400",
            )}
            disabled={mutation.isPending || rating !== null}
            aria-label="Mark as unhelpful"
            aria-pressed={rating === -1}
          >
            <ThumbsDownIcon className="h-3.5 w-3.5" />
          </Button>
        </PopoverTrigger>

        <PopoverContent
          className="w-72 p-3"
          side="top"
          align="start"
          role="dialog"
          aria-label="Provide feedback details"
        >
          <p className="mb-2 text-xs font-medium text-foreground">
            What went wrong? <span className="font-normal text-muted-foreground">(optional)</span>
          </p>
          <Textarea
            value={comment}
            onChange={(e) => setComment(e.target.value)}
            placeholder="e.g. Missing information, incorrect answer…"
            className="mb-2 h-20 resize-none text-xs"
            maxLength={MAX_COMMENT}
            aria-label="Feedback comment"
          />
          <div className="flex items-center justify-between">
            <span className="text-[10px] text-muted-foreground">
              {comment.length}/{MAX_COMMENT}
            </span>
            <div className="flex gap-1.5">
              <Button
                size="sm"
                variant="ghost"
                className="h-7 text-xs"
                onClick={() => setThumbsDownOpen(false)}
              >
                Cancel
              </Button>
              <Button
                size="sm"
                className="h-7 text-xs"
                onClick={handleThumbsDownSubmit}
                disabled={mutation.isPending}
              >
                Submit
              </Button>
            </div>
          </div>
        </PopoverContent>
      </Popover>
    </div>
  );
}
```

---

## 3. Wire into `MessageBubble`

In `src/components/chat/MessageThread.tsx`, update the `MessageBubble` component to include `FeedbackButtons` for assistant messages:

```tsx
import { FeedbackButtons } from "./FeedbackButtons";

// Inside MessageBubble, after the <p> content and citations:
{!isUser && (
  <FeedbackButtons
    sessionId={/* pass from parent */}
    messageId={message.id}
    initialRating={
      (message as Message & { feedback?: { rating: 1 | -1 } | null })
        ?.feedback?.rating ?? null
    }
  />
)}
```

Update `MessageThreadProps` to accept `sessionId`:

```tsx
interface MessageThreadProps {
  sessionId: string | null;
  streamingToken?: string;
  isStreaming?: boolean;
  extraMessages?: Message[];
}
```

Pass `sessionId` down to each `MessageBubble`:

```tsx
{allMessages.map((msg) => (
  <MessageBubble
    key={msg.id}
    message={msg}
    sessionId={sessionId ?? ""}
    onCitationClick={setOpenCitation}
  />
))}
```

Update `MessageBubbleProps`:

```tsx
interface MessageBubbleProps {
  message: Message;
  sessionId: string;
  onCitationClick: (c: Citation) => void;
}
```

---

## 4. Update `Message` type

In `src/components/chat/types.ts`, add nullable feedback field:

```ts
export interface MessageFeedback {
  id: string;
  rating: 1 | -1;
  comment: string | null;
}

export interface Message {
  id: string;
  role: "user" | "assistant" | "system";
  content: string;
  created_at: string;
  citations?: Citation[];
  feedback?: MessageFeedback | null;
}
```

---

## 5. Tests

### `src/components/chat/__tests__/FeedbackButtons.test.tsx`

```tsx
import { render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { FeedbackButtons } from "../FeedbackButtons";
import { vi } from "vitest";

vi.mock("@/lib/api-client", () => ({
  apiClient: {
    post: vi.fn().mockResolvedValue({
      data: { id: "fb1", rating: 1, comment: null },
    }),
  },
}));

function wrapper({ children }: { children: React.ReactNode }) {
  const qc = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  return <QueryClientProvider client={qc}>{children}</QueryClientProvider>;
}

test("renders thumbs up and thumbs down buttons", () => {
  render(
    <FeedbackButtons sessionId="s1" messageId="m1" />,
    { wrapper },
  );
  expect(
    screen.getByRole("button", { name: /mark as helpful/i }),
  ).toBeInTheDocument();
  expect(
    screen.getByRole("button", { name: /mark as unhelpful/i }),
  ).toBeInTheDocument();
});

test("thumbs up calls API and disables buttons after success", async () => {
  const { apiClient } = await import("@/lib/api-client");
  render(<FeedbackButtons sessionId="s1" messageId="m1" />, { wrapper });
  await userEvent.click(
    screen.getByRole("button", { name: /mark as helpful/i }),
  );
  await waitFor(() => {
    expect(apiClient.post).toHaveBeenCalledWith(
      "/chat/sessions/s1/messages/m1/feedback",
      { rating: 1, comment: null },
    );
  });
  // After rating, both buttons should be disabled
  expect(
    screen.getByRole("button", { name: /mark as helpful/i }),
  ).toBeDisabled();
});

test("thumbs down opens popover", async () => {
  render(<FeedbackButtons sessionId="s1" messageId="m1" />, { wrapper });
  await userEvent.click(
    screen.getByRole("button", { name: /mark as unhelpful/i }),
  );
  expect(
    screen.getByRole("dialog", { name: /provide feedback details/i }),
  ).toBeInTheDocument();
});

test("thumbs down submits with comment", async () => {
  const { apiClient } = await import("@/lib/api-client");
  (apiClient.post as ReturnType<typeof vi.fn>).mockResolvedValueOnce({
    data: { id: "fb2", rating: -1, comment: "Wrong answer" },
  });
  render(<FeedbackButtons sessionId="s1" messageId="m1" />, { wrapper });
  await userEvent.click(
    screen.getByRole("button", { name: /mark as unhelpful/i }),
  );
  await userEvent.type(
    screen.getByRole("textbox", { name: /feedback comment/i }),
    "Wrong answer",
  );
  await userEvent.click(screen.getByRole("button", { name: /^submit$/i }));
  await waitFor(() => {
    expect(apiClient.post).toHaveBeenCalledWith(
      "/chat/sessions/s1/messages/m1/feedback",
      { rating: -1, comment: "Wrong answer" },
    );
  });
});

test("shows initial rating state when pre-existing rating provided", () => {
  render(
    <FeedbackButtons sessionId="s1" messageId="m1" initialRating={1} />,
    { wrapper },
  );
  expect(
    screen.getByRole("button", { name: /mark as helpful/i }),
  ).toBeDisabled();
});
```

---

## Acceptance Criteria

- [ ] 👍 and 👎 buttons render below every assistant message (not user messages)
- [ ] Clicking 👍 immediately disables both buttons (single-use) and submits `{ rating: 1, comment: null }`
- [ ] Clicking 👎 opens a popover with an optional comment textarea
- [ ] Submitting 👎 popover sends `{ rating: -1, comment }` and closes popover
- [ ] Cancel button in 👎 popover closes without submitting
- [ ] After submitting, rated button turns green (👍) or red (👎)
- [ ] Both buttons are disabled once any rating is submitted
- [ ] API error shows Sonner toast
- [ ] `initialRating` prop reflects previously persisted rating on component mount
- [ ] `aria-pressed` attribute reflects current rating state
- [ ] Buttons visible but small, not intrusive — appear below citation row
- [ ] Unit tests pass: `pnpm test`
