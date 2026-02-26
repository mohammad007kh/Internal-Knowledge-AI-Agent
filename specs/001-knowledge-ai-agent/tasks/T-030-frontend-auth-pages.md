# T-030 — Frontend Auth Pages (Login, Setup, Password Reset)

## Metadata
| Field | Value |
|---|---|
| **ID** | T-030 |
| **Title** | Frontend Auth Pages — login, invitation setup, password-reset request + confirm |
| **Phase** | 1 — Authentication & User Management |
| **Domain** | Frontend / Auth UI |
| **Depends on** | T-005, T-026, T-031, T-032 |
| **Blocks** | T-036, T-038 |
| **Est. complexity** | M |

### Project Standards
| Standard | Value |
|---|---|
| Python | 3.12 |
| Backend | FastAPI · SQLAlchemy 2.x · Pydantic v2 · dependency-injector |
| Frontend | Next.js 15 App Router · shadcn/ui · Tailwind CSS v4 |
| State | React Context · TanStack Query v5 · react-hook-form · Zod |
| Database | PostgreSQL 16 + pgvector · UUID PKs · soft-delete + audit columns |
| Migrations | Alembic versioned |
| Background | Celery + Redis · Beat replicas=1 STRICT |
| File Storage | MinIO · presigned PUT pattern |
| Auth | JWT 15-min access + 7-day rotating httpOnly refresh cookie · bcrypt · RBAC (admin/user) |
| Encryption | Fernet (connection configs at rest) |
| AI Pipeline | LangGraph 8-node · interrupt() for clarification · SSE streaming |
| Tracing | Langfuse self-hosted · every pipeline run must emit a trace |
| Error Format | RFC 7807 Problem Details — all non-2xx API responses |
| UI | Dark mode · responsive · WCAG-AA · no animations · Lucide icons · Sonner toasts |
| Naming | snake_case vars/files/tables · PascalCase classes · SCREAMING_SNAKE_CASE constants |
| Testing | pytest + httpx + Playwright · ≥80% coverage |
| Infrastructure | Docker Compose 9 services |

### Domain Rules
- Source access is per-user per-source; never expose unapproved source data (FR-019)
- Connection strings and file paths MUST NEVER appear in user-facing output (FR-020)
- Celery Beat MUST run with exactly 1 replica
- File size limit is defined in app_config.yaml; default 50 MB — NOT in .env, NOT hardcoded (FR-035)
- bootstrap_admin executes once on startup only if zero users exist (FR-024)
- Auto-restart is capped at 3 consecutive attempts (FR-033)
- All passwords validated via validate_password_policy() (FR-034)
- Invitations are the only path to new accounts — no self-registration (FR-021)

---

## Goal
Build the four public-facing auth pages under `app/(auth)/` route group. Each page uses
`react-hook-form` + Zod validation, TanStack Query mutations (defined in T-031), Sonner
toasts for feedback, and `shadcn/ui` components. No animations. Dark-mode-aware via CSS
variables. WCAG-AA contrast minimum.

---

## Route Map

| Route | Page file | Description |
|---|---|---|
| `/auth/login` | `app/(auth)/login/page.tsx` | Email + password form → issues token pair |
| `/auth/setup` | `app/(auth)/setup/page.tsx` | Accept invitation (`?token=…`) + set password |
| `/auth/password-reset` | `app/(auth)/password-reset/page.tsx` | Request reset link by email |
| `/auth/password-reset/confirm` | `app/(auth)/password-reset/confirm/page.tsx` | Set new password via reset token |

---

## Deliverables

### 1. `app/(auth)/layout.tsx`
```tsx
import type { ReactNode } from "react";

export default function AuthLayout({ children }: { children: ReactNode }) {
  return (
    <div className="min-h-screen flex items-center justify-center bg-background px-4">
      <div className="w-full max-w-sm">
        <div className="mb-8 text-center">
          <h1 className="text-2xl font-semibold tracking-tight text-foreground">
            Internal Knowledge AI
          </h1>
        </div>
        {children}
      </div>
    </div>
  );
}
```

---

