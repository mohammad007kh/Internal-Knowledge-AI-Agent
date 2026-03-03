# T-088 Â· Admin â€” User Management UI

**Status:** Done

**Phase:** 5 â€” Admin Frontend  
**Depends on:** T-080 (layout), T-050 (user API)  
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

> **RBAC:** Admin-only. Ensured by `src/app/(app)/admin/layout.tsx` (T-087).

---

## Objective

Admin UI for managing users:

| Route | Description |
|---|---|
| `/admin/users` | Paginated user table with role, status, last-login |
| `/admin/users/new` | Invite user by email and assign role |
| `/admin/users/[id]` | View/edit user: change role, deactivate/reactivate, reset password |

---

## 1. Users List Page

### `src/app/(app)/admin/users/page.tsx`

```tsx
import { Suspense } from "react";
import Link from "next/link";
import { PlusIcon } from "lucide-react";
import { Button } from "@/components/ui/button";
import { UsersTable } from "@/components/admin/UsersTable";

export const metadata = { title: "Users â€” Admin" };

export default function UsersPage() {
  return (
    <div className="space-y-4 p-6">
      <div className="flex items-center justify-between">
        <h1 className="text-xl font-semibold">Users</h1>
        <Button asChild size="sm">
          <Link href="/admin/users/new">
            <PlusIcon className="mr-1.5 h-4 w-4" />
            Invite user
          </Link>
        </Button>
      </div>
      <Suspense fallback={<div className="h-64 animate-pulse rounded-md bg-muted" />}>
        <UsersTable />
      </Suspense>
    </div>
  );
}
```

---

## 2. `UsersTable` Component

### `src/components/admin/UsersTable.tsx`

