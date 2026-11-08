import { NextResponse, type NextRequest } from "next/server";

/**
 * Optimistic gate: pages without a session cookie go to sign-in. Real checks happen on the server
 * (session decryption) and in the gateway (tenant membership, policy) for every API call.
 */
export function proxy(request: NextRequest): Response {
  if (!request.cookies.has("nx_session")) {
    const login = new URL("/auth/login", request.url);
    login.searchParams.set("returnTo", `${request.nextUrl.pathname}${request.nextUrl.search}`);
    return NextResponse.redirect(login);
  }
  return NextResponse.next();
}

export const config = {
  // Everything except auth flow, APIs (they answer 401 themselves), static assets and public pages.
  matcher: ["/((?!auth/|api/|signed-out|_next/|favicon\\.ico|.*\\.(?:svg|png|ico|webp|txt)$).*)"],
};
