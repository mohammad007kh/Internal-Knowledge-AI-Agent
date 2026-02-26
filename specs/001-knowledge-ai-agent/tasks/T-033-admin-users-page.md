# T-033 — Admin Users Page (Frontend)

## Metadata
| Field | Value |
|---|---|
| **ID** | T-033 |
| **Title** | Admin Users Page — paginated list, invite modal, role change, deactivate |
| **Phase** | 1 — Authentication & User Management |
| **Domain** | Frontend / Admin UI |
| **Depends on** | T-028, T-031, T-032, T-038 |
| **Blocks** | T-036, T-039 |
| **Est. complexity** | M |

### Project Standards
| Standard | Value |
|---|---|
| Python | 3.12 |
| Backend | FastAPI · SQLAlchemy 2.x · Pydantic v2 · dependency-injector |
| Frontend | Next.js 15 App Router · shadcn/ui · Tailwind CSS v4 |
| State | React Context · TanStack Query v5 · react-hook-form · Zod |
| Auth | JWT 15-min access + 7-day rotating httpOnly refresh cookie · bcrypt · RBAC (admin/user) |
| Error Format | RFC 7807 Problem Details — all non-2xx API responses |
| UI | Dark mode · responsive · WCAG-AA · no animations · Lucide icons · Sonner toasts |
| Testing | pytest + httpx + Playwright · ≥80% coverage |
| Infrastructure | Docker Compose 9 services |

### Domain Rules
- Source access is per-user per-source; never expose unapproved source data (FR-019)
- Invitations are the only path to new accounts (FR-021)
- All passwords validated via validate_password_policy() (FR-034)

---

## Goal
Build the `/admin/users` page (admin-only) that lets administrators:
1. **List** all users (paginated, 50 per page)
2. **Invite** a new user by email (opens a modal)
3. **Change role** for any user (admin ↔ user)
4. **Deactivate** a user (soft-delete; cannot deactivate self)

The page lives under `app/(dashboard)/admin/users/`. Access control is enforced both in
the Next.js middleware (T-038) and the backend router (T-028).

---

## Deliverables

### 1. `src/frontend/lib/api/users.ts` — typed API functions
```typescript
import { apiClient } from "@/lib/api-client";

export type UserRole = "admin" | "user";

export interface UserListItem {
  id: string;
  email: string;
  role: UserRole;
  is_active: boolean;
  created_at: string;
}

export interface PaginatedUsers {
  items: UserListItem[];
  total: number;
  limit: number;
  offset: number;
}

export interface InviteUserRequest {
  email: string;
  role: UserRole;
}

export interface ChangeRoleRequest {
  role: UserRole;
}

export async function listUsersApi(
  limit = 50,
  offset = 0
): Promise<PaginatedUsers> {
  return apiClient<PaginatedUsers>(
    `/users?limit=${limit}&offset=${offset}`
  );
}

export async function inviteUserApi(body: InviteUserRequest): Promise<void> {
  await apiClient<void>("/users/invitations", {
    method: "POST",
    body: JSON.stringify(body),
  });
}

export async function changeUserRoleApi(
  userId: string,
  body: ChangeRoleRequest
): Promise<UserListItem> {
  return apiClient<UserListItem>(`/users/${userId}/role`, {
    method: "PATCH",
    body: JSON.stringify(body),
  });
}

export async function deactivateUserApi(userId: string): Promise<void> {
  await apiClient<void>(`/users/${userId}`, { method: "DELETE" });
}
```

---