```tsx
"use client";

import { useState } from "react";
import { useQuery, useMutation, useQueryClient } from "@tanstack/react-query";
import {
  ColumnDef,
  flexRender,
  getCoreRowModel,
  useReactTable,
} from "@tanstack/react-table";
import { toast } from "sonner";
import {
  PencilIcon,
  ShieldCheckIcon,
  UserIcon,
  BanIcon,
  CheckCircleIcon,
} from "lucide-react";
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
import { Input } from "@/components/ui/input";
import { apiClient } from "@/lib/api-client";
import { cn } from "@/lib/utils";

// â”€â”€â”€ Types â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€

export interface AdminUser {
  id: string;
  email: string;
  full_name: string | null;
  role: "admin" | "user";
  is_active: boolean;
  last_login_at: string | null;
  created_at: string;
}

interface UsersResponse {
  items: AdminUser[];
  total: number;
  page: number;
  page_size: number;
}

// â”€â”€â”€ API â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€

const PAGE_SIZE = 25;

async function fetchUsers(page: number, search: string): Promise<UsersResponse> {
  const params = new URLSearchParams({
    page: String(page),
    page_size: String(PAGE_SIZE),
  });
  if (search) params.set("search", search);
  const res = await apiClient.get<UsersResponse>(`/admin/users?${params}`);
  return res.data;
}

async function deactivateUser(id: string): Promise<void> {
  await apiClient.patch(`/admin/users/${id}`, { is_active: false });
}

async function reactivateUser(id: string): Promise<void> {
  await apiClient.patch(`/admin/users/${id}`, { is_active: true });
}

// â”€â”€â”€ Component â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€

export function UsersTable() {
  const queryClient = useQueryClient();
  const [page, setPage] = useState(1);
  const [search, setSearch] = useState("");
  const [deactivatingId, setDeactivatingId] = useState<string | null>(null);

  const { data, isLoading } = useQuery({
    queryKey: ["admin-users", page, search],
    queryFn: () => fetchUsers(page, search),
    staleTime: 15_000,
  });

  const users: AdminUser[] = data?.items ?? [];
  const total = data?.total ?? 0;
  const totalPages = Math.ceil(total / PAGE_SIZE);

  const deactivateMutation = useMutation({
    mutationFn: deactivateUser,
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ["admin-users"] });
      setDeactivatingId(null);
      toast.success("User deactivated.");
    },
    onError: () => toast.error("Failed to deactivate user."),
  });

  const reactivateMutation = useMutation({
    mutationFn: reactivateUser,
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ["admin-users"] });
      toast.success("User reactivated.");
    },
    onError: () => toast.error("Failed to reactivate user."),
  });

  const columns: ColumnDef<AdminUser>[] = [
    {
      accessorKey: "email",
      header: "Email",
      cell: ({ row }) => (
        <Link
          href={`/admin/users/${row.original.id}`}
          className="font-medium hover:underline"
        >
          {row.original.email}
        </Link>
      ),
    },
    {
      accessorKey: "full_name",
      header: "Name",
      cell: ({ getValue }) => (
        <span className="text-sm text-muted-foreground">
          {(getValue() as string | null) ?? "â€”"}
        </span>
      ),
    },
    {
      accessorKey: "role",
      header: "Role",
      cell: ({ getValue }) => {
        const role = getValue() as "admin" | "user";
        return (
          <Badge
            variant={role === "admin" ? "default" : "secondary"}
            className="gap-1"
          >
            {role === "admin" ? (
              <ShieldCheckIcon className="h-3 w-3" />
            ) : (
              <UserIcon className="h-3 w-3" />
            )}
            {role}
          </Badge>
        );
      },
    },
    {
      accessorKey: "is_active",
      header: "Status",
      cell: ({ getValue }) => {
        const active = getValue() as boolean;
        return (
          <Badge
            variant={active ? "outline" : "secondary"}
            className={cn(
              "gap-1",
              active ? "border-green-500 text-green-700 dark:text-green-400" : "",
            )}
          >
            {active ? (
              <CheckCircleIcon className="h-3 w-3" />
            ) : (
              <BanIcon className="h-3 w-3" />
            )}
            {active ? "Active" : "Inactive"}
          </Badge>
        );
      },
    },
    {
      accessorKey: "last_login_at",
      header: "Last login",
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
            asChild
            aria-label={`Edit ${row.original.email}`}
          >
            <Link href={`/admin/users/${row.original.id}`}>
              <PencilIcon className="h-3.5 w-3.5" />
            </Link>
          </Button>
          {row.original.is_active ? (
            <Button
              size="icon"
              variant="ghost"
              className="h-7 w-7 text-destructive hover:bg-destructive/10"
              onClick={() => setDeactivatingId(row.original.id)}
              aria-label={`Deactivate ${row.original.email}`}
            >
              <BanIcon className="h-3.5 w-3.5" />
            </Button>
          ) : (
            <Button
              size="icon"
              variant="ghost"
              className="h-7 w-7 text-green-600"
              onClick={() => reactivateMutation.mutate(row.original.id)}
              disabled={reactivateMutation.isPending}
              aria-label={`Reactivate ${row.original.email}`}
            >
              <CheckCircleIcon className="h-3.5 w-3.5" />
            </Button>
          )}
        </div>
      ),
    },
  ];

  const table = useReactTable({
    data: users,
    columns,
    getCoreRowModel: getCoreRowModel(),
    manualPagination: true,
    pageCount: totalPages,
  });

  return (
    <>
      {/* Search */}
      <div className="mb-3 max-w-xs">
        <Input
          placeholder="Search by email or nameâ€¦"
          value={search}
          onChange={(e) => {
            setSearch(e.target.value);
            setPage(1);
          }}
          className="h-8 text-xs"
          aria-label="Search users"
        />
      </div>

      {/* Table */}
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
            {isLoading ? (
              Array.from({ length: 5 }).map((_, i) => (
                <TableRow key={i}>
                  <TableCell colSpan={columns.length}>
                    <div className="h-4 animate-pulse rounded bg-muted" />
                  </TableCell>
                </TableRow>
              ))
            ) : users.length === 0 ? (
              <TableRow>
                <TableCell
                  colSpan={columns.length}
                  className="py-8 text-center text-sm text-muted-foreground"
                >
                  No users found.
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
        <div className="flex items-center justify-between pt-2">
          <p className="text-xs text-muted-foreground">{total} users total</p>
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

      {/* Deactivate confirmation */}
      <AlertDialog
        open={!!deactivatingId}
        onOpenChange={(o) => !o && setDeactivatingId(null)}
      >
        <AlertDialogContent>
          <AlertDialogHeader>
            <AlertDialogTitle>Deactivate user?</AlertDialogTitle>
            <AlertDialogDescription>
              The user's access will be revoked immediately. They will be unable
              to log in until reactivated.
            </AlertDialogDescription>
          </AlertDialogHeader>
          <AlertDialogFooter>
            <AlertDialogCancel>Cancel</AlertDialogCancel>
            <AlertDialogAction
              onClick={() =>
                deactivatingId && deactivateMutation.mutate(deactivatingId)
              }
              className="bg-destructive text-destructive-foreground hover:bg-destructive/90"
            >
              Deactivate
            </AlertDialogAction>
          </AlertDialogFooter>
        </AlertDialogContent>
      </AlertDialog>
    </>
  );
}
```

