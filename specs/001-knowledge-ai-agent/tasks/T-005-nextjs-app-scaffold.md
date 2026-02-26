---
id: T-005
title: Next.js 15 App Scaffold — App Router, shadcn/ui, Tailwind, TanStack Query Provider
status: Not Started
created: 2026-02-25
phase: Phase 0 — Foundation
user_story: cross
requirements: []
---

## 📋 Embedded Context (READ THIS FIRST)

### Project Standards
| Standard | Value |
|---|---|
| Frontend | Next.js 15 App Router · shadcn/ui · Tailwind CSS v4 |
| State | React Context · TanStack Query v5 |
| Forms | react-hook-form + Zod |
| UI | Dark mode · responsive · WCAG-AA · no animations · Lucide icons · Sonner toasts |
| Naming | kebab-case component files · PascalCase component names |
| TypeScript | strict mode · `@/` path alias |
| Routing | next-router (App Router file-system based) |

### Domain Rules
- All user-facing errors use RFC 7807 format when returned from API; frontend shows user-friendly messages
- Route groups: `(auth)` for unauthenticated pages, `(dashboard)` for authenticated
- All pages in `(dashboard)` require valid auth — enforced via middleware
- Dark mode toggle uses `next-themes`

### Feature Summary
Next.js 15 App Router scaffold with proper provider hierarchy, route groups, shadcn/ui initialization, and a global layout that wraps all pages with TanStack Query provider, Sonner toaster, and dark mode support.

### Gate Criteria
- `cd frontend && npx next build` — zero TypeScript or build errors
- `cd frontend && npx tsc --noEmit` — zero type errors
- `localhost:3000` renders root layout without React errors
- Dark mode toggle works

---

## 🎯 Objective

Initialize the Next.js 15 frontend with App Router, configure Tailwind CSS v4, install and initialize shadcn/ui, set up TanStack Query v5 provider, wrap app in Sonner toaster and theme provider, add `next/middleware.ts` for auth-route protection, and define the `(auth)` and `(dashboard)` route groups.

---

## 🛠️ Implementation Details

### Files to Create

| Path | Purpose |
|------|---------|
| `frontend/src/app/layout.tsx` | Root layout with providers: QueryClient, ThemeProvider, Toaster |
| `frontend/src/app/(auth)/layout.tsx` | Unauthenticated layout (center card, no sidebar) |
| `frontend/src/app/(auth)/login/page.tsx` | Login page placeholder |
| `frontend/src/app/(dashboard)/layout.tsx` | Authenticated layout with sidebar shell |
| `frontend/src/app/(dashboard)/page.tsx` | Dashboard home redirect to `/chat` |
| `frontend/src/middleware.ts` | Next.js middleware: redirect to `/login` if no auth cookie |
| `frontend/src/lib/query-client.ts` | TanStack Query client singleton with staleTime/gcTime defaults |
| `frontend/src/lib/api-client.ts` | Axios/fetch wrapper with base URL, auth header injection, 401 refresh interceptor |
| `frontend/src/components/providers.tsx` | Combined providers component for root layout |
| `frontend/src/components/theme-toggle.tsx` | Dark/light mode toggle button |
| `frontend/components.json` | shadcn/ui config |

### Files to Update
- `frontend/src/app/globals.css` — import Tailwind, define CSS variables for shadcn
- `frontend/tailwind.config.ts` — configure dark mode, content paths, shadcn preset

### Code / Logic Requirements

**`frontend/src/app/layout.tsx`:**
```tsx
import type { Metadata } from "next";
import { Providers } from "@/components/providers";
import "./globals.css";

export const metadata: Metadata = {
  title: "Knowledge AI Agent",
  description: "Internal knowledge base powered by AI",
};

export default function RootLayout({ children }: { children: React.ReactNode }) {
  return (
    <html lang="en" suppressHydrationWarning>
      <body>
        <Providers>{children}</Providers>
      </body>
    </html>
  );
}
```

**`frontend/src/components/providers.tsx`:**
```tsx
"use client";
import { QueryClientProvider } from "@tanstack/react-query";
import { ThemeProvider } from "next-themes";
import { Toaster } from "sonner";
import { queryClient } from "@/lib/query-client";

export function Providers({ children }: { children: React.ReactNode }) {
  return (
    <QueryClientProvider client={queryClient}>
      <ThemeProvider attribute="class" defaultTheme="system" enableSystem>
        {children}
        <Toaster richColors closeButton />
      </ThemeProvider>
    </QueryClientProvider>
  );
}
```

**`frontend/src/middleware.ts`:**
```ts
import { NextResponse } from "next/server";
import type { NextRequest } from "next/server";

const PUBLIC_PATHS = ["/login", "/setup", "/reset-password"];

export function middleware(request: NextRequest) {
  const isPublic = PUBLIC_PATHS.some(p => request.nextUrl.pathname.startsWith(p));
  const hasToken = request.cookies.has("access_token");
  if (!isPublic && !hasToken) {
    return NextResponse.redirect(new URL("/login", request.url));
  }
  return NextResponse.next();
}

export const config = {
  matcher: ["/((?!api|_next/static|_next/image|favicon.ico).*)"],
};
```

**`frontend/src/lib/query-client.ts`:**
```ts
import { QueryClient } from "@tanstack/react-query";
export const queryClient = new QueryClient({
  defaultOptions: {
    queries: { staleTime: 60_000, gcTime: 5 * 60_000, retry: 1 },
  },
});
```

**`frontend/src/lib/api-client.ts`:**
- Base URL from `NEXT_PUBLIC_API_URL`
- Inject `Authorization: Bearer <token>` from cookie/localStorage
- On 401: attempt `/api/auth/refresh` then retry once, then redirect to `/login`

**shadcn/ui install commands (run in task):**
```bash
cd frontend && npx shadcn@latest init --defaults
npx shadcn@latest add button input label card badge separator toast
```

---

## 🔌 Wiring Checklist

- [ ] Root layout renders `<Providers>` wrapping `{children}`
- [ ] Middleware protects all non-public routes
- [ ] `(auth)` layout renders centered card — no sidebar
- [ ] `(dashboard)` layout renders sidebar shell placeholder
- [ ] `ThemeProvider` and `Toaster` in Providers
- [ ] `@/` path alias resolves in tsconfig.json

---

## ✅ Verification

```bash
cd frontend

# TypeScript check
npx tsc --noEmit
# Expected: no output (zero errors)

# Build check
npx next build 2>&1 | tail -5
# Expected: "Compiled successfully" or zero error lines

# Start dev and verify root loads
npx next dev &
sleep 5
curl -s http://localhost:3000 | grep -q "Knowledge AI Agent" && echo "Root layout OK"

# Verify middleware redirects unauthenticated user
curl -s -o /dev/null -w "%{http_code}" http://localhost:3000/chat
# Expected: 307 (redirect to /login)
```

**Success Criteria:**
- `npx tsc --noEmit` → zero errors
- `npx next build` → compiles successfully
- `GET /` → renders root layout
- `GET /chat` (no cookie) → 307 redirect to `/login`
- Dark mode toggle cycles light/dark/system

---

## 📝 Completion Log

- [ ] Code implemented
- [ ] Tests passed
- [ ] Linter passed
- [ ] Wiring verified
- [ ] Integration verification passed
