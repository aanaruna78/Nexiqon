import { NextResponse, type NextRequest } from "next/server";

import { finishLogin, type LoginFlow } from "@/lib/server/auth/oidc";
import { studioEnv } from "@/lib/server/env";
import { cookieOptions, FLOW_COOKIE, ID_TOKEN_COOKIE, safeReturnTo, seal, SESSION_COOKIE, unseal } from "@/lib/server/session";

export async function GET(request: NextRequest): Promise<Response> {
  const env = studioEnv();
  const flow = await unseal<LoginFlow>(request.cookies.get(FLOW_COOKIE)?.value, env.sessionSecret);
  if (!flow) return NextResponse.redirect(`${env.baseUrl}/signed-out?reason=expired`);
  try {
    // The callback must be validated against the URL the IdP redirected to (public base URL).
    const current = new URL(`${env.baseUrl}/auth/callback${request.nextUrl.search}`);
    const { idToken, ...session } = await finishLogin(env, current, flow);
    const response = NextResponse.redirect(`${env.baseUrl}${safeReturnTo(flow.returnTo)}`);
    response.cookies.set(SESSION_COOKIE, await seal(session, env.sessionSecret), cookieOptions(env.secureCookies));
    if (idToken) {
      response.cookies.set(ID_TOKEN_COOKIE, await seal({ idToken }, env.sessionSecret), cookieOptions(env.secureCookies));
    }
    response.cookies.delete(FLOW_COOKIE);
    return response;
  } catch {
    return NextResponse.redirect(`${env.baseUrl}/signed-out?reason=failed`);
  }
}