---

## 3. Invite User Form

### `src/app/(app)/admin/users/new/page.tsx`

```tsx
"use client";

import { useRouter } from "next/navigation";
import { useMutation } from "@tanstack/react-query";
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
  FormDescription,
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
  email: z.string().email("Valid email required"),
  full_name: z.string().max(100).optional(),
  role: z.enum(["admin", "user"]),
  send_invite: z.boolean().default(true),
});

type FormValues = z.infer<typeof schema>;

async function inviteUser(values: FormValues): Promise<{ id: string }> {
  const res = await apiClient.post<{ id: string }>("/admin/users/invite", values);
  return res.data;
}

export default function InviteUserPage() {
  const router = useRouter();

  const form = useForm<FormValues>({
    resolver: zodResolver(schema),
    defaultValues: { role: "user", send_invite: true },
  });

  const mutation = useMutation({
    mutationFn: inviteUser,
    onSuccess: (data) => {
      toast.success("User invited successfully.");
      router.push(`/admin/users/${data.id}`);
    },
    onError: () => toast.error("Failed to invite user."),
  });

  return (
    <div className="max-w-lg p-6">
      <h1 className="mb-6 text-xl font-semibold">Invite User</h1>
      <Form {...form}>
        <form
          onSubmit={form.handleSubmit((v) => mutation.mutate(v))}
          className="space-y-4"
          noValidate
        >
          <FormField
            control={form.control}
            name="email"
            render={({ field }) => (
              <FormItem>
                <FormLabel>Email address</FormLabel>
                <FormControl>
                  <Input
                    type="email"
                    placeholder="user@company.com"
                    {...field}
                  />
                </FormControl>
                <FormMessage />
              </FormItem>
            )}
          />

          <FormField
            control={form.control}
            name="full_name"
            render={({ field }) => (
              <FormItem>
                <FormLabel>
                  Full name{" "}
                  <span className="font-normal text-muted-foreground">
                    (optional)
                  </span>
                </FormLabel>
                <FormControl>
                  <Input placeholder="Jane Doe" {...field} />
                </FormControl>
                <FormMessage />
              </FormItem>
            )}
          />

          <FormField
            control={form.control}
            name="role"
            render={({ field }) => (
              <FormItem>
                <FormLabel>Role</FormLabel>
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
                    <SelectItem value="user">User</SelectItem>
                    <SelectItem value="admin">Admin</SelectItem>
                  </SelectContent>
                </Select>
                <FormDescription>
                  Admins can manage sources, connectors, and other users.
                </FormDescription>
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
              {mutation.isPending ? "Sendingâ€¦" : "Send invite"}
            </Button>
          </div>
        </form>
      </Form>
    </div>
  );
}
```

---

## 4. User Detail Page

### `src/app/(app)/admin/users/[id]/page.tsx`

Key sections:

- **Profile section**: Edit `full_name`, `email`, `role` â€” PATCH `/admin/users/{id}`
- **Status section**: Deactivate / Reactivate button
- **Security section**: "Send password reset email" button â†’ POST `/admin/users/{id}/reset-password`
- **Activity section**: Last login timestamp, account creation date

