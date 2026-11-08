import { NextResponse } from "next/server";

import { logoutUrl } from "@/lib/server/auth/oidc";
import { studioEnv } from "@/lib/server/env";
import { isSameOrigin } from "@/lib/server/gateway";
import { cookies } from "next/headers";

import { ID_TOKEN_COOKIE, SESSION_COOKIE, TENANT_COOKIE, unseal } from "@/lib/server/session";

export async function POST(request: Request): Promise<Response> {
  const env = studioEnv();
  if (!isSameOrigin(request, env.baseUrl)) return new Response(null, { status: 403 });
  const hint = await unseal<{ idToken: string }>((await cookies()).get(ID_TOKEN_COOKIE)?.value, env.sessionSecret);
  const response = NextResponse.json({ redirect: await logoutUrl(env, hint?.idToken) });
  response.cookies.delete(ID_TOKEN_COOKIE);
  response.cookies.delete(SESSION_COOKIE);
  response.cookies.delete(TENANT_COOKIE);
  return response;
}
