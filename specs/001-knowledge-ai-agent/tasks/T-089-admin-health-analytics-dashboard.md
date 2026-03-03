# T-089 Â· Admin â€” System Health & Analytics Dashboard

**Status:** Done

**Phase:** 5 â€” Admin Frontend  
**Depends on:** T-080 (layout), T-055 (health API), T-059 (analytics API)  
**Blocks:** T-090

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

> **No charting library.** All visualisations use native `<canvas>` via the `useBarChart` hook below, or plain data tables. No Recharts / Chart.js / Victory dependency.

---

## Objective

The admin overview page at `/admin` shows:

1. **System health cards** â€” live service status (DB, Redis, MinIO, Celery)
2. **Key metrics** â€” total users, active sources, total documents indexed, queries (7d)
3. **Recent activity feed** â€” last 20 system events (sync completions, errors, user logins)
4. **Query volume bar chart** â€” queries per day for the last 14 days (canvas)
5. **Top sources by query count** â€” simple sorted table

Auto-refreshes every 30 seconds.

---

## 1. Routes and Pages

### `src/app/(app)/admin/page.tsx`

```tsx
import { Suspense } from "react";
import { HealthCards } from "@/components/admin/HealthCards";
import { MetricsCards } from "@/components/admin/MetricsCards";
import { QueryVolumeChart } from "@/components/admin/QueryVolumeChart";
import { TopSourcesTable } from "@/components/admin/TopSourcesTable";
import { ActivityFeed } from "@/components/admin/ActivityFeed";

export const metadata = { title: "Dashboard â€” Admin" };

export default function AdminDashboardPage() {
  return (
    <div className="space-y-6 p-6">
      <h1 className="text-xl font-semibold">System Overview</h1>

      {/* Row 1: Service health */}
      <Suspense fallback={<div className="h-24 animate-pulse rounded-md bg-muted" />}>
        <HealthCards />
      </Suspense>

      {/* Row 2: Metrics */}
      <Suspense fallback={<div className="h-24 animate-pulse rounded-md bg-muted" />}>
        <MetricsCards />
      </Suspense>

      {/* Row 3: Chart + Top sources */}
      <div className="grid grid-cols-1 gap-6 lg:grid-cols-2">
        <Suspense fallback={<div className="h-56 animate-pulse rounded-md bg-muted" />}>
          <QueryVolumeChart />
        </Suspense>
        <Suspense fallback={<div className="h-56 animate-pulse rounded-md bg-muted" />}>
          <TopSourcesTable />
        </Suspense>
      </div>

      {/* Row 4: Activity feed */}
      <Suspense fallback={<div className="h-48 animate-pulse rounded-md bg-muted" />}>
        <ActivityFeed />
      </Suspense>
    </div>
  );
}
```

---

## 2. API Types

```ts
// src/types/admin-analytics.ts

export interface HealthCheck {
  service: "database" | "redis" | "minio" | "celery";
  status: "ok" | "degraded" | "down";
  latency_ms: number | null;
  detail: string | null;
}

export interface SystemHealth {
  checks: HealthCheck[];
  checked_at: string;
}

export interface SystemMetrics {
  total_users: number;
  active_users_7d: number;
  active_sources: number;
  total_documents: number;
  queries_7d: number;
  avg_response_time_ms: number;
}

export interface DailyQueryCount {
  date: string;   // ISO date "2026-02-15"
  count: number;
}

export interface SourceQueryStat {
  source_id: string;
  source_name: string;
  query_count: number;
}

export interface ActivityEvent {
  id: string;
  event_type: string;
  message: string;
  severity: "info" | "warning" | "error";
  created_at: string;
}
```

---

## 3. Health Cards

### `src/components/admin/HealthCards.tsx`