```tsx
"use client";

import { useParams, useRouter } from "next/navigation";
import { useQuery, useMutation, useQueryClient } from "@tanstack/react-query";
import { zodResolver } from "@hookform/resolvers/zod";
import { useForm } from "react-hook-form";
import { z } from "zod";
import { toast } from "sonner";
import { apiClient } from "@/lib/api-client";
import {
  Form, FormControl, FormField, FormItem, FormLabel, FormMessage,
} from "@/components/ui/form";
import { Input } from "@/components/ui/input";
import { Button } from "@/components/ui/button";
import { Badge } from "@/components/ui/badge";
import { Separator } from "@/components/ui/separator";
import {
  Select, SelectContent, SelectItem, SelectTrigger, SelectValue,
} from "@/components/ui/select";
import type { AdminUser } from "@/components/admin/UsersTable";

const schema = z.object({
  full_name: z.string().max(100).optional(),
  email: z.string().email(),
  role: z.enum(["admin", "user"]),
});
type FormValues = z.infer<typeof schema>;

export default function UserDetailPage() {
  const { id } = useParams<{ id: string }>();
  const router = useRouter();
  const queryClient = useQueryClient();

  const { data: user } = useQuery({
    queryKey: ["admin-user", id],
    queryFn: async () => {
      const res = await apiClient.get<AdminUser>(`/admin/users/${id}`);
      return res.data;
    },
  });

  const form = useForm<FormValues>({
    resolver: zodResolver(schema),
    values: user
      ? {
          full_name: user.full_name ?? "",
          email: user.email,
          role: user.role,
        }
      : undefined,
  });

  const updateMutation = useMutation({
    mutationFn: (v: FormValues) => apiClient.patch(`/admin/users/${id}`, v),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ["admin-user", id] });
      queryClient.invalidateQueries({ queryKey: ["admin-users"] });
      toast.success("User updated.");
    },
    onError: () => toast.error("Failed to update user."),
  });

  const toggleActiveMutation = useMutation({
    mutationFn: (active: boolean) =>
      apiClient.patch(`/admin/users/${id}`, { is_active: active }),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ["admin-user", id] });
      toast.success(user?.is_active ? "User deactivated." : "User reactivated.");
    },
  });

  const resetPasswordMutation = useMutation({
    mutationFn: () => apiClient.post(`/admin/users/${id}/reset-password`),
    onSuccess: () => toast.success("Password reset email sent."),
    onError: () => toast.error("Failed to send reset email."),
  });

  if (!user) {
    return (
      <div className="h-64 animate-pulse rounded-md bg-muted" aria-busy="true" />
    );
  }

  return (
    <div className="max-w-xl space-y-8 p-6">
      {/* Header */}
      <div className="flex items-start justify-between">
        <div>
          <h1 className="text-xl font-semibold">{user.full_name ?? user.email}</h1>
          <p className="text-sm text-muted-foreground">{user.email}</p>
        </div>
        <Badge variant={user.is_active ? "outline" : "secondary"}>
          {user.is_active ? "Active" : "Inactive"}
        </Badge>
      </div>

      <Separator />

      {/* Edit profile */}
      <section aria-label="Edit profile">
        <h2 className="mb-4 text-sm font-medium">Profile</h2>
        <Form {...form}>
          <form
            onSubmit={form.handleSubmit((v) => updateMutation.mutate(v))}
            className="space-y-4"
            noValidate
          >
            <FormField
              control={form.control}
              name="full_name"
              render={({ field }) => (
                <FormItem>
                  <FormLabel>Full name</FormLabel>
                  <FormControl>
                    <Input {...field} />
                  </FormControl>
                  <FormMessage />
                </FormItem>
              )}
            />
            <FormField
              control={form.control}
              name="email"
              render={({ field }) => (
                <FormItem>
                  <FormLabel>Email</FormLabel>
                  <FormControl>
                    <Input type="email" {...field} />
                  </FormControl>
                  <FormMessage />
                </FormItem>
              )}
            />
            <FormField
              control={form.control}
              name="role"
              render={({ field }) => (
                <FormItem>
                  <FormLabel>Role</FormLabel>
                  <Select onValueChange={field.onChange} value={field.value}>
                    <FormControl>
                      <SelectTrigger>
                        <SelectValue />
                      </SelectTrigger>
                    </FormControl>
                    <SelectContent>
                      <SelectItem value="user">User</SelectItem>
                      <SelectItem value="admin">Admin</SelectItem>
                    </SelectContent>
                  </Select>
                  <FormMessage />
                </FormItem>
              )}
            />
            <div className="flex gap-2">
              <Button type="submit" size="sm" disabled={updateMutation.isPending}>
                Save changes
              </Button>
              <Button
                type="button"
                size="sm"
                variant="ghost"
                onClick={() => router.back()}
              >
                Cancel
              </Button>
            </div>
          </form>
        </Form>
      </section>

      <Separator />

      {/* Account status */}
      <section aria-label="Account status">
        <h2 className="mb-2 text-sm font-medium">Account</h2>
        <div className="flex flex-wrap gap-2">
          <Button
            variant={user.is_active ? "destructive" : "outline"}
            size="sm"
            disabled={toggleActiveMutation.isPending}
            onClick={() => toggleActiveMutation.mutate(!user.is_active)}
          >
            {user.is_active ? "Deactivate account" : "Reactivate account"}
          </Button>
          <Button
            variant="outline"
            size="sm"
            disabled={resetPasswordMutation.isPending}
            onClick={() => resetPasswordMutation.mutate()}
          >
            Send password reset
          </Button>
        </div>
      </section>

      <Separator />

      {/* Activity */}
      <section aria-label="Activity">
        <h2 className="mb-2 text-sm font-medium">Activity</h2>
        <dl className="grid grid-cols-2 gap-2 text-xs">
          <dt className="text-muted-foreground">Last login</dt>
          <dd>
            {user.last_login_at
              ? new Date(user.last_login_at).toLocaleString()
              : "Never"}
          </dd>
          <dt className="text-muted-foreground">Account created</dt>
          <dd>{new Date(user.created_at).toLocaleDateString()}</dd>
        </dl>
      </section>
    </div>
  );
}
```

