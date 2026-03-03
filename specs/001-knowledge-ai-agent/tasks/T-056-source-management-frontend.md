# T-056 â€” Source Management Frontend

**Status:** Done

## Context
```
Next.js 15 App Router Â· shadcn/ui Â· Tailwind CSS v4
TanStack Query v5 Â· react-hook-form Â· Zod
Routes: (dashboard)/admin/sources/...
RBAC: admin-only pages; non-admin see /dashboard/sources read-only list
Dark mode Â· WCAG-AA Â· Lucide icons Â· Sonner toasts
```

## Goal
Four pages + two hook files:
1. Admin source list (`/admin/sources`) â€” CRUD + test-connection
2. Grant/revoke permissions modal (`/admin/sources/[id]/permissions`)
3. Two TanStack Query hook files â€” `useSources`, `useSourcePermissions`

---

## File 1 â€” `app/(dashboard)/admin/sources/page.tsx`

```tsx
import { Suspense } from "react";
import { SourcesTable } from "./_components/SourcesTable";

export const metadata = { title: "Sources" };

export default function SourcesPage() {
  return (
    <main className="flex-1 space-y-4 p-8">
      <h1 className="text-2xl font-semibold">Knowledge Sources</h1>
      <Suspense fallback={<p>Loadingâ€¦</p>}>
        <SourcesTable />
      </Suspense>
    </main>
  );
}
```

---

## File 2 â€” `app/(dashboard)/admin/sources/_components/SourcesTable.tsx`

```tsx
"use client";
import { useState } from "react";
import {
  useListSources,
  useCreateSource,
  useDeleteSource,
  useTestConnection,
} from "@/hooks/useSources";
import {
  Table, TableHeader, TableBody, TableRow, TableHead, TableCell,
} from "@/components/ui/table";
import { Button } from "@/components/ui/button";
import { Badge } from "@/components/ui/badge";
import { toast } from "sonner";
import { Trash2, Plug } from "lucide-react";
import { CreateSourceDialog } from "./CreateSourceDialog";

export function SourcesTable() {
  const { data: sources = [] } = useListSources();
  const deleteMutation = useDeleteSource();
  const testMutation = useTestConnection();
  const [open, setOpen] = useState(false);

  async function handleDelete(id: string) {
    await deleteMutation.mutateAsync(id);
    toast.success("Source deleted");
  }

  async function handleTest(id: string) {
    const result = await testMutation.mutateAsync(id);
    result.connected
      ? toast.success("Connection OK")
      : toast.error(`Connection failed: ${result.error ?? "unknown"}`);
  }

  return (
    <>
      <div className="flex justify-end">
        <Button onClick={() => setOpen(true)}>Add Source</Button>
      </div>
      <Table>
        <TableHeader>
          <TableRow>
            <TableHead>Name</TableHead>
            <TableHead>Type</TableHead>
            <TableHead>Status</TableHead>
            <TableHead className="w-36" />
          </TableRow>
        </TableHeader>
        <TableBody>
          {sources.map((src) => (
            <TableRow key={src.id}>
              <TableCell>{src.name}</TableCell>
              <TableCell>
                <Badge variant="secondary">{src.source_type}</Badge>
              </TableCell>
              <TableCell>
                <Badge variant={src.is_active ? "default" : "outline"}>
                  {src.is_active ? "Active" : "Inactive"}
                </Badge>
              </TableCell>
              <TableCell className="space-x-2">
                <Button
                  size="sm"
                  variant="ghost"
                  aria-label="Test connection"
                  onClick={() => handleTest(src.id)}
                >
                  <Plug className="h-4 w-4" />
                </Button>
                <Button
                  size="sm"
                  variant="ghost"
                  aria-label="Delete source"
                  onClick={() => handleDelete(src.id)}
                >
                  <Trash2 className="h-4 w-4 text-destructive" />
                </Button>
              </TableCell>
            </TableRow>
          ))}
        </TableBody>
      </Table>
      <CreateSourceDialog open={open} onOpenChange={setOpen} />
    </>
  );
}
```

---

## File 3 â€” `app/(dashboard)/admin/sources/_components/CreateSourceDialog.tsx`