```tsx
"use client";

import { useQuery } from "@tanstack/react-query";
import {
  CheckCircleIcon,
  AlertTriangleIcon,
  XCircleIcon,
  DatabaseIcon,
  ZapIcon,
  HardDriveIcon,
  CpuIcon,
} from "lucide-react";
import { cn } from "@/lib/utils";
import { apiClient } from "@/lib/api-client";
import type { SystemHealth, HealthCheck } from "@/types/admin-analytics";

const SERVICE_ICON: Record<string, React.ComponentType<{ className?: string }>> = {
  database: DatabaseIcon,
  redis: ZapIcon,
  minio: HardDriveIcon,
  celery: CpuIcon,
};

const STATUS_STYLES: Record<
  HealthCheck["status"],
  { icon: React.ComponentType<{ className?: string }>; color: string; bg: string }
> = {
  ok: {
    icon: CheckCircleIcon,
    color: "text-green-700 dark:text-green-400",
    bg: "bg-green-50 dark:bg-green-950/30",
  },
  degraded: {
    icon: AlertTriangleIcon,
    color: "text-amber-700 dark:text-amber-400",
    bg: "bg-amber-50 dark:bg-amber-950/30",
  },
  down: {
    icon: XCircleIcon,
    color: "text-red-700 dark:text-red-400",
    bg: "bg-red-50 dark:bg-red-950/30",
  },
};

export function HealthCards() {
  const { data } = useQuery<SystemHealth>({
    queryKey: ["admin-health"],
    queryFn: async () => {
      const res = await apiClient.get<SystemHealth>("/health/detail");
      return res.data;
    },
    refetchInterval: 30_000,
    staleTime: 10_000,
  });

  const checks = data?.checks ?? [];

  return (
    <section aria-label="Service health">
      <h2 className="mb-3 text-sm font-medium text-muted-foreground">
        Service Status
      </h2>
      <div className="grid grid-cols-2 gap-3 sm:grid-cols-4">
        {(["database", "redis", "minio", "celery"] as const).map((svc) => {
          const check = checks.find((c) => c.service === svc);
          const status: HealthCheck["status"] = check?.status ?? "down";
          const styles = STATUS_STYLES[status];
          const ServiceIcon = SERVICE_ICON[svc];
          const StatusIcon = styles.icon;

          return (
            <div
              key={svc}
              className={cn(
                "flex flex-col gap-1.5 rounded-lg border border-border p-3",
                styles.bg,
              )}
              role="status"
              aria-label={`${svc} is ${status}`}
            >
              <div className="flex items-center justify-between">
                <ServiceIcon className="h-4 w-4 text-muted-foreground" />
                <StatusIcon className={cn("h-4 w-4", styles.color)} />
              </div>
              <p className="text-xs font-medium capitalize">{svc}</p>
              <p className={cn("text-xs capitalize", styles.color)}>{status}</p>
              {check?.latency_ms != null && (
                <p className="text-[10px] text-muted-foreground">
                  {check.latency_ms}ms
                </p>
              )}
            </div>
          );
        })}
      </div>
    </section>
  );
}
```

---

## 4. Metrics Cards

### `src/components/admin/MetricsCards.tsx`

```tsx
"use client";

import { useQuery } from "@tanstack/react-query";
import {
  UsersIcon,
  DatabaseIcon,
  FileTextIcon,
  MessageSquareIcon,
  ClockIcon,
} from "lucide-react";
import { apiClient } from "@/lib/api-client";
import type { SystemMetrics } from "@/types/admin-analytics";

interface MetricCard {
  label: string;
  value: string | number;
  sub?: string;
  icon: React.ComponentType<{ className?: string }>;
}

export function MetricsCards() {
  const { data } = useQuery<SystemMetrics>({
    queryKey: ["admin-metrics"],
    queryFn: async () => {
      const res = await apiClient.get<SystemMetrics>("/admin/analytics/metrics");
      return res.data;
    },
    refetchInterval: 30_000,
    staleTime: 10_000,
  });

  const cards: MetricCard[] = [
    {
      label: "Total users",
      value: data?.total_users.toLocaleString() ?? "â€”",
      sub: `${data?.active_users_7d ?? 0} active (7d)`,
      icon: UsersIcon,
    },
    {
      label: "Active sources",
      value: data?.active_sources.toLocaleString() ?? "â€”",
      icon: DatabaseIcon,
    },
    {
      label: "Documents indexed",
      value: data?.total_documents.toLocaleString() ?? "â€”",
      icon: FileTextIcon,
    },
    {
      label: "Queries (7d)",
      value: data?.queries_7d.toLocaleString() ?? "â€”",
      icon: MessageSquareIcon,
    },
    {
      label: "Avg response",
      value:
        data?.avg_response_time_ms != null
          ? `${data.avg_response_time_ms.toFixed(0)}ms`
          : "â€”",
      icon: ClockIcon,
    },
  ];

  return (
    <section aria-label="Key metrics">
      <h2 className="mb-3 text-sm font-medium text-muted-foreground">
        Key Metrics
      </h2>
      <div className="grid grid-cols-2 gap-3 sm:grid-cols-3 lg:grid-cols-5">
        {cards.map(({ label, value, sub, icon: Icon }) => (
          <div
            key={label}
            className="flex flex-col gap-1 rounded-lg border border-border bg-card p-3"
          >
            <Icon className="h-4 w-4 text-muted-foreground" />
            <p
              className="text-xl font-semibold tabular-nums tracking-tight"
              aria-label={label}
            >
              {value}
            </p>
            <p className="text-xs text-muted-foreground">{label}</p>
            {sub && (
              <p className="text-[10px] text-muted-foreground">{sub}</p>
            )}
          </div>
        ))}
      </div>
    </section>
  );
}
```