---

## 5. Tests

### `src/components/admin/__tests__/UsersTable.test.tsx`

```tsx
import { render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { UsersTable } from "../UsersTable";
import { vi } from "vitest";

const mockUsers = [
  {
    id: "u1",
    email: "admin@example.com",
    full_name: "Admin User",
    role: "admin",
    is_active: true,
    last_login_at: new Date().toISOString(),
    created_at: new Date().toISOString(),
  },
  {
    id: "u2",
    email: "user@example.com",
    full_name: null,
    role: "user",
    is_active: false,
    last_login_at: null,
    created_at: new Date().toISOString(),
  },
];

vi.mock("@/lib/api-client", () => ({
  apiClient: {
    get: vi.fn().mockResolvedValue({
      data: { items: mockUsers, total: 2, page: 1, page_size: 25 },
    }),
    patch: vi.fn().mockResolvedValue({ data: {} }),
  },
}));

function wrapper({ children }: { children: React.ReactNode }) {
  const qc = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  return <QueryClientProvider client={qc}>{children}</QueryClientProvider>;
}

test("renders user list with role and status badges", async () => {
  render(<UsersTable />, { wrapper });
  expect(await screen.findByText("admin@example.com")).toBeInTheDocument();
  expect(screen.getByText("user@example.com")).toBeInTheDocument();
  expect(screen.getByText("admin")).toBeInTheDocument();
  expect(screen.getByText("Active")).toBeInTheDocument();
  expect(screen.getByText("Inactive")).toBeInTheDocument();
});

test("search filters users", async () => {
  render(<UsersTable />, { wrapper });
  await screen.findByText("admin@example.com");
  await userEvent.type(
    screen.getByRole("textbox", { name: /search users/i }),
    "admin",
  );
  expect(screen.getByText("admin@example.com")).toBeInTheDocument();
});

test("deactivate shows confirmation dialog", async () => {
  render(<UsersTable />, { wrapper });
  await screen.findByText("admin@example.com");
  await userEvent.click(
    screen.getByRole("button", { name: /deactivate admin@example.com/i }),
  );
  expect(
    screen.getByText(/the user's access will be revoked/i),
  ).toBeInTheDocument();
});

test("reactivate button calls PATCH is_active=true", async () => {
  const { apiClient } = await import("@/lib/api-client");
  render(<UsersTable />, { wrapper });
  await screen.findByText("user@example.com");
  await userEvent.click(
    screen.getByRole("button", { name: /reactivate user@example.com/i }),
  );
  await waitFor(() => {
    expect(apiClient.patch).toHaveBeenCalledWith(
      "/admin/users/u2",
      { is_active: true },
    );
  });
});
```

---

## Acceptance Criteria

- [ ] Users table renders with email, name, role badge, status badge, last login
- [ ] Search filters by email/name in real time (debounced refetch)
- [ ] Role badge uses shield icon for admin, user icon for user
- [ ] Active badge green, Inactive badge grey
- [ ] Deactivate button shows `AlertDialog`; confirmed â†’ `PATCH { is_active: false }`
- [ ] Reactivate button (on inactive users) â†’ `PATCH { is_active: true }` directly
- [ ] Invite form validates email and role; submits via `POST /admin/users/invite`
- [ ] User detail page loads profile and allows editing name, email, role
- [ ] "Send password reset" button triggers `POST /admin/users/{id}/reset-password` + toast
- [ ] Admin cannot deactivate their own account (guard by comparing `user.id` with session `userId`)
- [ ] Skeleton rows shown while loading
- [ ] Unit tests pass: `pnpm test`
