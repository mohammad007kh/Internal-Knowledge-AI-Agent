# T-032 â€” Frontend Auth React Context (`useAuth`)

## Metadata
| Field | Value |
|---|---|
| **Status** | Done |
| **ID** | T-032 |
| **Title** | Frontend Auth Context â€” in-memory token store, `useAuth` hook, JWT decode |
| **Phase** | 1 â€” Authentication & User Management |
| **Domain** | Frontend / State |
| **Depends on** | T-005, T-031 |
| **Blocks** | T-030, T-033, T-038 |
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
- Connection strings MUST NEVER appear in user-facing output (FR-020)
- Invitations are the only path to new accounts (FR-021)

---

## Goal
Implement the `AuthContext` + `AuthProvider` that manages the **in-memory** access token.
The token is decoded client-side (JWT claims, no verification â€” verification is done server-
side on every request) to extract `user_id`, `email`, and `role`. The httpOnly refresh
cookie is managed server-side; the frontend never touches it directly.

On first mount the provider calls `POST /auth/refresh` to restore the session from the
existing httpOnly cookie. If that fails (cookie absent or expired) the user is considered
unauthenticated.

---

## Deliverables

### 1. `src/frontend/features/auth/types.ts`
```typescript
export type UserRole = "admin" | "user";

export interface AuthUser {
  id: string;
  email: string;
  role: UserRole;
  must_change_password: boolean;
}

export interface AuthContextValue {
  /** Decoded JWT payload; null when unauthenticated. */
  user: AuthUser | null;
  /** Raw access token (opaque to most callers). */
  accessToken: string | null;
  /** True while the initial refresh call is in-flight. */
  isLoading: boolean;
  /** Store a new access token (called by login/refresh mutations). */
  setAccessToken: (token: string) => void;
  /** Clear the token (called by logout mutation). */
  clearAccessToken: () => void;
}
```

---

### 2. `src/frontend/features/auth/context/AuthContext.tsx`
```typescript
"use client";

import {
  createContext,
  useCallback,
  useContext,
  useEffect,
  useRef,
  useState,
  type ReactNode,
} from "react";
import { refreshTokenApi } from "@/lib/api/auth";
import type { AuthContextValue, AuthUser } from "../types";

// â”€â”€ JWT decode (no signature verification) â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€
interface JwtPayload {
  sub: string;
  email: string;
  role: "admin" | "user";
  must_change_password?: boolean;
  exp: number;
}

function decodeJwt(token: string): JwtPayload | null {
  try {
    const [, payload] = token.split(".");
    const json = atob(payload.replace(/-/g, "+").replace(/_/g, "/"));
    return JSON.parse(json) as JwtPayload;
  } catch {
    return null;
  }
}

function jwtToUser(token: string): AuthUser | null {
  const payload = decodeJwt(token);
  if (!payload) return null;
  return {
    id: payload.sub,
    email: payload.email,
    role: payload.role,
    must_change_password: payload.must_change_password ?? false,
  };
}

// â”€â”€ Context â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€
const AuthContext = createContext<AuthContextValue | null>(null);

export function AuthProvider({ children }: { children: ReactNode }) {
  const [accessToken, setAccessTokenState] = useState<string | null>(null);
  const [isLoading, setIsLoading] = useState(true);

  // Derived user from in-memory token
  const user: AuthUser | null = accessToken ? jwtToUser(accessToken) : null;

  // â”€â”€ Proactive token refresh â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€
  // Schedule a refresh 60 s before the token expires.
  const refreshTimerRef = useRef<ReturnType<typeof setTimeout> | null>(null);

  const scheduleRefresh = useCallback((token: string) => {
    const payload = decodeJwt(token);
    if (!payload) return;
    const msUntilExpiry = payload.exp * 1000 - Date.now();
    const refreshIn = Math.max(msUntilExpiry - 60_000, 0);

    if (refreshTimerRef.current) clearTimeout(refreshTimerRef.current);

    refreshTimerRef.current = setTimeout(async () => {
      try {
        const data = await refreshTokenApi();
        setAccessTokenState(data.access_token);
        scheduleRefresh(data.access_token);
      } catch {
        // Session expired â€” clear silently; middleware will redirect to /auth/login
        setAccessTokenState(null);
      }
    }, refreshIn);
  }, []);

  // â”€â”€ Initial session restore â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€
  useEffect(() => {
    (async () => {
      try {
        const data = await refreshTokenApi();
        setAccessTokenState(data.access_token);
        scheduleRefresh(data.access_token);
      } catch {
        // No valid session â€” remain unauthenticated
      } finally {
        setIsLoading(false);
      }
    })();

    return () => {
      if (refreshTimerRef.current) clearTimeout(refreshTimerRef.current);
    };
  }, [scheduleRefresh]);

  // â”€â”€ Public API â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€
  const setAccessToken = useCallback(
    (token: string) => {
      setAccessTokenState(token);
      scheduleRefresh(token);
    },
    [scheduleRefresh]
  );

  const clearAccessToken = useCallback(() => {
    setAccessTokenState(null);
    if (refreshTimerRef.current) clearTimeout(refreshTimerRef.current);
  }, []);

  return (
    <AuthContext.Provider
      value={{ user, accessToken, isLoading, setAccessToken, clearAccessToken }}
    >
      {children}
    </AuthContext.Provider>
  );
}

// â”€â”€ Hook â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€
export function useAuth(): AuthContextValue {
  const ctx = useContext(AuthContext);
  if (!ctx) {
    throw new Error("useAuth must be used inside <AuthProvider>");
  }
  return ctx;
}
```