---

## 5. Query Volume Bar Chart (Canvas)

### `src/hooks/useBarChart.ts`

```ts
import { useEffect, useRef } from "react";

interface BarData {
  label: string;
  value: number;
}

interface UseBarChartOptions {
  data: BarData[];
  color?: string;
}

export function useBarChart({ data, color = "#6366f1" }: UseBarChartOptions) {
  const canvasRef = useRef<HTMLCanvasElement>(null);

  useEffect(() => {
    const canvas = canvasRef.current;
    if (!canvas || data.length === 0) return;

    const ctx = canvas.getContext("2d");
    if (!ctx) return;

    const { width, height } = canvas;
    const PADDING = { top: 16, right: 8, bottom: 32, left: 40 };
    const chartW = width - PADDING.left - PADDING.right;
    const chartH = height - PADDING.top - PADDING.bottom;

    ctx.clearRect(0, 0, width, height);

    const maxValue = Math.max(...data.map((d) => d.value), 1);

    // Gridlines (3)
    ctx.strokeStyle = "rgba(128,128,128,0.15)";
    ctx.lineWidth = 1;
    [0.25, 0.5, 0.75, 1].forEach((frac) => {
      const y = PADDING.top + chartH * (1 - frac);
      ctx.beginPath();
      ctx.moveTo(PADDING.left, y);
      ctx.lineTo(PADDING.left + chartW, y);
      ctx.stroke();

      // Y-axis labels
      ctx.fillStyle = "rgba(128,128,128,0.8)";
      ctx.font = "10px sans-serif";
      ctx.textAlign = "right";
      ctx.fillText(
        String(Math.round(maxValue * frac)),
        PADDING.left - 4,
        y + 3,
      );
    });

    // Bars
    const barW = (chartW / data.length) * 0.7;
    const gap = (chartW / data.length) * 0.3;

    data.forEach((d, i) => {
      const barH = (d.value / maxValue) * chartH;
      const x = PADDING.left + (chartW / data.length) * i + gap / 2;
      const y = PADDING.top + chartH - barH;

      ctx.fillStyle = color;
      ctx.fillRect(x, y, barW, barH);

      // X-axis label (skip every other for readability)
      if (i % 2 === 0) {
        ctx.fillStyle = "rgba(128,128,128,0.8)";
        ctx.font = "9px sans-serif";
        ctx.textAlign = "center";
        ctx.fillText(d.label.slice(5), x + barW / 2, PADDING.top + chartH + 14);
      }
    });
  }, [data, color]);

  return canvasRef;
}
```

### `src/components/admin/QueryVolumeChart.tsx`

