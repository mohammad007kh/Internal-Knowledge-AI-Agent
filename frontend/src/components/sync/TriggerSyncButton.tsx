"use client";

import { useState } from "react";
import { toast } from "sonner";
import { RefreshCw } from "lucide-react";
import { Button } from "@/components/ui/button";
import { useSyncJob } from "@/hooks/useSyncJob";

interface TriggerSyncButtonProps {
  sourceId: string;
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
        description: `Job ${jobId.slice(0, 8)}… is queued.`,
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
      <span className="ml-1">{isRunning ? "Syncing…" : "Sync Now"}</span>
    </Button>
  );
}