### 2. `src/frontend/features/users/hooks/useUsersQueries.ts`
```typescript
"use client";

import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import {
  changeUserRoleApi,
  deactivateUserApi,
  inviteUserApi,
  listUsersApi,
  type InviteUserRequest,
  type ChangeRoleRequest,
} from "@/lib/api/users";

const USERS_KEY = ["admin", "users"] as const;

export function useUsersList(limit = 50, offset = 0) {
  return useQuery({
    queryKey: [...USERS_KEY, limit, offset],
    queryFn: () => listUsersApi(limit, offset),
  });
}

export function useInviteUser() {
  const qc = useQueryClient();
  return useMutation<void, Error, InviteUserRequest>({
    mutationFn: inviteUserApi,
    onSuccess: () => qc.invalidateQueries({ queryKey: USERS_KEY }),
  });
}

export function useChangeRole() {
  const qc = useQueryClient();
  return useMutation<
    Awaited<ReturnType<typeof changeUserRoleApi>>,
    Error,
    { userId: string; body: ChangeRoleRequest }
  >({
    mutationFn: ({ userId, body }) => changeUserRoleApi(userId, body),
    onSuccess: () => qc.invalidateQueries({ queryKey: USERS_KEY }),
  });
}

export function useDeactivateUser() {
  const qc = useQueryClient();
  return useMutation<void, Error, string>({
    mutationFn: deactivateUserApi,
    onSuccess: () => qc.invalidateQueries({ queryKey: USERS_KEY }),
  });
}
```

---

### 3. `src/frontend/features/users/components/InviteUserModal.tsx`
```tsx
"use client";

import { useForm } from "react-hook-form";
import { zodResolver } from "@hookform/resolvers/zod";
import { z } from "zod";
import { toast } from "sonner";
import {
  Dialog,
  DialogContent,
  DialogHeader,
  DialogTitle,
  DialogFooter,
} from "@/components/ui/dialog";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import {
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue,
} from "@/components/ui/select";
import { useInviteUser } from "../hooks/useUsersQueries";

const inviteSchema = z.object({
  email: z.string().email("Enter a valid email address"),
  role: z.enum(["admin", "user"]),
});
type InviteFormValues = z.infer<typeof inviteSchema>;

interface Props {
  open: boolean;
  onClose: () => void;
}

export function InviteUserModal({ open, onClose }: Props) {
  const invite = useInviteUser();

  const {
    register,
    handleSubmit,
    setValue,
    reset,
    formState: { errors, isSubmitting },
  } = useForm<InviteFormValues>({
    resolver: zodResolver(inviteSchema),
    defaultValues: { role: "user" },
  });

  const onSubmit = async (values: InviteFormValues) => {
    try {
      await invite.mutateAsync(values);
      toast.success(`Invitation sent to ${values.email}`);
      reset();
      onClose();
    } catch (err: unknown) {
      const message =
        err instanceof Error ? err.message : "Failed to send invitation";
      toast.error(message);
    }
  };

  return (
    <Dialog open={open} onOpenChange={(o) => !o && onClose()}>
      <DialogContent className="sm:max-w-md">
        <DialogHeader>
          <DialogTitle>Invite user</DialogTitle>
        </DialogHeader>

        <form onSubmit={handleSubmit(onSubmit)} noValidate className="space-y-4">
          <div className="space-y-1">
            <Label htmlFor="invite-email">Email address</Label>
            <Input
              id="invite-email"
              type="email"
              placeholder="colleague@example.com"
              aria-invalid={!!errors.email}
              {...register("email")}
            />
            {errors.email && (
              <p className="text-sm text-destructive">{errors.email.message}</p>
            )}
          </div>

          <div className="space-y-1">
            <Label htmlFor="invite-role">Role</Label>
            <Select
              defaultValue="user"
              onValueChange={(v) =>
                setValue("role", v as "admin" | "user", { shouldValidate: true })
              }
            >
              <SelectTrigger id="invite-role">
                <SelectValue />
              </SelectTrigger>
              <SelectContent>
                <SelectItem value="user">User</SelectItem>
                <SelectItem value="admin">Admin</SelectItem>
              </SelectContent>
            </Select>
          </div>

          <DialogFooter>
            <Button type="button" variant="outline" onClick={onClose}>
              Cancel
            </Button>
            <Button type="submit" disabled={isSubmitting}>
              {isSubmitting ? "Sending…" : "Send invitation"}
            </Button>
          </DialogFooter>
        </form>
      </DialogContent>
    </Dialog>
  );
}
```

