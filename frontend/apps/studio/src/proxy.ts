import { NextResponse, type NextRequest } from "next/server";

import { contentSecurityPolicy } from "@/lib/csp";

const PUBLIC = /^\/(auth\/|signed-out)/;

/**
 * Optimistic gate: pages without a session cookie go to sign-in. Real checks happen on the server
 * (session decryption) and in the gateway (tenant membership, policy) for every API call.
 * Every page also gets the Content-Security-Policy here (it depends on runtime configuration).
 */
export function proxy(request: NextRequest): Response {
  const csp = contentSecurityPolicy({
    dev: process.env.NODE_ENV !== "production",
    dataOrigin: process.env.NEXIQON_DATA_ORIGIN || null,
  });
  let response: NextResponse;
  if (!PUBLIC.test(request.nextUrl.pathname) && !request.cookies.has("nx_session")) {
    const login = new URL("/auth/login", request.url);
    login.searchParams.set("returnTo", `${request.nextUrl.pathname}${request.nextUrl.search}`);
    response = NextResponse.redirect(login);
  } else {
    response = NextResponse.next();
  }
  response.headers.set("Content-Security-Policy", csp);
  return response;
}

export const config = {
  // Everything except APIs (they answer 401 themselves), static assets and the public widget
  // bundle that customers' websites load.
  matcher: ["/((?!api/|widget/|_next/|favicon\\.ico|.*\\.(?:svg|png|ico|webp|txt)$).*)"],
};