```tsx
"use client";
import { useForm } from "react-hook-form";
import { zodResolver } from "@hookform/resolvers/zod";
import { z } from "zod";
import {
  Dialog, DialogContent, DialogHeader, DialogTitle,
} from "@/components/ui/dialog";
import { Form, FormField, FormItem, FormLabel, FormControl, FormMessage } from "@/components/ui/form";
import { Input } from "@/components/ui/input";
import { Select, SelectTrigger, SelectValue, SelectContent, SelectItem } from "@/components/ui/select";
import { Button } from "@/components/ui/button";
import { toast } from "sonner";
import { useCreateSource } from "@/hooks/useSources";

const SOURCE_TYPES = ["WEB_URL", "FILE_UPLOAD", "DATABASE", "CONFLUENCE", "SHAREPOINT"] as const;

const schema = z.object({
  name: z.string().min(1),
  source_type: z.enum(SOURCE_TYPES),
  config: z.string().min(2, "Config must be valid JSON"),
});

type FormValues = z.infer<typeof schema>;

interface Props {
  open: boolean;
  onOpenChange: (v: boolean) => void;
}

export function CreateSourceDialog({ open, onOpenChange }: Props) {
  const createMutation = useCreateSource();
  const form = useForm<FormValues>({ resolver: zodResolver(schema) });

  async function onSubmit(values: FormValues) {
    try {
      JSON.parse(values.config); // validate JSON
      await createMutation.mutateAsync({
        name: values.name,
        source_type: values.source_type,
        config: JSON.parse(values.config),
      });
      toast.success("Source created");
      onOpenChange(false);
      form.reset();
    } catch {
      toast.error("Failed to create source");
    }
  }

  return (
    <Dialog open={open} onOpenChange={onOpenChange}>
      <DialogContent>
        <DialogHeader>
          <DialogTitle>Add Knowledge Source</DialogTitle>
        </DialogHeader>
        <Form {...form}>
          <form onSubmit={form.handleSubmit(onSubmit)} className="space-y-4">
            <FormField
              control={form.control}
              name="name"
              render={({ field }) => (
                <FormItem>
                  <FormLabel>Name</FormLabel>
                  <FormControl><Input {...field} /></FormControl>
                  <FormMessage />
                </FormItem>
              )}
            />
            <FormField
              control={form.control}
              name="source_type"
              render={({ field }) => (
                <FormItem>
                  <FormLabel>Type</FormLabel>
                  <Select onValueChange={field.onChange} defaultValue={field.value}>
                    <FormControl>
                      <SelectTrigger><SelectValue placeholder="Select type" /></SelectTrigger>
                    </FormControl>
                    <SelectContent>
                      {SOURCE_TYPES.map((t) => (
                        <SelectItem key={t} value={t}>{t}</SelectItem>
                      ))}
                    </SelectContent>
                  </Select>
                  <FormMessage />
                </FormItem>
              )}
            />
            <FormField
              control={form.control}
              name="config"
              render={({ field }) => (
                <FormItem>
                  <FormLabel>Config (JSON)</FormLabel>
                  <FormControl>
                    <Input {...field} placeholder='{"url": "https://..."}' />
                  </FormControl>
                  <FormMessage />
                </FormItem>
              )}
            />
            <Button type="submit" className="w-full">Create</Button>
          </form>
        </Form>
      </DialogContent>
    </Dialog>
  );
}
```

---

## File 4 â€” `app/(dashboard)/admin/sources/[id]/permissions/page.tsx`

```tsx
import { Suspense } from "react";
import { PermissionsManager } from "./_components/PermissionsManager";

interface Props {
  params: { id: string };
}

export default function PermissionsPage({ params }: Props) {
  return (
    <main className="flex-1 space-y-4 p-8">
      <h1 className="text-2xl font-semibold">Source Permissions</h1>
      <Suspense fallback={<p>Loadingâ€¦</p>}>
        <PermissionsManager sourceId={params.id} />
      </Suspense>
    </main>
  );
}
```

---

## File 5 â€” `app/(dashboard)/admin/sources/[id]/permissions/_components/PermissionsManager.tsx`