---

### 4. `src/frontend/app/(dashboard)/admin/users/page.tsx`
```tsx
"use client";

import { useState } from "react";
import { toast } from "sonner";
import { UserPlus, Shield, ShieldOff, Trash2 } from "lucide-react";

import { Button } from "@/components/ui/button";
import {
  Table,
  TableBody,
  TableCell,
  TableHead,
  TableHeader,
  TableRow,
} from "@/components/ui/table";
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

import { useUsersList, useChangeRole, useDeactivateUser } from "@/features/users/hooks/useUsersQueries";
import { InviteUserModal } from "@/features/users/components/InviteUserModal";
import { useAuth } from "@/features/auth/context/AuthContext";

const PAGE_SIZE = 50;

export default function AdminUsersPage() {
  const { user: currentUser } = useAuth();
  const [offset, setOffset] = useState(0);
  const [inviteOpen, setInviteOpen] = useState(false);
  const [confirmDeactivate, setConfirmDeactivate] = useState<string | null>(null);

  const { data, isLoading, error } = useUsersList(PAGE_SIZE, offset);
  const changeRole = useChangeRole();
  const deactivate = useDeactivateUser();

  const handleChangeRole = async (userId: string, currentRole: "admin" | "user") => {
    const newRole = currentRole === "admin" ? "user" : "admin";
    try {
      await changeRole.mutateAsync({ userId, body: { role: newRole } });
      toast.success(`Role changed to ${newRole}`);
    } catch (err: unknown) {
      toast.error(err instanceof Error ? err.message : "Failed to change role");
    }
  };

  const handleDeactivate = async (userId: string) => {
    try {
      await deactivate.mutateAsync(userId);
      toast.success("User deactivated");
    } catch (err: unknown) {
      toast.error(err instanceof Error ? err.message : "Failed to deactivate user");
    } finally {
      setConfirmDeactivate(null);
    }
  };

  if (error) {
    return (
      <div className="p-6">
        <p className="text-destructive">Failed to load users. Please refresh.</p>
      </div>
    );
  }

  return (
    <div className="p-6 space-y-4">
      <div className="flex items-center justify-between">
        <div>
          <h1 className="text-xl font-semibold">Users</h1>
          {data && (
            <p className="text-sm text-muted-foreground">
              {data.total} total user{data.total !== 1 ? "s" : ""}
            </p>
          )}
        </div>
        <Button onClick={() => setInviteOpen(true)} size="sm">
          <UserPlus className="mr-2 h-4 w-4" />
          Invite user
        </Button>
      </div>

      <div className="rounded-md border">
        <Table>
          <TableHeader>
            <TableRow>
              <TableHead>Email</TableHead>
              <TableHead>Role</TableHead>
              <TableHead>Status</TableHead>
              <TableHead>Joined</TableHead>
              <TableHead className="w-[120px]">Actions</TableHead>
            </TableRow>
          </TableHeader>
          <TableBody>
            {isLoading
              ? Array.from({ length: 5 }).map((_, i) => (
                  <TableRow key={i}>
                    {Array.from({ length: 5 }).map((__, j) => (
                      <TableCell key={j}>
                        <div className="h-4 w-full animate-pulse rounded bg-muted" />
                      </TableCell>
                    ))}
                  </TableRow>
                ))
              : data?.items.map((u) => (
                  <TableRow key={u.id}>
                    <TableCell className="font-mono text-sm">{u.email}</TableCell>
                    <TableCell>
                      <Badge variant={u.role === "admin" ? "default" : "secondary"}>
                        {u.role}
                      </Badge>
                    </TableCell>
                    <TableCell>
                      <Badge variant={u.is_active ? "outline" : "destructive"}>
                        {u.is_active ? "Active" : "Inactive"}
                      </Badge>
                    </TableCell>
                    <TableCell className="text-sm text-muted-foreground">
                      {new Date(u.created_at).toLocaleDateString()}
                    </TableCell>
                    <TableCell>
                      <div className="flex items-center gap-1">
                        <Button
                          variant="ghost"
                          size="icon"
                          aria-label={`Change role for ${u.email}`}
                          disabled={changeRole.isPending}
                          onClick={() => handleChangeRole(u.id, u.role)}
                        >
                          {u.role === "admin" ? (
                            <ShieldOff className="h-4 w-4" />
                          ) : (
                            <Shield className="h-4 w-4" />
                          )}
                        </Button>
                        <Button
                          variant="ghost"
                          size="icon"
                          aria-label={`Deactivate ${u.email}`}
                          disabled={
                            !u.is_active || u.id === currentUser?.id
                          }
                          onClick={() => setConfirmDeactivate(u.id)}
                          className="text-destructive hover:text-destructive"
                        >
                          <Trash2 className="h-4 w-4" />
                        </Button>
                      </div>
                    </TableCell>
                  </TableRow>
                ))}
          </TableBody>
        </Table>
      </div>

      {/* Pagination */}
      {data && data.total > PAGE_SIZE && (
        <div className="flex justify-end gap-2">
          <Button
            variant="outline"
            size="sm"
            disabled={offset === 0}
            onClick={() => setOffset((o) => Math.max(0, o - PAGE_SIZE))}
          >
            Previous
          </Button>
          <Button
            variant="outline"
            size="sm"
            disabled={offset + PAGE_SIZE >= data.total}
            onClick={() => setOffset((o) => o + PAGE_SIZE)}
          >
            Next
          </Button>
        </div>
      )}

      <InviteUserModal open={inviteOpen} onClose={() => setInviteOpen(false)} />

      {/* Deactivation confirm dialog */}
      <AlertDialog
        open={!!confirmDeactivate}
        onOpenChange={(o) => !o && setConfirmDeactivate(null)}
      >
        <AlertDialogContent>
          <AlertDialogHeader>
            <AlertDialogTitle>Deactivate user?</AlertDialogTitle>
            <AlertDialogDescription>
              This will prevent the user from signing in. Their data will be
              retained. This action can be reversed by a database administrator.
            </AlertDialogDescription>
          </AlertDialogHeader>
          <AlertDialogFooter>
            <AlertDialogCancel>Cancel</AlertDialogCancel>
            <AlertDialogAction
              className="bg-destructive text-destructive-foreground hover:bg-destructive/90"
              onClick={() =>
                confirmDeactivate && handleDeactivate(confirmDeactivate)
              }
            >
              Deactivate
            </AlertDialogAction>
          </AlertDialogFooter>
        </AlertDialogContent>
      </AlertDialog>
    </div>
  );
}
```

---

## Files to Create

| Path | Description |
|---|---|
| `src/frontend/lib/api/users.ts` | Typed API wrapper functions for users endpoints |
| `src/frontend/features/users/hooks/useUsersQueries.ts` | TanStack Query hooks for user list + mutations |
| `src/frontend/features/users/components/InviteUserModal.tsx` | Invite modal with email + role form |
| `src/frontend/app/(dashboard)/admin/users/page.tsx` | Admin users list page |

---

## Gate Criteria
- `make lint` passes — no TypeScript errors
- `/admin/users` renders an accessible table of users with pagination
- "Invite user" button opens the modal; submitting calls `POST /api/v1/users/invitations`
- Role toggle icon button calls `PATCH /api/v1/users/{id}/role`; success shows Sonner toast
- Deactivate icon button is disabled for the current user's own row
- Confirmation dialog appears before deactivation; confirming calls `DELETE /api/v1/users/{id}`
- After any mutation, the users query is invalidated and the table refreshes automatically
