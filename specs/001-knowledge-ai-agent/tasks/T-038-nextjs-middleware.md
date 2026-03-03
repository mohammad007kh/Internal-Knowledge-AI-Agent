# T-038 â€” Next.js Middleware for Auth Route Protection

## Metadata
| Field | Value |
|---|---|
| **Status** | Done |
| **ID** | T-038 |
| **Title** | Next.js Middleware â€” auth-route protection, role guard, must_change_password redirect |
| **Phase** | 1 â€” Authentication & User Management |
| **Domain** | Frontend / Middleware |
| **Depends on** | T-005, T-032 |
| **Blocks** | T-033, T-039 |
| **Est. complexity** | S |

### Project Standards
| Standard | Value |
|---|---|
| Python | 3.12 |
| Backend | FastAPI Â· SQLAlchemy 2.x Â· Pydantic v2 Â· dependency-injector |
| Frontend | Next.js 15 App Router Â· shadcn/ui Â· Tailwind CSS v4 |
| Auth | JWT 15-min access + 7-day rotating httpOnly refresh cookie Â· bcrypt Â· RBAC (admin/user) |
| UI | Dark mode Â· responsive Â· WCAG-AA Â· no animations Â· Lucide icons Â· Sonner toasts |
| Infrastructure | Docker Compose 9 services |

### Domain Rules
- Source access is per-user per-source; never expose unapproved source data (FR-019)
- Invitations are the only path to new accounts (FR-021)

---

## Goal
Implement `src/middleware.ts` (Next.js Edge middleware) that:
1. **Protects `(dashboard)` routes** â€” redirects to `/auth/login` if the httpOnly refresh
   cookie is absent
2. **Blocks admin routes** â€” redirects non-admins away from `/admin/*`; uses the JWT
   `role` claim (decoded in middleware without crypto verify â€” verification happens server-side)
3. **Intercepts `must_change_password`** â€” if the JWT `must_change_password` claim is `true`,
   redirects every `(dashboard)` request to `/auth/change-password`
4. **Redirects authenticated users** away from `(auth)` pages (except `/auth/change-password`)

---

## Deliverables

### `src/frontend/middleware.ts`
```typescript
import { type NextRequest, NextResponse } from "next/server";

// â”€â”€ Route groups â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€
const AUTH_ROUTES = /^\/auth(\/|$)/;
const DASHBOARD_ROUTES = /^\/(chat|admin|sources|profile)(\/|$)/;
const ADMIN_ROUTES = /^\/admin(\/|$)/;
const CHANGE_PASSWORD_ROUTE = "/auth/change-password";

// â”€â”€ JWT decode (Edge-safe, no crypto library) â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€
interface EdgeJwtPayload {
  sub?: string;
  email?: string;
  role?: "admin" | "user";
  must_change_password?: boolean;
  exp?: number;
}

function decodeJwtEdge(token: string): EdgeJwtPayload | null {
  try {
    const [, payload] = token.split(".");
    if (!payload) return null;
    const padded = payload.replace(/-/g, "+").replace(/_/g, "/");
    const json = atob(padded);
    return JSON.parse(json) as EdgeJwtPayload;
  } catch {
    return null;
  }
}

function isTokenExpired(payload: EdgeJwtPayload): boolean {
  if (!payload.exp) return true;
  return payload.exp * 1000 < Date.now();
}

// â”€â”€ Middleware â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€
export function middleware(request: NextRequest) {
  const { pathname } = request.nextUrl;

  // Read the access token from a non-httpOnly cookie set by the frontend
  // after a successful login (the httpOnly refresh cookie is opaque to JS).
  // The access token cookie is named "__access" and is readable by middleware.
  const accessTokenCookie = request.cookies.get("__access")?.value;
  const refreshCookie = request.cookies.get("refresh_token")?.value;

  // â”€â”€ Determine auth state â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€
  let payload: EdgeJwtPayload | null = null;
  let isAuthenticated = false;

  if (accessTokenCookie) {
    payload = decodeJwtEdge(accessTokenCookie);
    if (payload && !isTokenExpired(payload)) {
      isAuthenticated = true;
    }
  }

  // If access token is expired/absent but refresh cookie exists,
  // let the request through to dashboard â€” AuthProvider will trigger a refresh.
  const hasRefreshCookie = !!refreshCookie;

  // â”€â”€ Auth pages: redirect authenticated users away â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€
  if (AUTH_ROUTES.test(pathname) && pathname !== CHANGE_PASSWORD_ROUTE) {
    if (isAuthenticated) {
      return NextResponse.redirect(new URL("/chat", request.url));
    }
    return NextResponse.next();
  }

  // â”€â”€ Dashboard pages: protect â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€
  if (DASHBOARD_ROUTES.test(pathname)) {
    // No credentials at all â†’ redirect to login
    if (!isAuthenticated && !hasRefreshCookie) {
      const loginUrl = new URL("/auth/login", request.url);
      loginUrl.searchParams.set("next", pathname);
      return NextResponse.redirect(loginUrl);
    }

    // Authenticated but must change password â†’ redirect to change-password
    if (isAuthenticated && payload?.must_change_password) {
      if (pathname !== CHANGE_PASSWORD_ROUTE) {
        return NextResponse.redirect(new URL(CHANGE_PASSWORD_ROUTE, request.url));
      }
    }

    // Admin-only routes: reject non-admins
    if (ADMIN_ROUTES.test(pathname)) {
      if (isAuthenticated && payload?.role !== "admin") {
        return NextResponse.redirect(new URL("/chat", request.url));
      }
    }
  }

  return NextResponse.next();
}

// â”€â”€ Matcher: skip static assets, API routes, Next.js internals â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€
export const config = {
  matcher: [
    "/((?!_next/static|_next/image|favicon.ico|api/).*)",
  ],
};
```

---

### Cookie management update in `AuthContext`
When the access token is set, also write the readable `__access` cookie so that the
middleware can inspect it. **The `__access` cookie must NOT be httpOnly** â€” it's for
middleware route-guard use only (not a security credential).

```typescript
// Add to AuthProvider, inside setAccessToken callback:
import Cookies from "js-cookie";

const setAccessToken = useCallback(
  (token: string) => {
    setAccessTokenState(token);
    scheduleRefresh(token);
    // Write readable cookie for Next.js Edge middleware
    const payload = decodeJwt(token);
    if (payload) {
      Cookies.set("__access", token, {
        expires: new Date(payload.exp * 1000),
        sameSite: "strict",
        secure: process.env.NODE_ENV === "production",
        // NOT httpOnly â€” must be readable from middleware
      });
    }
  },
  [scheduleRefresh]
);

const clearAccessToken = useCallback(() => {
  setAccessTokenState(null);
  Cookies.remove("__access");
  if (refreshTimerRef.current) clearTimeout(refreshTimerRef.current);
}, []);
```

---

## Files to Create / Modify

| Path | Action | Description |
|---|---|---|
| `src/frontend/middleware.ts` | **Create** | Edge middleware for route protection |
| `src/frontend/features/auth/context/AuthContext.tsx` | **Modify** | Sync `__access` cookie on token changes |

---

## Gate Criteria
- Navigating to `/chat` without a refresh cookie redirects to `/auth/login?next=/chat`
- Navigating to `/admin/users` as a regular user (role=user) redirects to `/chat`
- A user with `must_change_password=true` is redirected to `/auth/change-password` on every dashboard visit
- After login, navigating to `/auth/login` redirects to `/chat`
- Static assets (`/_next/static/**`) are never intercepted by the middleware
- Edge middleware compiles without errors (`next build` passes)