### 2. `app/(auth)/login/page.tsx`
```tsx
"use client";

import { useEffect } from "react";
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
import { useLogin } from "@/features/auth/hooks/useAuthMutations";
import { useAuth } from "@/features/auth/context/AuthContext";

const loginSchema = z.object({
  email: z.string().email("Enter a valid email address"),
  password: z.string().min(1, "Password is required"),
});
type LoginFormValues = z.infer<typeof loginSchema>;

export default function LoginPage() {
  const router = useRouter();
  const { user } = useAuth();
  const login = useLogin();

  // Redirect already-authenticated users
  useEffect(() => {
    if (user) router.replace("/chat");
  }, [user, router]);

  const {
    register,
    handleSubmit,
    formState: { errors, isSubmitting },
  } = useForm<LoginFormValues>({ resolver: zodResolver(loginSchema) });

  const onSubmit = async (values: LoginFormValues) => {
    try {
      const result = await login.mutateAsync(values);
      if (result.must_change_password) {
        router.push("/auth/change-password");
      } else {
        router.push("/chat");
      }
    } catch (err: unknown) {
      const message =
        err instanceof Error ? err.message : "Login failed. Please try again.";
      toast.error(message);
    }
  };

  return (
    <Card>
      <CardHeader>
        <CardTitle>Sign in</CardTitle>
        <CardDescription>
          Enter your credentials to access your workspace
        </CardDescription>
      </CardHeader>
      <CardContent>
        <form onSubmit={handleSubmit(onSubmit)} noValidate className="space-y-4">
          <div className="space-y-1">
            <Label htmlFor="email">Email</Label>
            <Input
              id="email"
              type="email"
              autoComplete="email"
              placeholder="you@example.com"
              aria-invalid={!!errors.email}
              aria-describedby={errors.email ? "email-error" : undefined}
              {...register("email")}
            />
            {errors.email && (
              <p id="email-error" className="text-sm text-destructive">
                {errors.email.message}
              </p>
            )}
          </div>

          <div className="space-y-1">
            <div className="flex items-center justify-between">
              <Label htmlFor="password">Password</Label>
              <a
                href="/auth/password-reset"
                className="text-xs text-muted-foreground hover:text-foreground underline-offset-4 hover:underline"
              >
                Forgot password?
              </a>
            </div>
            <Input
              id="password"
              type="password"
              autoComplete="current-password"
              aria-invalid={!!errors.password}
              aria-describedby={errors.password ? "password-error" : undefined}
              {...register("password")}
            />
            {errors.password && (
              <p id="password-error" className="text-sm text-destructive">
                {errors.password.message}
              </p>
            )}
          </div>

          <Button type="submit" className="w-full" disabled={isSubmitting}>
            {isSubmitting ? "Signing in…" : "Sign in"}
          </Button>
        </form>
      </CardContent>
    </Card>
  );
}
```

---