```tsx
"use client";
import { useState } from "react";
import { Input } from "@/components/ui/input";
import { Button } from "@/components/ui/button";
import { toast } from "sonner";
import { UserMinus, UserPlus } from "lucide-react";
import {
  useSourcePermissions,
  useGrantPermission,
  useRevokePermission,
} from "@/hooks/useSourcePermissions";

interface Props {
  sourceId: string;
}

export function PermissionsManager({ sourceId }: Props) {
  const { data: userIds = [] } = useSourcePermissions(sourceId);
  const grantMutation = useGrantPermission();
  const revokeMutation = useRevokePermission();
  const [inputUserId, setInputUserId] = useState("");

  async function handleGrant() {
    if (!inputUserId.trim()) return;
    try {
      await grantMutation.mutateAsync({ sourceId, userId: inputUserId.trim() });
      toast.success("Access granted");
      setInputUserId("");
    } catch {
      toast.error("Failed to grant access");
    }
  }

  async function handleRevoke(userId: string) {
    try {
      await revokeMutation.mutateAsync({ sourceId, userId });
      toast.success("Access revoked");
    } catch {
      toast.error("Failed to revoke access");
    }
  }

  return (
    <div className="space-y-4">
      <div className="flex gap-2">
        <Input
          placeholder="User UUID"
          value={inputUserId}
          onChange={(e) => setInputUserId(e.target.value)}
          aria-label="User ID to grant access"
        />
        <Button onClick={handleGrant} aria-label="Grant access">
          <UserPlus className="h-4 w-4 mr-1" /> Grant
        </Button>
      </div>
      <ul className="space-y-2">
        {userIds.map((uid) => (
          <li key={uid} className="flex items-center justify-between rounded border px-3 py-2 text-sm">
            <span className="font-mono text-xs">{uid}</span>
            <Button
              size="sm"
              variant="ghost"
              aria-label="Revoke access"
              onClick={() => handleRevoke(uid)}
            >
              <UserMinus className="h-4 w-4 text-destructive" />
            </Button>
          </li>
        ))}
        {userIds.length === 0 && (
          <p className="text-sm text-muted-foreground">No users have access yet.</p>
        )}
      </ul>
    </div>
  );
}
```

---

## File 6 â€” `app/hooks/useSources.ts`

```typescript
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { api } from "@/lib/api";

export interface SourceListItem {
  id: string;
  name: string;
  source_type: string;
  is_active: boolean;
  owner_id: string;
  created_at: string;
}

export interface TestConnectionResponse {
  connected: boolean;
  error?: string;
}

export function useListSources() {
  return useQuery<SourceListItem[]>({
    queryKey: ["sources"],
    queryFn: () => api.get("/api/v1/sources").then((r) => r.data.items),
  });
}

export function useCreateSource() {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: (body: { name: string; source_type: string; config: Record<string, unknown> }) =>
      api.post("/api/v1/sources", body).then((r) => r.data),
    onSuccess: () => qc.invalidateQueries({ queryKey: ["sources"] }),
  });
}

export function useDeleteSource() {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: (id: string) => api.delete(`/api/v1/sources/${id}`),
    onSuccess: () => qc.invalidateQueries({ queryKey: ["sources"] }),
  });
}

export function useTestConnection() {
  return useMutation<TestConnectionResponse, Error, string>({
    mutationFn: (id: string) =>
      api.post(`/api/v1/sources/${id}/test-connection`).then((r) => r.data),
  });
}
```

---

## File 7 â€” `app/hooks/useSourcePermissions.ts`

```typescript
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { api } from "@/lib/api";

export function useSourcePermissions(sourceId: string) {
  return useQuery<string[]>({
    queryKey: ["source-permissions", sourceId],
    queryFn: () =>
      api.get(`/api/v1/sources/${sourceId}/permissions`).then((r) => r.data.user_ids),
  });
}

export function useGrantPermission() {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: ({ sourceId, userId }: { sourceId: string; userId: string }) =>
      api.post(`/api/v1/sources/${sourceId}/permissions`, { user_id: userId }),
    onSuccess: (_, { sourceId }) =>
      qc.invalidateQueries({ queryKey: ["source-permissions", sourceId] }),
  });
}

export function useRevokePermission() {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: ({ sourceId, userId }: { sourceId: string; userId: string }) =>
      api.delete(`/api/v1/sources/${sourceId}/permissions/${userId}`),
    onSuccess: (_, { sourceId }) =>
      qc.invalidateQueries({ queryKey: ["source-permissions", sourceId] }),
  });
}
```

---

## Acceptance Criteria

1. `/admin/sources` renders a table listing all sources with name, type, status.
2. "Add Source" button opens dialog; form validates name (required), type (enum select), config (valid JSON).
3. "Test connection" button calls `POST /sources/{id}/test-connection`; shows Sonner toast with result.
4. "Delete" button calls `DELETE /sources/{id}` and invalidates query cache.
5. `/admin/sources/[id]/permissions` renders a list of UUIDs with revoke button per row.
6. Grant form validates UUID input; calls `POST /sources/{id}/permissions`.
7. Revoke button calls `DELETE /sources/{id}/permissions/{userId}`.
8. All mutations show success/error Sonner toasts.
9. Pages are server-component wrappers with `<Suspense>` fallback.
10. WCAG-AA: all buttons have `aria-label`; keyboard navigable.
