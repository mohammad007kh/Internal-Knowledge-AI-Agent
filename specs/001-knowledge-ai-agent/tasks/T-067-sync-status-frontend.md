# T-067 â€” Sync Status Frontend Components

**Status:** Done

## Context
```
Next.js 15 App Router Â· shadcn/ui Â· Tailwind CSS v4
React Context Â· TanStack Query v5 Â· react-hook-form Â· Zod
Dark mode Â· responsive Â· WCAG-AA Â· no animations Â· Lucide icons Â· Sonner toasts
snake_case vars/files/tables Â· PascalCase classes Â· SCREAMING_SNAKE_CASE constants
```

## Goal
Add three frontend artefacts to the Source Management UI:

1. `SyncStatusBadge` â€” colour-coded status pill
2. `TriggerSyncButton` â€” POST handler with polling trigger
3. `useSyncJob` â€” TanStack Query hook that polls while PENDING|RUNNING

---

## Acceptance Criteria

- [ ] `SyncStatusBadge` renders correct icon + colour for each of the 4 states
- [ ] RUNNING badge shows a spinning icon (CSS `animate-spin` only â€” no JS animation library)
- [ ] `TriggerSyncButton` POSTs to `/api/v1/sources/{id}/sync`, shows success/error Sonner toast
- [ ] Button is disabled while RUNNING or while the POST request is in-flight
- [ ] `useSyncJob` polls every 3 s when status is `pending` or `running`; stops when terminal
- [ ] All components pass `aria-label` / role attributes for WCAG-AA screen readers

---

## 1  `SyncStatusBadge` â€” `src/components/sync/SyncStatusBadge.tsx`

```tsx
"use client";

import { cn } from "@/lib/utils";
import {
  CheckCircle2,
  Clock,
  Loader2,
  XCircle,
} from "lucide-react";

type SyncStatus = "pending" | "running" | "success" | "failed";

interface SyncStatusBadgeProps {
  status: SyncStatus;
  className?: string;
}

const CONFIG: Record<
  SyncStatus,
  { label: string; icon: React.ElementType; colour: string }
> = {
  pending: {
    label: "Pending",
    icon: Clock,
    colour: "bg-gray-100 text-gray-600 dark:bg-gray-800 dark:text-gray-400",
  },
  running: {
    label: "Running",
    icon: Loader2,
    colour: "bg-blue-100 text-blue-700 dark:bg-blue-900/30 dark:text-blue-400",
  },
  success: {
    label: "Success",
    icon: CheckCircle2,
    colour:
      "bg-green-100 text-green-700 dark:bg-green-900/30 dark:text-green-400",
  },
  failed: {
    label: "Failed",
    icon: XCircle,
    colour: "bg-red-100 text-red-700 dark:bg-red-900/30 dark:text-red-400",
  },
};

export function SyncStatusBadge({ status, className }: SyncStatusBadgeProps) {
  const { label, icon: Icon, colour } = CONFIG[status];

  return (
    <span
      role="status"
      aria-label={`Sync status: ${label}`}
      className={cn(
        "inline-flex items-center gap-1 rounded-full px-2 py-0.5 text-xs font-medium",
        colour,
        className,
      )}
    >
      <Icon
        size={12}
        aria-hidden="true"
        className={status === "running" ? "animate-spin" : undefined}
      />
      {label}
    </span>
  );
}
```

---

## 2  `useSyncJob` â€” `src/hooks/useSyncJob.ts`

```ts
"use client";

import { useQuery } from "@tanstack/react-query";

const TERMINAL = new Set(["success", "failed"]);
const POLL_INTERVAL_MS = 3_000;

export interface SyncJob {
  id: string;
  source_id: string;
  status: "pending" | "running" | "success" | "failed";
  documents_synced: number;
  chunks_created: number;
  started_at: string | null;
  finished_at: string | null;
  error_message: string | null;
  created_at: string;
}

async function fetchSyncJob(jobId: string): Promise<SyncJob> {
  const res = await fetch(`/api/v1/sync-jobs/${jobId}`, {
    credentials: "include",
  });
  if (!res.ok) {
    const err = await res.json().catch(() => ({}));
    throw new Error(err?.detail ?? `HTTP ${res.status}`);
  }
  return res.json() as Promise<SyncJob>;
}

export function useSyncJob(jobId: string | null) {
  return useQuery<SyncJob>({
    queryKey: ["sync-job", jobId],
    queryFn: () => fetchSyncJob(jobId!),
    enabled: Boolean(jobId),
    refetchInterval(query) {
      const status = query.state.data?.status;
      if (!status || TERMINAL.has(status)) return false;
      return POLL_INTERVAL_MS;
    },
    staleTime: 0,
  });
}
```

---

## 3  `TriggerSyncButton` â€” `src/components/sync/TriggerSyncButton.tsx`