### 3. `app/(auth)/setup/page.tsx`
```tsx
"use client";

import { useSearchParams, useRouter } from "next/navigation";
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
import { useSetupAccount } from "@/features/auth/hooks/useAuthMutations";

const setupSchema = z
  .object({
    password: z
      .string()
      .min(8, "Password must be at least 8 characters")
      .regex(/[A-Z]/, "Must contain at least one uppercase letter")
      .regex(/[a-z]/, "Must contain at least one lowercase letter")
      .regex(/[0-9]/, "Must contain at least one number"),
    confirm_password: z.string().min(1, "Please confirm your password"),
  })
  .refine((d) => d.password === d.confirm_password, {
    path: ["confirm_password"],
    message: "Passwords do not match",
  });
type SetupFormValues = z.infer<typeof setupSchema>;

export default function SetupPage() {
  const params = useSearchParams();
  const router = useRouter();
  const inviteToken = params.get("token") ?? "";
  const setupAccount = useSetupAccount();

  const {
    register,
    handleSubmit,
    formState: { errors, isSubmitting },
  } = useForm<SetupFormValues>({ resolver: zodResolver(setupSchema) });

  if (!inviteToken) {
    return (
      <Card>
        <CardHeader>
          <CardTitle>Invalid link</CardTitle>
          <CardDescription>
            The invitation link is missing or malformed. Please request a new
            invitation from an administrator.
          </CardDescription>
        </CardHeader>
      </Card>
    );
  }

  const onSubmit = async (values: SetupFormValues) => {
    try {
      await setupAccount.mutateAsync({
        invitation_token: inviteToken,
        password: values.password,
      });
      toast.success("Account created! Please sign in.");
      router.push("/auth/login");
    } catch (err: unknown) {
      const message =
        err instanceof Error ? err.message : "Setup failed. The link may have expired.";
      toast.error(message);
    }
  };

  return (
    <Card>
      <CardHeader>
        <CardTitle>Set your password</CardTitle>
        <CardDescription>
          Create a password for your new account
        </CardDescription>
      </CardHeader>
      <CardContent>
        <form onSubmit={handleSubmit(onSubmit)} noValidate className="space-y-4">
          <div className="space-y-1">
            <Label htmlFor="password">New password</Label>
            <Input
              id="password"
              type="password"
              autoComplete="new-password"
              aria-invalid={!!errors.password}
              {...register("password")}
            />
            {errors.password && (
              <p className="text-sm text-destructive">{errors.password.message}</p>
            )}
          </div>

          <div className="space-y-1">
            <Label htmlFor="confirm_password">Confirm password</Label>
            <Input
              id="confirm_password"
              type="password"
              autoComplete="new-password"
              aria-invalid={!!errors.confirm_password}
              {...register("confirm_password")}
            />
            {errors.confirm_password && (
              <p className="text-sm text-destructive">
                {errors.confirm_password.message}
              </p>
            )}
          </div>

          <Button type="submit" className="w-full" disabled={isSubmitting}>
            {isSubmitting ? "Creating account…" : "Create account"}
          </Button>
        </form>
      </CardContent>
    </Card>
  );
}
```

---

### 4. `app/(auth)/password-reset/page.tsx`
```tsx
"use client";

import { useState } from "react";
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
import { useRequestPasswordReset } from "@/features/auth/hooks/useAuthMutations";

const requestSchema = z.object({
  email: z.string().email("Enter a valid email address"),
});
type RequestFormValues = z.infer<typeof requestSchema>;

export default function PasswordResetPage() {
  const [submitted, setSubmitted] = useState(false);
  const requestReset = useRequestPasswordReset();

  const {
    register,
    handleSubmit,
    formState: { errors, isSubmitting },
  } = useForm<RequestFormValues>({ resolver: zodResolver(requestSchema) });

  const onSubmit = async (values: RequestFormValues) => {
    try {
      await requestReset.mutateAsync(values);
    } catch {
      // Always show success to prevent email enumeration (server returns 202)
    } finally {
      setSubmitted(true);
    }
  };

  if (submitted) {
    return (
      <Card>
        <CardHeader>
          <CardTitle>Check your inbox</CardTitle>
          <CardDescription>
            If an account exists for that email address, you will receive a
            password reset link within a few minutes.
          </CardDescription>
        </CardHeader>
        <CardContent>
          <a
            href="/auth/login"
            className="text-sm text-muted-foreground hover:text-foreground underline-offset-4 hover:underline"
          >
            ← Back to sign in
          </a>
        </CardContent>
      </Card>
    );
  }

  return (
    <Card>
      <CardHeader>
        <CardTitle>Reset your password</CardTitle>
        <CardDescription>
          Enter your email address and we'll send you a reset link
        </CardDescription>
      </CardHeader>
      <CardContent>
        <form onSubmit={handleSubmit(onSubmit)} noValidate className="space-y-4">
          <div className="space-y-1">
            <Label htmlFor="email">Email</Label>
            <Input
              id="email"
              type="email"
              autoComplete="email"
              placeholder="you@example.com"
              aria-invalid={!!errors.email}
              {...register("email")}
            />
            {errors.email && (
              <p className="text-sm text-destructive">{errors.email.message}</p>
            )}
          </div>

          <Button type="submit" className="w-full" disabled={isSubmitting}>
            {isSubmitting ? "Sending…" : "Send reset link"}
          </Button>
        </form>
      </CardContent>
    </Card>
  );
}
```

---

