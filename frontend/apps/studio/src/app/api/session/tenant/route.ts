import { NextResponse } from "next/server";

import { studioEnv } from "@/lib/server/env";
import { isSameOrigin } from "@/lib/server/gateway";
import { cookieOptions, TENANT_COOKIE } from "@/lib/server/session";

/** Select the active tenant. Membership is enforced by the gateway on every request, not here. */
export async function POST(request: Request): Promise<Response> {
  const env = studioEnv();
  if (!isSameOrigin(request, env.baseUrl)) return new Response(null, { status: 403 });
  const { tenant } = (await request.json()) as { tenant?: string };
  if (!tenant || !/^[a-z0-9-]{1,63}$|^[0-9a-f-]{36}$/.test(tenant)) {
    return Response.json({ title: "Invalid tenant" }, { status: 400 });
  }
  const response = NextResponse.json({ tenant });
  response.cookies.set(TENANT_COOKIE, tenant, cookieOptions(env.secureCookies, 30 * 24 * 3600));
  return response;
}