```tsx
"use client";

import { useState } from "react";
import { toast } from "sonner";
import { RefreshCw } from "lucide-react";
import { Button } from "@/components/ui/button";
import { useSyncJob } from "@/hooks/useSyncJob";

interface TriggerSyncButtonProps {
  sourceId: string;
  /** Optional: if a latest job is already known, pass it so the button is
   *  disabled immediately while that job is running. */
  currentJobId?: string | null;
}

async function postTriggerSync(sourceId: string): Promise<string> {
  const res = await fetch(`/api/v1/sources/${sourceId}/sync`, {
    method: "POST",
    credentials: "include",
  });
  if (!res.ok) {
    const err = await res.json().catch(() => ({}));
    throw new Error(err?.detail?.detail ?? `HTTP ${res.status}`);
  }
  const job = await res.json();
  return job.id as string;
}

export function TriggerSyncButton({
  sourceId,
  currentJobId,
}: TriggerSyncButtonProps) {
  const [activeJobId, setActiveJobId] = useState<string | null>(
    currentJobId ?? null,
  );
  const [posting, setPosting] = useState(false);

  const { data: activeJob } = useSyncJob(activeJobId);

  const isRunning =
    activeJob?.status === "running" || activeJob?.status === "pending";

  const disabled = posting || isRunning;

  async function handleClick() {
    setPosting(true);
    try {
      const jobId = await postTriggerSync(sourceId);
      setActiveJobId(jobId);
      toast.success("Sync triggered", {
        description: `Job ${jobId.slice(0, 8)}â€¦ is queued.`,
      });
    } catch (err) {
      const msg = err instanceof Error ? err.message : "Unknown error";
      toast.error("Failed to trigger sync", { description: msg });
    } finally {
      setPosting(false);
    }
  }

  return (
    <Button
      variant="outline"
      size="sm"
      onClick={handleClick}
      disabled={disabled}
      aria-label={isRunning ? "Sync in progress" : "Trigger sync"}
    >
      <RefreshCw
        size={14}
        aria-hidden="true"
        className={isRunning ? "animate-spin" : undefined}
      />
      <span className="ml-1">{isRunning ? "Syncingâ€¦" : "Sync Now"}</span>
    </Button>
  );
}
```

---

## 4  Integration in `SourceRow` â€” patch `src/components/sources/SourceRow.tsx`

```tsx
// Add these imports:
import { SyncStatusBadge } from "@/components/sync/SyncStatusBadge";
import { TriggerSyncButton } from "@/components/sync/TriggerSyncButton";

// Inside the row render, after the source name:
<td className="px-4 py-3">
  {source.latest_job ? (
    <SyncStatusBadge status={source.latest_job.status} />
  ) : (
    <span className="text-xs text-muted-foreground">Never synced</span>
  )}
</td>
<td className="px-4 py-3 text-right">
  <TriggerSyncButton
    sourceId={source.id}
    currentJobId={source.latest_job?.id ?? null}
  />
</td>
```

---

## 5  Backend schema extension â€” `GET /sources` list

Ensure the `SourceListItem` schema returned by the backend includes:

```python
# app/schemas/source.py â€” append field to SourceListItem
from app.schemas.sync_job import SyncJobResponse

class SourceListItem(BaseModel):
    id: UUID
    name: str
    source_type: str
    is_active: bool
    latest_job: SyncJobResponse | None = None

    model_config = ConfigDict(from_attributes=True)
```

And in `SourceService.list_for_user()`, join-load the latest sync job:

```python
# In source_service.py list_for_user():
stmt = (
    select(Source)
    .options(
        selectinload(Source.sync_jobs.of_type(SyncJob))
        .order_by(SyncJob.created_at.desc())
        .limit(1)
    )
    .where(Source.owner_id == owner_id)
    .order_by(Source.created_at.desc())
)
```

---

## 6  File Summary

| File | Action |
|---|---|
| `src/components/sync/SyncStatusBadge.tsx` | **CREATE** |
| `src/components/sync/TriggerSyncButton.tsx` | **CREATE** |
| `src/hooks/useSyncJob.ts` | **CREATE** |
| `src/components/sources/SourceRow.tsx` | **PATCH** â€” add badge + button cells |
| `app/schemas/source.py` | **PATCH** â€” `latest_job` field on `SourceListItem` |
| `app/services/source_service.py` | **PATCH** â€” join-load latest job |

---

## Phase / Requirement Mapping

| Requirement | Satisfied by |
|---|---|
| FR-030 â€” trigger sync from UI | `TriggerSyncButton` |
| FR-033 â€” observe sync status | `SyncStatusBadge` + `useSyncJob` polling |
| WCAG-AA | `role="status"`, `aria-label`, `aria-hidden` |
| Dark mode | Tailwind dark: variants in `CONFIG` |
