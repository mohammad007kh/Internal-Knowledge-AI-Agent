import { type NextRequest, NextResponse } from "next/server";

// ── Route groups ──────────────────────────────────────────────────────────────
const AUTH_ROUTES = /^\/auth(\/|$)/;
const DASHBOARD_ROUTES = /^\/(chat|admin|sources|profile)(\/|$)/;
const ADMIN_ROUTES = /^\/admin(\/|$)/;
const CHANGE_PASSWORD_ROUTE = "/auth/change-password";

// ── JWT decode (Edge-safe, no crypto library) ────────────────────────────────
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

// ── Middleware ────────────────────────────────────────────────────────────────
export function middleware(request: NextRequest) {
  const { pathname } = request.nextUrl;

  // Read the access token from a non-httpOnly cookie set by the frontend
  // after a successful login (the httpOnly refresh cookie is opaque to JS).
  // The access token cookie is named "__access" and is readable by middleware.
  const accessTokenCookie = request.cookies.get("__access")?.value;
  const refreshCookie = request.cookies.get("refresh_token")?.value;

  // ── Determine auth state ─────────────────────────────────────────────────
  let payload: EdgeJwtPayload | null = null;
  let isAuthenticated = false;

  if (accessTokenCookie) {
    payload = decodeJwtEdge(accessTokenCookie);
    if (payload && !isTokenExpired(payload)) {
      isAuthenticated = true;
    }
  }

  // If access token is expired/absent but refresh cookie exists,
  // let the request through to dashboard — AuthProvider will trigger a refresh.
  const hasRefreshCookie = !!refreshCookie;

  // ── Auth pages: redirect authenticated users away ─────────────────────────
  if (AUTH_ROUTES.test(pathname) && pathname !== CHANGE_PASSWORD_ROUTE) {
    if (isAuthenticated) {
      return NextResponse.redirect(new URL("/chat", request.url));
    }
    return NextResponse.next();
  }

  // ── Dashboard pages: protect ──────────────────────────────────────────────
  if (DASHBOARD_ROUTES.test(pathname)) {
    // No credentials at all → redirect to login
    if (!isAuthenticated && !hasRefreshCookie) {
      const loginUrl = new URL("/auth/login", request.url);
      loginUrl.searchParams.set("next", pathname);
      return NextResponse.redirect(loginUrl);
    }

    // Authenticated but must change password → redirect to change-password
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

// ── Matcher: skip static assets, API routes, Next.js internals ───────────────
export const config = {
  matcher: [
    "/((?!_next/static|_next/image|favicon.ico|api/).*)",
  ],
};
