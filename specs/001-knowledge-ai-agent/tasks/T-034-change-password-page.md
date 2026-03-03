# T-034 â€” Change-Password Page (Frontend)

## Metadata
| Field | Value |
|---|---|
| **Status** | Done |
| **ID** | T-034 |
| **Title** | Change-Password Page â€” forced and voluntary password change |
| **Phase** | 1 â€” Authentication & User Management |
| **Domain** | Frontend / Auth UI |
| **Depends on** | T-030, T-031, T-032 |
| **Blocks** | T-036 |
| **Est. complexity** | S |

### Project Standards
| Standard | Value |
|---|---|
| Python | 3.12 |
| Backend | FastAPI Â· SQLAlchemy 2.x Â· Pydantic v2 Â· dependency-injector |
| Frontend | Next.js 15 App Router Â· shadcn/ui Â· Tailwind CSS v4 |
| State | React Context Â· TanStack Query v5 Â· react-hook-form Â· Zod |
| Auth | JWT 15-min access + 7-day rotating httpOnly refresh cookie Â· bcrypt Â· RBAC (admin/user) |
| Error Format | RFC 7807 Problem Details â€” all non-2xx API responses |
| UI | Dark mode Â· responsive Â· WCAG-AA Â· no animations Â· Lucide icons Â· Sonner toasts |
| Testing | pytest + httpx + Playwright Â· â‰¥80% coverage |
| Infrastructure | Docker Compose 9 services |

### Domain Rules
- All passwords validated via validate_password_policy() (FR-034)
- When `must_change_password === true`, the user is redirected here from login automatically and the "current password" field is omitted (the old temporary password has already been verified)

---

## Goal
Create `/auth/change-password` â€” a protected page (requires auth) that handles both:
- **Forced change**: `must_change_password === true` in JWT â†’ `current_password` field is
  hidden; user just sets new password
- **Voluntary change**: Accessed from profile/settings â†’ full form with `current_password`

---

## Deliverables

### `src/frontend/app/(auth)/change-password/page.tsx`
```tsx
"use client";

import { useRouter } from "next/navigation";
import { useForm } from "react-hook-form";
import { zodResolver } from "@hookform/resolvers/zod";
import { z } from "zod";
import { toast } from "sonner";

import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import {
  Card,
  CardContent,
  CardDescription,
  CardHeader,
  CardTitle,
} from "@/components/ui/card";
import { useAuth } from "@/features/auth/context/AuthContext";
import { useChangePassword } from "@/features/auth/hooks/useAuthMutations";

// Strong-password shape shared with setup / confirm pages
const passwordRules = z
  .string()
  .min(8, "Password must be at least 8 characters")
  .regex(/[A-Z]/, "Must contain at least one uppercase letter")
  .regex(/[a-z]/, "Must contain at least one lowercase letter")
  .regex(/[0-9]/, "Must contain at least one number");

const forcedSchema = z
  .object({
    new_password: passwordRules,
    confirm_password: z.string().min(1, "Please confirm your password"),
  })
  .refine((d) => d.new_password === d.confirm_password, {
    path: ["confirm_password"],
    message: "Passwords do not match",
  });

const voluntarySchema = forcedSchema.and(
  z.object({ current_password: z.string().min(1, "Current password is required") })
);

type ForcedFormValues = z.infer<typeof forcedSchema>;
type VoluntaryFormValues = z.infer<typeof voluntarySchema>;
type FormValues = ForcedFormValues | VoluntaryFormValues;

export default function ChangePasswordPage() {
  const router = useRouter();
  const { user } = useAuth();
  const changePassword = useChangePassword();

  // Determine mode from JWT claim
  const forced = user?.must_change_password ?? false;
  const schema = forced ? forcedSchema : voluntarySchema;

  const {
    register,
    handleSubmit,
    formState: { errors, isSubmitting },
  } = useForm<FormValues>({ resolver: zodResolver(schema) });

  const onSubmit = async (values: FormValues) => {
    try {
      await changePassword.mutateAsync({
        new_password: (values as ForcedFormValues).new_password,
        current_password: (values as VoluntaryFormValues).current_password,
      });
      toast.success("Password changed successfully");
      router.push("/chat");
    } catch (err: unknown) {
      const message =
        err instanceof Error
          ? err.message
          : "Failed to change password. Please try again.";
      toast.error(message);
    }
  };

  return (
    <Card>
      <CardHeader>
        <CardTitle>{forced ? "Set a new password" : "Change password"}</CardTitle>
        <CardDescription>
          {forced
            ? "You must set a new password before continuing."
            : "Update your account password."}
        </CardDescription>
      </CardHeader>
      <CardContent>
        <form onSubmit={handleSubmit(onSubmit)} noValidate className="space-y-4">
          {!forced && (
            <div className="space-y-1">
              <Label htmlFor="current_password">Current password</Label>
              <Input
                id="current_password"
                type="password"
                autoComplete="current-password"
                aria-invalid={
                  !!(errors as { current_password?: unknown }).current_password
                }
                {...register("current_password" as keyof FormValues)}
              />
              {(errors as { current_password?: { message?: string } })
                .current_password && (
                <p className="text-sm text-destructive">
                  {(errors as { current_password?: { message?: string } })
                    .current_password?.message}
                </p>
              )}
            </div>
          )}

          <div className="space-y-1">
            <Label htmlFor="new_password">New password</Label>
            <Input
              id="new_password"
              type="password"
              autoComplete="new-password"
              aria-invalid={!!(errors as ForcedFormValues).new_password}
              {...register("new_password" as keyof FormValues)}
            />
            {(errors as { new_password?: { message?: string } }).new_password && (
              <p className="text-sm text-destructive">
                {(errors as { new_password?: { message?: string } }).new_password?.message}
              </p>
            )}
          </div>

          <div className="space-y-1">
            <Label htmlFor="confirm_password">Confirm new password</Label>
            <Input
              id="confirm_password"
              type="password"
              autoComplete="new-password"
              aria-invalid={
                !!(errors as { confirm_password?: unknown }).confirm_password
              }
              {...register("confirm_password" as keyof FormValues)}
            />
            {(errors as { confirm_password?: { message?: string } })
              .confirm_password && (
              <p className="text-sm text-destructive">
                {(errors as { confirm_password?: { message?: string } })
                  .confirm_password?.message}
              </p>
            )}
          </div>

          <Button type="submit" className="w-full" disabled={isSubmitting}>
            {isSubmitting ? "Savingâ€¦" : "Change password"}
          </Button>
        </form>
      </CardContent>
    </Card>
  );
}
```

---

## Files to Create

| Path | Description |
|---|---|
| `src/frontend/app/(auth)/change-password/page.tsx` | Forced + voluntary change-password page |

---

## Gate Criteria
- `make lint` passes
- When `user.must_change_password === true`, the "Current password" field is absent from the DOM
- Submitting calls `POST /api/v1/auth/change-password`; on success redirects to `/chat`
- Mismatched confirm password shows inline Zod error without server round-trip
- Weak password (no uppercase) shows inline Zod error before submission
