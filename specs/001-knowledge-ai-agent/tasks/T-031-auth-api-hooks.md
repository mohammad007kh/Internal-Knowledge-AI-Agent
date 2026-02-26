# T-031 — Frontend Auth TanStack Query Hooks

## Metadata
| Field | Value |
|---|---|
| **ID** | T-031 |
| **Title** | Frontend Auth API Hooks — TanStack Query mutations for all auth flows |
| **Phase** | 1 — Authentication & User Management |
| **Domain** | Frontend / Data Layer |
| **Depends on** | T-005, T-025, T-026, T-032 |
| **Blocks** | T-030, T-033, T-038 |
| **Est. complexity** | S |

### Project Standards
| Standard | Value |
|---|---|
| Python | 3.12 |
| Backend | FastAPI · SQLAlchemy 2.x · Pydantic v2 · dependency-injector |
| Frontend | Next.js 15 App Router · shadcn/ui · Tailwind CSS v4 |
| State | React Context · TanStack Query v5 · react-hook-form · Zod |
| Database | PostgreSQL 16 + pgvector · UUID PKs · soft-delete + audit columns |
| Auth | JWT 15-min access + 7-day rotating httpOnly refresh cookie · bcrypt · RBAC (admin/user) |
| Error Format | RFC 7807 Problem Details — all non-2xx API responses |
| UI | Dark mode · responsive · WCAG-AA · no animations · Lucide icons · Sonner toasts |
| Testing | pytest + httpx + Playwright · ≥80% coverage |
| Infrastructure | Docker Compose 9 services |

### Domain Rules
- Connection strings and file paths MUST NEVER appear in user-facing output (FR-020)
- Invitations are the only path to new accounts — no self-registration (FR-021)
- All passwords validated via validate_password_policy() (FR-034)

---

## Goal
Create all TanStack Query v5 mutations used by the auth pages (T-030) and the auth context
(T-032). Each mutation wraps a typed API call from the central `api-client.ts` and translates
RFC 7807 `ProblemDetail` error responses into plain `Error` objects so the pages receive
human-readable messages.

---

## Deliverables

### 1. `src/frontend/lib/api/auth.ts` — typed API functions
```typescript
import { apiClient } from "@/lib/api-client";

// ── Request / Response types ────────────────────────────────────────────────

export interface LoginRequest {
  email: string;
  password: string;
}

export interface TokenResponse {
  access_token: string;
  token_type: "Bearer";
  expires_in: number;
  must_change_password: boolean;
}

export interface SetupAccountRequest {
  invitation_token: string;
  password: string;
}

export interface ChangePasswordRequest {
  current_password?: string;       // optional: omit when forced by must_change_password
  new_password: string;
}

export interface PasswordResetRequest {
  email: string;
}

export interface PasswordResetConfirmRequest {
  token: string;
  new_password: string;
}

// ── API functions ────────────────────────────────────────────────────────────

export async function loginApi(body: LoginRequest): Promise<TokenResponse> {
  return apiClient<TokenResponse>("/auth/login", {
    method: "POST",
    body: JSON.stringify(body),
  });
}

export async function refreshTokenApi(): Promise<TokenResponse> {
  return apiClient<TokenResponse>("/auth/refresh", { method: "POST" });
}

export async function logoutApi(): Promise<void> {
  await apiClient<void>("/auth/logout", { method: "POST" });
}

export async function setupAccountApi(body: SetupAccountRequest): Promise<void> {
  await apiClient<void>("/auth/setup", {
    method: "POST",
    body: JSON.stringify(body),
  });
}

export async function requestPasswordResetApi(
  body: PasswordResetRequest
): Promise<void> {
  await apiClient<void>("/auth/password-reset", {
    method: "POST",
    body: JSON.stringify(body),
  });
}

export async function confirmPasswordResetApi(
  body: PasswordResetConfirmRequest
): Promise<void> {
  await apiClient<void>("/auth/password-reset/confirm", {
    method: "POST",
    body: JSON.stringify(body),
  });
}

export async function changePasswordApi(body: ChangePasswordRequest): Promise<void> {
  await apiClient<void>("/auth/change-password", {
    method: "POST",
    body: JSON.stringify(body),
  });
}
```

---

