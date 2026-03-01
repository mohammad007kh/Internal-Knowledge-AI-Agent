"use client";

import { SyncStatusBadge } from "@/components/sync/SyncStatusBadge";
import { TriggerSyncButton } from "@/components/sync/TriggerSyncButton";

type SyncStatus = "pending" | "running" | "success" | "failed";

interface LatestJob {
  id: string;
  status: SyncStatus;
}

interface SourceRowProps {
  source: {
    id: string;
    name: string;
    source_type: string;
    is_active: boolean;
    created_at: string;
    latest_job?: LatestJob | null;
  };
}

export function SourceRow({ source }: SourceRowProps) {
  return (
    <tr className="border-b last:border-0 hover:bg-muted/50 transition-colors">
      <td className="px-4 py-3 font-medium">{source.name}</td>
      <td className="px-4 py-3">
        <span className="rounded bg-muted px-2 py-0.5 text-xs font-mono">
          {source.source_type}
        </span>
      </td>
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
    </tr>
  );
}
