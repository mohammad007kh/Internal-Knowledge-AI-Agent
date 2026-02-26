# T-087 · Admin — Source & Connector Management UI

**Phase:** 5 — Admin Frontend  
**Depends on:** T-080 (layout), T-060–T-070 (source/connector APIs)  
**Blocks:** T-090

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

> **RBAC:** Admin-only pages. The layout must redirect `role === "user"` to `/chat`.

---

## Objective

Build the admin screens for managing **knowledge sources** and **connectors**:

| Route | Description |
|---|---|
| `/admin/sources` | Paginated source list with status indicator |
| `/admin/sources/new` | Connector-type picker then source form |
| `/admin/sources/[id]` | Source detail: documents tab + sync history tab |
| `/admin/connectors` | Connector configuration list |
| `/admin/connectors/new` | Add connector (type-driven form) |
| `/admin/connectors/[id]` | Edit / test connector |

---

## 1. Route Guard

### `src/app/(app)/admin/layout.tsx`

```tsx
import { redirect } from "next/navigation";
import { getServerSession } from "@/lib/auth/server-session";

export default async function AdminLayout({
  children,
}: {
  children: React.ReactNode;
}) {
  const session = await getServerSession();
  if (!session || session.role !== "admin") redirect("/chat");
  return <>{children}</>;
}
```

---

## 2. Sources List Page

### `src/app/(app)/admin/sources/page.tsx`

```tsx
import { Suspense } from "react";
import { SourcesTable } from "@/components/admin/SourcesTable";
import { Button } from "@/components/ui/button";
import Link from "next/link";
import { PlusIcon } from "lucide-react";

export const metadata = { title: "Knowledge Sources — Admin" };

export default function SourcesPage() {
  return (
    <div className="space-y-4 p-6">
      <div className="flex items-center justify-between">
        <h1 className="text-xl font-semibold">Knowledge Sources</h1>
        <Button asChild size="sm">
          <Link href="/admin/sources/new">
            <PlusIcon className="mr-1.5 h-4 w-4" />
            Add source
          </Link>
        </Button>
      </div>
      <Suspense fallback={<div className="h-64 animate-pulse rounded-md bg-muted" />}>
        <SourcesTable />
      </Suspense>
    </div>
  );
}
```

### `src/components/admin/SourcesTable.tsx`

