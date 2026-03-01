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
    colour: "bg-green-100 text-green-700 dark:bg-green-900/30 dark:text-green-400",
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