```tsx
"use client";

import { useQuery } from "@tanstack/react-query";
import { apiClient } from "@/lib/api-client";
import { useBarChart } from "@/hooks/useBarChart";
import type { DailyQueryCount } from "@/types/admin-analytics";

export function QueryVolumeChart() {
  const { data } = useQuery<DailyQueryCount[]>({
    queryKey: ["admin-query-volume"],
    queryFn: async () => {
      const res = await apiClient.get<DailyQueryCount[]>(
        "/admin/analytics/queries?days=14",
      );
      return res.data;
    },
    refetchInterval: 30_000,
    staleTime: 10_000,
  });

  const barData = (data ?? []).map((d) => ({
    label: d.date,
    value: d.count,
  }));

  const canvasRef = useBarChart({ data: barData });

  const total = barData.reduce((s, d) => s + d.value, 0);

  return (
    <section
      className="rounded-lg border border-border bg-card p-4"
      aria-label="Query volume last 14 days"
    >
      <div className="mb-3 flex items-center justify-between">
        <h2 className="text-sm font-medium">Query Volume (14d)</h2>
        <span className="text-xs text-muted-foreground">
          {total.toLocaleString()} total
        </span>
      </div>
      <canvas
        ref={canvasRef}
        width={480}
        height={200}
        className="w-full"
        role="img"
        aria-label={`Bar chart: ${barData.map((d) => `${d.label}: ${d.value}`).join(", ")}`}
      />
    </section>
  );
}
```

---

## 6. Top Sources Table

### `src/components/admin/TopSourcesTable.tsx`

```tsx
"use client";

import { useQuery } from "@tanstack/react-query";
import { apiClient } from "@/lib/api-client";
import type { SourceQueryStat } from "@/types/admin-analytics";

export function TopSourcesTable() {
  const { data } = useQuery<SourceQueryStat[]>({
    queryKey: ["admin-top-sources"],
    queryFn: async () => {
      const res = await apiClient.get<SourceQueryStat[]>(
        "/admin/analytics/top-sources?limit=10",
      );
      return res.data;
    },
    refetchInterval: 30_000,
    staleTime: 10_000,
  });

  const sources = data ?? [];
  const maxCount = Math.max(...sources.map((s) => s.query_count), 1);

  return (
    <section
      className="rounded-lg border border-border bg-card p-4"
      aria-label="Top sources by query count"
    >
      <h2 className="mb-3 text-sm font-medium">Top Sources (30d)</h2>
      {sources.length === 0 ? (
        <p className="text-xs text-muted-foreground">No query data yet.</p>
      ) : (
        <ol className="space-y-2">
          {sources.map((s, i) => (
            <li key={s.source_id} className="flex items-center gap-2">
              <span className="w-4 text-right text-[10px] text-muted-foreground">
                {i + 1}
              </span>
              <div className="flex flex-1 flex-col gap-0.5">
                <span className="truncate text-xs font-medium">{s.source_name}</span>
                <div className="flex items-center gap-1.5">
                  {/* Inline bar */}
                  <div className="h-1.5 flex-1 overflow-hidden rounded-full bg-muted">
                    <div
                      className="h-full rounded-full bg-primary"
                      style={{
                        width: `${(s.query_count / maxCount) * 100}%`,
                      }}
                    />
                  </div>
                  <span className="w-10 text-right text-[10px] tabular-nums text-muted-foreground">
                    {s.query_count.toLocaleString()}
                  </span>
                </div>
              </div>
            </li>
          ))}
        </ol>
      )}
    </section>
  );
}
```

---

## 7. Activity Feed

### `src/components/admin/ActivityFeed.tsx`