```tsx
"use client";

import { useState } from "react";
import { useQuery, useMutation, useQueryClient } from "@tanstack/react-query";
import {
  ColumnDef,
  flexRender,
  getCoreRowModel,
  getPaginationRowModel,
  useReactTable,
} from "@tanstack/react-table";
import { toast } from "sonner";
import { Trash2Icon, RefreshCwIcon, ExternalLinkIcon } from "lucide-react";
import Link from "next/link";
import {
  Table,
  TableBody,
  TableCell,
  TableHead,
  TableHeader,
  TableRow,
} from "@/components/ui/table";
import { Button } from "@/components/ui/button";
import { Badge } from "@/components/ui/badge";
import {
  AlertDialog,
  AlertDialogAction,
  AlertDialogCancel,
  AlertDialogContent,
  AlertDialogDescription,
  AlertDialogFooter,
  AlertDialogHeader,
  AlertDialogTitle,
} from "@/components/ui/alert-dialog";
import { apiClient } from "@/lib/api-client";
import { cn } from "@/lib/utils";

// ─── Types ───────────────────────────────────────────────────────────────────

export type SourceStatus =
  | "pending"
  | "syncing"
  | "ready"
  | "error"
  | "disabled";

export interface KnowledgeSource {
  id: string;
  name: string;
  connector_type: string;
  status: SourceStatus;
  document_count: number;
  last_synced_at: string | null;
  created_at: string;
}

interface SourcesResponse {
  items: KnowledgeSource[];
  total: number;
  page: number;
  page_size: number;
}

// ─── Status badge ─────────────────────────────────────────────────────────────

const STATUS_VARIANT: Record<SourceStatus, string> = {
  pending: "secondary",
  syncing: "outline",
  ready: "success",
  error: "destructive",
  disabled: "secondary",
};

function StatusBadge({ status }: { status: SourceStatus }) {
  return (
    <Badge
      variant={STATUS_VARIANT[status] as "secondary" | "outline" | "destructive"}
      className={cn(status === "ready" && "bg-green-600/15 text-green-700 dark:text-green-400")}
    >
      {status}
    </Badge>
  );
}

// ─── API ──────────────────────────────────────────────────────────────────────

async function fetchSources(page: number): Promise<SourcesResponse> {
  const res = await apiClient.get<SourcesResponse>(
    `/sources?page=${page}&page_size=20`,
  );
  return res.data;
}

async function triggerSync(id: string): Promise<void> {
  await apiClient.post(`/sources/${id}/sync`);
}

async function deleteSource(id: string): Promise<void> {
  await apiClient.delete(`/sources/${id}`);
}

// ─── Table ────────────────────────────────────────────────────────────────────

const PAGE_SIZE = 20;

export function SourcesTable() {
  const queryClient = useQueryClient();
  const [page, setPage] = useState(1);
  const [deletingId, setDeletingId] = useState<string | null>(null);

  const { data } = useQuery({
    queryKey: ["admin-sources", page],
    queryFn: () => fetchSources(page),
    staleTime: 15_000,
  });

  const sources: KnowledgeSource[] = data?.items ?? [];
  const total = data?.total ?? 0;
  const totalPages = Math.ceil(total / PAGE_SIZE);

  const syncMutation = useMutation({
    mutationFn: triggerSync,
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ["admin-sources"] });
      toast.success("Sync triggered.");
    },
    onError: () => toast.error("Failed to trigger sync."),
  });

  const deleteMutation = useMutation({
    mutationFn: deleteSource,
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ["admin-sources"] });
      setDeletingId(null);
      toast.success("Source deleted.");
    },
    onError: () => toast.error("Failed to delete source."),
  });

  const columns: ColumnDef<KnowledgeSource>[] = [
    {
      accessorKey: "name",
      header: "Name",
      cell: ({ row }) => (
        <Link
          href={`/admin/sources/${row.original.id}`}
          className="flex items-center gap-1.5 hover:underline"
        >
          {row.original.name}
          <ExternalLinkIcon className="h-3 w-3 text-muted-foreground" />
        </Link>
      ),
    },
    {
      accessorKey: "connector_type",
      header: "Type",
      cell: ({ getValue }) => (
        <span className="font-mono text-xs">{String(getValue())}</span>
      ),
    },
    {
      accessorKey: "status",
      header: "Status",
      cell: ({ getValue }) => (
        <StatusBadge status={getValue() as SourceStatus} />
      ),
    },
    {
      accessorKey: "document_count",
      header: "Documents",
      cell: ({ getValue }) => (
        <span className="tabular-nums">{Number(getValue()).toLocaleString()}</span>
      ),
    },
    {
      accessorKey: "last_synced_at",
      header: "Last sync",
      cell: ({ getValue }) => {
        const v = getValue() as string | null;
        return (
          <span className="text-xs text-muted-foreground">
            {v ? new Date(v).toLocaleString() : "Never"}
          </span>
        );
      },
    },
    {
      id: "actions",
      header: "",
      cell: ({ row }) => (
        <div className="flex items-center justify-end gap-1">
          <Button
            size="icon"
            variant="ghost"
            className="h-7 w-7"
            onClick={() => syncMutation.mutate(row.original.id)}
            disabled={
              syncMutation.isPending ||
              row.original.status === "syncing" ||
              row.original.status === "disabled"
            }
            title="Trigger sync"
            aria-label={`Sync ${row.original.name}`}
          >
            <RefreshCwIcon className="h-3.5 w-3.5" />
          </Button>
          <Button
            size="icon"
            variant="ghost"
            className="h-7 w-7 text-destructive hover:bg-destructive/10"
            onClick={() => setDeletingId(row.original.id)}
            title="Delete source"
            aria-label={`Delete ${row.original.name}`}
          >
            <Trash2Icon className="h-3.5 w-3.5" />
          </Button>
        </div>
      ),
    },
  ];

  const table = useReactTable({
    data: sources,
    columns,
    getCoreRowModel: getCoreRowModel(),
    getPaginationRowModel: getPaginationRowModel(),
    manualPagination: true,
    pageCount: totalPages,
    state: { pagination: { pageIndex: page - 1, pageSize: PAGE_SIZE } },
    onPaginationChange: (updater) => {
      if (typeof updater === "function") {
        const next = updater({ pageIndex: page - 1, pageSize: PAGE_SIZE });
        setPage(next.pageIndex + 1);
      }
    },
  });

  return (
    <>
      <div className="rounded-md border border-border">
        <Table>
          <TableHeader>
            {table.getHeaderGroups().map((hg) => (
              <TableRow key={hg.id}>
                {hg.headers.map((header) => (
                  <TableHead key={header.id}>
                    {header.isPlaceholder
                      ? null
                      : flexRender(
                          header.column.columnDef.header,
                          header.getContext(),
                        )}
                  </TableHead>
                ))}
              </TableRow>
            ))}
          </TableHeader>
          <TableBody>
            {table.getRowModel().rows.length === 0 ? (
              <TableRow>
                <TableCell
                  colSpan={columns.length}
                  className="py-8 text-center text-sm text-muted-foreground"
                >
                  No sources yet. Add your first knowledge source.
                </TableCell>
              </TableRow>
            ) : (
              table.getRowModel().rows.map((row) => (
                <TableRow key={row.id}>
                  {row.getVisibleCells().map((cell) => (
                    <TableCell key={cell.id}>
                      {flexRender(
                        cell.column.columnDef.cell,
                        cell.getContext(),
                      )}
                    </TableCell>
                  ))}
                </TableRow>
              ))
            )}
          </TableBody>
        </Table>
      </div>

      {/* Pagination */}
      {totalPages > 1 && (
        <div className="flex items-center justify-between">
          <p className="text-xs text-muted-foreground">
            {total} sources total
          </p>
          <div className="flex gap-1.5">
            <Button
              size="sm"
              variant="outline"
              onClick={() => setPage((p) => Math.max(1, p - 1))}
              disabled={page <= 1}
            >
              Previous
            </Button>
            <Button
              size="sm"
              variant="outline"
              onClick={() => setPage((p) => Math.min(totalPages, p + 1))}
              disabled={page >= totalPages}
            >
              Next
            </Button>
          </div>
        </div>
      )}

      {/* Delete confirmation */}
      <AlertDialog
        open={!!deletingId}
        onOpenChange={(o) => !o && setDeletingId(null)}
      >
        <AlertDialogContent>
          <AlertDialogHeader>
            <AlertDialogTitle>Delete knowledge source?</AlertDialogTitle>
            <AlertDialogDescription>
              All indexed documents and embeddings for this source will be
              removed. This cannot be undone.
            </AlertDialogDescription>
          </AlertDialogHeader>
          <AlertDialogFooter>
            <AlertDialogCancel>Cancel</AlertDialogCancel>
            <AlertDialogAction
              onClick={() => deletingId && deleteMutation.mutate(deletingId)}
              className="bg-destructive text-destructive-foreground hover:bg-destructive/90"
            >
              Delete
            </AlertDialogAction>
          </AlertDialogFooter>
        </AlertDialogContent>
      </AlertDialog>
    </>
  );
}
```

