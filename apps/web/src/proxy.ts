import { type NextRequest, NextResponse } from "next/server";

import { SESSION_COOKIE } from "@/lib/session";

/**
 * Optimistic check: without a session cookie, go to /login before rendering anything. Whether
 * the session is valid is decided by the API on every call (lib/api.ts), not here.
 */
export function proxy(request: NextRequest) {
  if (!request.cookies.has(SESSION_COOKIE)) {
    return NextResponse.redirect(new URL("/login", request.url));
  }
  return NextResponse.next();
}

export const config = {
  matcher: "/invoices/:path*",
};
