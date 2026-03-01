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