---

## 3. Add Source Form

### `src/app/(app)/admin/sources/new/page.tsx`

```tsx
"use client";

import { useState } from "react";
import { useRouter } from "next/navigation";
import { useMutation, useQuery } from "@tanstack/react-query";
import { zodResolver } from "@hookform/resolvers/zod";
import { useForm } from "react-hook-form";
import { z } from "zod";
import { toast } from "sonner";
import { apiClient } from "@/lib/api-client";
import {
  Form,
  FormControl,
  FormField,
  FormItem,
  FormLabel,
  FormMessage,
} from "@/components/ui/form";
import { Input } from "@/components/ui/input";
import { Button } from "@/components/ui/button";
import {
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue,
} from "@/components/ui/select";

const schema = z.object({
  name: z.string().min(1, "Name is required").max(100),
  connector_id: z.string().uuid("Select a connector"),
  sync_schedule: z.enum(["manual", "hourly", "daily", "weekly"]),
  config_overrides: z.string().optional(),
});

type FormValues = z.infer<typeof schema>;

interface Connector {
  id: string;
  name: string;
  connector_type: string;
}

async function fetchConnectors(): Promise<{ items: Connector[] }> {
  const res = await apiClient.get<{ items: Connector[] }>("/connectors?limit=100");
  return res.data;
}

async function createSource(values: FormValues): Promise<{ id: string }> {
  const body: Record<string, unknown> = {
    name: values.name,
    connector_id: values.connector_id,
    sync_schedule: values.sync_schedule,
  };
  if (values.config_overrides) {
    body.config_overrides = JSON.parse(values.config_overrides);
  }
  const res = await apiClient.post<{ id: string }>("/sources", body);
  return res.data;
}

export default function NewSourcePage() {
  const router = useRouter();

  const form = useForm<FormValues>({
    resolver: zodResolver(schema),
    defaultValues: { sync_schedule: "manual" },
  });

  const { data: connectorData } = useQuery({
    queryKey: ["connectors-list"],
    queryFn: fetchConnectors,
  });
  const connectors = connectorData?.items ?? [];

  const mutation = useMutation({
    mutationFn: createSource,
    onSuccess: (data) => {
      toast.success("Source created. Starting initial sync…");
      router.push(`/admin/sources/${data.id}`);
    },
    onError: () => toast.error("Failed to create source."),
  });

  return (
    <div className="max-w-lg p-6">
      <h1 className="mb-6 text-xl font-semibold">Add Knowledge Source</h1>
      <Form {...form}>
        <form
          onSubmit={form.handleSubmit((v) => mutation.mutate(v))}
          className="space-y-4"
          noValidate
        >
          <FormField
            control={form.control}
            name="name"
            render={({ field }) => (
              <FormItem>
                <FormLabel>Name</FormLabel>
                <FormControl>
                  <Input placeholder="e.g. Engineering Wiki" {...field} />
                </FormControl>
                <FormMessage />
              </FormItem>
            )}
          />

          <FormField
            control={form.control}
            name="connector_id"
            render={({ field }) => (
              <FormItem>
                <FormLabel>Connector</FormLabel>
                <Select
                  onValueChange={field.onChange}
                  defaultValue={field.value}
                >
                  <FormControl>
                    <SelectTrigger>
                      <SelectValue placeholder="Select connector…" />
                    </SelectTrigger>
                  </FormControl>
                  <SelectContent>
                    {connectors.map((c) => (
                      <SelectItem key={c.id} value={c.id}>
                        {c.name} ({c.connector_type})
                      </SelectItem>
                    ))}
                  </SelectContent>
                </Select>
                <FormMessage />
              </FormItem>
            )}
          />

          <FormField
            control={form.control}
            name="sync_schedule"
            render={({ field }) => (
              <FormItem>
                <FormLabel>Sync schedule</FormLabel>
                <Select
                  onValueChange={field.onChange}
                  defaultValue={field.value}
                >
                  <FormControl>
                    <SelectTrigger>
                      <SelectValue />
                    </SelectTrigger>
                  </FormControl>
                  <SelectContent>
                    {["manual", "hourly", "daily", "weekly"].map((s) => (
                      <SelectItem key={s} value={s}>
                        {s.charAt(0).toUpperCase() + s.slice(1)}
                      </SelectItem>
                    ))}
                  </SelectContent>
                </Select>
                <FormMessage />
              </FormItem>
            )}
          />

          <div className="flex justify-end gap-2 pt-2">
            <Button
              type="button"
              variant="outline"
              onClick={() => router.back()}
            >
              Cancel
            </Button>
            <Button type="submit" disabled={mutation.isPending}>
              {mutation.isPending ? "Creating…" : "Create source"}
            </Button>
          </div>
        </form>
      </Form>
    </div>
  );
}
```