### 5. `app/(auth)/password-reset/confirm/page.tsx`
```tsx
"use client";

import { useSearchParams, useRouter } from "next/navigation";
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
import { useConfirmPasswordReset } from "@/features/auth/hooks/useAuthMutations";

const confirmSchema = z
  .object({
    password: z
      .string()
      .min(8, "Password must be at least 8 characters")
      .regex(/[A-Z]/, "Must contain at least one uppercase letter")
      .regex(/[a-z]/, "Must contain at least one lowercase letter")
      .regex(/[0-9]/, "Must contain at least one number"),
    confirm_password: z.string().min(1, "Please confirm your password"),
  })
  .refine((d) => d.password === d.confirm_password, {
    path: ["confirm_password"],
    message: "Passwords do not match",
  });
type ConfirmFormValues = z.infer<typeof confirmSchema>;

export default function PasswordResetConfirmPage() {
  const params = useSearchParams();
  const router = useRouter();
  const resetToken = params.get("token") ?? "";
  const confirmReset = useConfirmPasswordReset();

  const {
    register,
    handleSubmit,
    formState: { errors, isSubmitting },
  } = useForm<ConfirmFormValues>({ resolver: zodResolver(confirmSchema) });

  if (!resetToken) {
    return (
      <Card>
        <CardHeader>
          <CardTitle>Invalid link</CardTitle>
          <CardDescription>
            This reset link is missing or malformed. Please request a new one.
          </CardDescription>
        </CardHeader>
        <CardContent>
          <a href="/auth/password-reset" className="text-sm underline">
            Request a new link →
          </a>
        </CardContent>
      </Card>
    );
  }

  const onSubmit = async (values: ConfirmFormValues) => {
    try {
      await confirmReset.mutateAsync({
        token: resetToken,
        new_password: values.password,
      });
      toast.success("Password reset successful. Please sign in.");
      router.push("/auth/login");
    } catch (err: unknown) {
      const message =
        err instanceof Error
          ? err.message
          : "Reset failed. The link may have expired.";
      toast.error(message);
    }
  };

  return (
    <Card>
      <CardHeader>
        <CardTitle>Set new password</CardTitle>
        <CardDescription>
          Choose a strong password for your account
        </CardDescription>
      </CardHeader>
      <CardContent>
        <form onSubmit={handleSubmit(onSubmit)} noValidate className="space-y-4">
          <div className="space-y-1">
            <Label htmlFor="password">New password</Label>
            <Input
              id="password"
              type="password"
              autoComplete="new-password"
              aria-invalid={!!errors.password}
              {...register("password")}
            />
            {errors.password && (
              <p className="text-sm text-destructive">{errors.password.message}</p>
            )}
          </div>

          <div className="space-y-1">
            <Label htmlFor="confirm_password">Confirm password</Label>
            <Input
              id="confirm_password"
              type="password"
              autoComplete="new-password"
              aria-invalid={!!errors.confirm_password}
              {...register("confirm_password")}
            />
            {errors.confirm_password && (
              <p className="text-sm text-destructive">
                {errors.confirm_password.message}
              </p>
            )}
          </div>

          <Button type="submit" className="w-full" disabled={isSubmitting}>
            {isSubmitting ? "Resetting…" : "Reset password"}
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
| `src/frontend/app/(auth)/layout.tsx` | Centered card layout for all auth pages |
| `src/frontend/app/(auth)/login/page.tsx` | Login page with email + password form |
| `src/frontend/app/(auth)/setup/page.tsx` | Invitation acceptance + password setup |
| `src/frontend/app/(auth)/password-reset/page.tsx` | Request reset link |
| `src/frontend/app/(auth)/password-reset/confirm/page.tsx` | Confirm reset with new password |

---

## Gate Criteria
- `make lint` passes (no TypeScript errors, no eslint warnings)
- Navigating to `/auth/login` renders the login card without console errors
- Submitting the login form with invalid email shows inline Zod error
- Submitting the login form with valid credentials calls `POST /api/v1/auth/login`
- Visiting `/auth/setup?token=abc` renders the setup form; missing `?token` shows the invalid-link card
- Visiting `/auth/password-reset` renders the request form; after submit shows the "Check your inbox" success state