---

### 3. `src/frontend/lib/api-client.ts` â€” inject Bearer from AuthContext
The `apiClient` helper (T-005, extended in T-031) must include the access token on every
authenticated request. Because the token lives in React context (not a module-level
variable), we use a simple module-level **token store** proxy:

```typescript
// src/frontend/lib/token-store.ts
/**
 * Minimal write-once store so that api-client.ts can read the access token
 * without importing React context (which cannot be imported in non-component
 * modules in Next.js App Router).
 *
 * AuthProvider calls setToken() when the token changes.
 * apiClient reads getToken() to attach Authorization headers.
 */
let _token: string | null = null;

export function setToken(t: string | null): void {
  _token = t;
}

export function getToken(): string | null {
  return _token;
}
```

Update `AuthProvider` to sync the token store:
```typescript
// Inside AuthProvider, add after the state declarations:
import { setToken } from "@/lib/token-store";

useEffect(() => {
  setToken(accessToken);
}, [accessToken]);
```

Update `api-client.ts` to inject the header:
```typescript
import { getToken } from "@/lib/token-store";

// Inside apiClient, before fetch:
const headers: HeadersInit = {
  "Content-Type": "application/json",
};
const token = getToken();
if (token) {
  (headers as Record<string, string>)["Authorization"] = `Bearer ${token}`;
}
```

---

## Files to Create / Modify

| Path | Action | Description |
|---|---|---|
| `src/frontend/features/auth/types.ts` | **Create** | `AuthUser`, `AuthContextValue` types |
| `src/frontend/features/auth/context/AuthContext.tsx` | **Create** | `AuthProvider`, `useAuth`, JWT decode, proactive refresh |
| `src/frontend/lib/token-store.ts` | **Create** | Module-level token proxy for api-client |
| `src/frontend/lib/api-client.ts` | **Modify** | Inject `Authorization` header from token store |
| `src/frontend/app/providers.tsx` | **Modify** | Wrap `QueryClientProvider` with `AuthProvider` |

---

## `app/providers.tsx` â€” updated
```tsx
"use client";

import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { Toaster } from "sonner";
import { useState, type ReactNode } from "react";
import { AuthProvider } from "@/features/auth/context/AuthContext";

export function Providers({ children }: { children: ReactNode }) {
  const [queryClient] = useState(() => new QueryClient({
    defaultOptions: {
      queries: { retry: 1, staleTime: 30_000 },
    },
  }));

  return (
    <QueryClientProvider client={queryClient}>
      <AuthProvider>
        {children}
        <Toaster richColors closeButton position="top-right" />
      </AuthProvider>
    </QueryClientProvider>
  );
}
```

---

## Gate Criteria
- `make lint` passes; no TypeScript errors
- On page load, `AuthProvider` calls `POST /api/v1/auth/refresh`; if it returns 200, `useAuth().user` is non-null
- If refresh returns 401, `useAuth().user` is null and `isLoading` transitions `true â†’ false`
- `setAccessToken` updates `user` immediately without a round-trip
- `clearAccessToken` sets `user` to null
- The proactive refresh timer fires 60 s before `exp`
- No access token is ever stored in `localStorage` or `sessionStorage`