---

## 4. Connector Management Pages

Identical TanStack Table pattern for `/admin/connectors`. The `ConnectorsTable` component follows the same structure as `SourcesTable` but uses connector-specific fields:

| Column | Description |
|---|---|
| Name | Link to `/admin/connectors/[id]` |
| Type | `connector_type` (confluence / jira / sharepoint / web / file) |
| Status | `active` / `error` |
| Source count | Number of sources using this connector |
| Last tested | Timestamp of last connection test |
| Actions | Test connection (⚡), Edit (✏️), Delete (🗑️) |

Connector Form Fields (by type):

```
confluence: base_url, username, api_token (secret), space_keys
jira:       base_url, username, api_token (secret), project_keys
sharepoint: tenant_id, client_id, client_secret (secret), site_url
web:        allowed_domains[], crawl_depth, user_agent
file:       allowed_extensions[], max_file_size_mb
```

Secret fields use `type="password"` and show ••••••• when a value is already saved.

---

## 5. Tests

### `src/components/admin/__tests__/SourcesTable.test.tsx`

```tsx
import { render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { SourcesTable } from "../SourcesTable";
import { vi } from "vitest";

const mockSources = [
  {
    id: "src1",
    name: "Confluence Wiki",
    connector_type: "confluence",
    status: "ready",
    document_count: 1200,
    last_synced_at: new Date().toISOString(),
    created_at: new Date().toISOString(),
  },
  {
    id: "src2",
    name: "Jira Backlog",
    connector_type: "jira",
    status: "error",
    document_count: 0,
    last_synced_at: null,
    created_at: new Date().toISOString(),
  },
];

vi.mock("@/lib/api-client", () => ({
  apiClient: {
    get: vi.fn().mockResolvedValue({
      data: { items: mockSources, total: 2, page: 1, page_size: 20 },
    }),
    post: vi.fn().mockResolvedValue({ data: {} }),
    delete: vi.fn().mockResolvedValue({ data: {} }),
  },
}));

function wrapper({ children }: { children: React.ReactNode }) {
  const qc = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  return <QueryClientProvider client={qc}>{children}</QueryClientProvider>;
}

test("renders sources in table", async () => {
  render(<SourcesTable />, { wrapper });
  expect(await screen.findByText("Confluence Wiki")).toBeInTheDocument();
  expect(screen.getByText("Jira Backlog")).toBeInTheDocument();
});

test("shows correct status badges", async () => {
  render(<SourcesTable />, { wrapper });
  expect(await screen.findByText("ready")).toBeInTheDocument();
  expect(screen.getByText("error")).toBeInTheDocument();
});

test("trigger sync button calls POST /sources/{id}/sync", async () => {
  const { apiClient } = await import("@/lib/api-client");
  render(<SourcesTable />, { wrapper });
  await screen.findByText("Confluence Wiki");
  await userEvent.click(screen.getByRole("button", { name: /sync confluence wiki/i }));
  await waitFor(() => {
    expect(apiClient.post).toHaveBeenCalledWith("/sources/src1/sync");
  });
});

test("delete shows confirmation dialog", async () => {
  render(<SourcesTable />, { wrapper });
  await screen.findByText("Confluence Wiki");
  await userEvent.click(screen.getByRole("button", { name: /delete confluence wiki/i }));
  expect(
    screen.getByText(/all indexed documents and embeddings/i),
  ).toBeInTheDocument();
});
```

---

## Acceptance Criteria

- [ ] `/admin/*` redirects non-admin users to `/chat`
- [ ] Sources table loads with pagination, status badges, document counts
- [ ] Sync button triggers `POST /sources/{id}/sync` with success toast
- [ ] Delete shows `AlertDialog` confirmation before `DELETE /sources/{id}`
- [ ] Source name links to `/admin/sources/[id]` detail page
- [ ] New source form validates name (required) and connector (required UUID)
- [ ] Form error messages displayed inline under fields
- [ ] Connectors table same pattern: list, test, edit, delete
- [ ] Connector form hides secret fields behind password input
- [ ] Empty state row shown when no sources/connectors
- [ ] All admin pages are server component + client table split (RSC outer, `"use client"` table)
- [ ] Unit tests pass: `pnpm test`