```tsx
"use client";

import { useQuery } from "@tanstack/react-query";
import {
  InfoIcon,
  AlertTriangleIcon,
  XCircleIcon,
} from "lucide-react";
import { cn } from "@/lib/utils";
import { apiClient } from "@/lib/api-client";
import type { ActivityEvent } from "@/types/admin-analytics";

const SEV_STYLES: Record<
  ActivityEvent["severity"],
  { icon: React.ComponentType<{ className?: string }>; color: string }
> = {
  info: { icon: InfoIcon, color: "text-blue-600 dark:text-blue-400" },
  warning: { icon: AlertTriangleIcon, color: "text-amber-600 dark:text-amber-400" },
  error: { icon: XCircleIcon, color: "text-red-600 dark:text-red-400" },
};

export function ActivityFeed() {
  const { data } = useQuery<ActivityEvent[]>({
    queryKey: ["admin-activity"],
    queryFn: async () => {
      const res = await apiClient.get<ActivityEvent[]>(
        "/admin/analytics/activity?limit=20",
      );
      return res.data;
    },
    refetchInterval: 30_000,
    staleTime: 10_000,
  });

  const events = data ?? [];

  return (
    <section aria-label="Recent system activity">
      <h2 className="mb-3 text-sm font-medium text-muted-foreground">
        Recent Activity
      </h2>
      {events.length === 0 ? (
        <p className="text-xs text-muted-foreground">No recent activity.</p>
      ) : (
        <ol className="space-y-1" aria-live="polite">
          {events.map((ev) => {
            const { icon: Icon, color } = SEV_STYLES[ev.severity];
            return (
              <li
                key={ev.id}
                className="flex items-start gap-2 rounded-md px-2 py-1.5 hover:bg-muted/50"
              >
                <Icon className={cn("mt-0.5 h-3.5 w-3.5 shrink-0", color)} />
                <div className="min-w-0 flex-1">
                  <p className="truncate text-xs">{ev.message}</p>
                  <p className="text-[10px] text-muted-foreground">
                    {new Date(ev.created_at).toLocaleString()}
                  </p>
                </div>
              </li>
            );
          })}
        </ol>
      )}
    </section>
  );
}
```

---

## 8. Tests

### `src/components/admin/__tests__/HealthCards.test.tsx`

```tsx
import { render, screen } from "@testing-library/react";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { HealthCards } from "../HealthCards";
import { vi } from "vitest";

vi.mock("@/lib/api-client", () => ({
  apiClient: {
    get: vi.fn().mockResolvedValue({
      data: {
        checked_at: new Date().toISOString(),
        checks: [
          { service: "database", status: "ok", latency_ms: 3, detail: null },
          { service: "redis", status: "ok", latency_ms: 1, detail: null },
          { service: "minio", status: "degraded", latency_ms: 120, detail: "Slow" },
          { service: "celery", status: "down", latency_ms: null, detail: "No workers" },
        ],
      },
    }),
  },
}));

function wrapper({ children }: { children: React.ReactNode }) {
  const qc = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  return <QueryClientProvider client={qc}>{children}</QueryClientProvider>;
}

test("renders all four service cards", async () => {
  render(<HealthCards />, { wrapper });
  expect(await screen.findByRole("status", { name: /database is ok/i })).toBeInTheDocument();
  expect(screen.getByRole("status", { name: /redis is ok/i })).toBeInTheDocument();
  expect(screen.getByRole("status", { name: /minio is degraded/i })).toBeInTheDocument();
  expect(screen.getByRole("status", { name: /celery is down/i })).toBeInTheDocument();
});
```

### `src/hooks/__tests__/useBarChart.test.ts`

```ts
import { renderHook } from "@testing-library/react";
import { useBarChart } from "../useBarChart";

test("returns a canvas ref", () => {
  const { result } = renderHook(() =>
    useBarChart({ data: [{ label: "2026-02-01", value: 10 }] }),
  );
  expect(result.current).toBeDefined();
  expect(result.current.current).toBeNull(); // JSDOM doesn't mount
});
```

---

## Acceptance Criteria

- [ ] `/admin` shows 4 service health cards (database, redis, minio, celery) with OK / degraded / down states
- [ ] Metrics row shows 5 KPI cards with real API data
- [ ] Query volume bar chart uses native Canvas (no chart library) and renders bars for 14 days
- [ ] Top sources shows inline bar proportional to max query count
- [ ] Activity feed shows last 20 events in reverse-chronological order
- [ ] All sections auto-refresh every 30 seconds (`refetchInterval: 30_000`)
- [ ] Health card `role="status"` with `aria-label="{service} is {status}"`
- [ ] Bar chart `role="img"` with full textual `aria-label`
- [ ] Activity feed list has `aria-live="polite"`
- [ ] Skeleton placeholder shown while data is loading
- [ ] Unit tests pass: `pnpm test`