### 2. `src/frontend/features/auth/hooks/useAuthMutations.ts`
```typescript
"use client";

import { useMutation, useQueryClient } from "@tanstack/react-query";
import {
  loginApi,
  logoutApi,
  setupAccountApi,
  requestPasswordResetApi,
  confirmPasswordResetApi,
  changePasswordApi,
  type LoginRequest,
  type TokenResponse,
  type SetupAccountRequest,
  type ChangePasswordRequest,
  type PasswordResetRequest,
  type PasswordResetConfirmRequest,
} from "@/lib/api/auth";
import { useAuth } from "@/features/auth/context/AuthContext";

/**
 * Login mutation.
 * On success, the AuthContext is updated via the returned TokenResponse.
 */
export function useLogin() {
  const { setAccessToken } = useAuth();
  return useMutation<TokenResponse, Error, LoginRequest>({
    mutationFn: loginApi,
    onSuccess: (data) => {
      setAccessToken(data.access_token);
    },
  });
}

/**
 * Logout mutation.
 * Clears the in-memory access token and invalidates all queries so any
 * cached user data is dropped.
 */
export function useLogout() {
  const { clearAccessToken } = useAuth();
  const qc = useQueryClient();
  return useMutation<void, Error, void>({
    mutationFn: logoutApi,
    onSettled: () => {
      clearAccessToken();
      qc.clear();
    },
  });
}

/**
 * Accept invitation + set initial password.
 */
export function useSetupAccount() {
  return useMutation<void, Error, SetupAccountRequest>({
    mutationFn: setupAccountApi,
  });
}

/**
 * Request a password-reset email. Always succeeds from the client's
 * perspective (server returns 202 regardless of whether the email exists
 * to prevent enumeration).
 */
export function useRequestPasswordReset() {
  return useMutation<void, Error, PasswordResetRequest>({
    mutationFn: requestPasswordResetApi,
  });
}

/**
 * Submit the reset token + new password.
 */
export function useConfirmPasswordReset() {
  return useMutation<void, Error, PasswordResetConfirmRequest>({
    mutationFn: confirmPasswordResetApi,
  });
}

/**
 * Change password (authenticated).
 * Used both for voluntary change and for forced change when
 * `must_change_password === true`.
 */
export function useChangePassword() {
  return useMutation<void, Error, ChangePasswordRequest>({
    mutationFn: changePasswordApi,
  });
}
```

---

### 3. `src/frontend/lib/api-client.ts` — additions / refinement (extends T-005 stub)
The existing stub from T-005 handles 401 → refresh. Extend it to translate RFC 7807
`ProblemDetail` responses into plain `Error` objects with a meaningful `message`:

```typescript
// src/frontend/lib/api-client.ts  (additions to T-005 stub)

interface ProblemDetail {
  type?: string;
  title?: string;
  status: number;
  detail?: string;
}

/**
 * Internal helper — parses RFC 7807 ProblemDetail bodies into plain Error.
 * Called by apiClient after a non-2xx response.
 */
async function parseErrorResponse(res: Response): Promise<Error> {
  const contentType = res.headers.get("content-type") ?? "";
  if (contentType.includes("application/problem+json")) {
    try {
      const problem = (await res.json()) as ProblemDetail;
      return new Error(problem.detail ?? problem.title ?? "An error occurred");
    } catch {
      // fall through to generic message
    }
  }
  return new Error(`Request failed with status ${res.status}`);
}

// Ensure the apiClient re-throws:
// In the existing apiClient, replace:
//   throw new Error(`HTTP ${res.status}`)
// With:
//   throw await parseErrorResponse(res)
```

---

## Files to Create / Modify

| Path | Action | Description |
|---|---|---|
| `src/frontend/lib/api/auth.ts` | **Create** | Typed API wrapper functions for all auth endpoints |
| `src/frontend/features/auth/hooks/useAuthMutations.ts` | **Create** | TanStack Query mutation hooks |
| `src/frontend/lib/api-client.ts` | **Modify** | Add `parseErrorResponse` helper for RFC 7807 support |

---

## Gate Criteria
- `make lint` passes
- `useLogin()` mutation calls `POST /api/v1/auth/login` with correct JSON body
- On a 401 ProblemDetail response, the mutation rejects with `err.message` equal to the `detail` field
- `useLogout()` clears the access token and calls `queryClient.clear()`
- TypeScript compiles cleanly — no `any` types in exported interfaces
