import { NextResponse, type NextRequest } from "next/server";

import { startLogin } from "@/lib/server/auth/oidc";
import { isLocale, LOCALE_COOKIE } from "@/i18n/config";
import { studioEnv } from "@/lib/server/env";
import { cookieOptions, FLOW_COOKIE, safeReturnTo, seal } from "@/lib/server/session";

export async function GET(request: NextRequest): Promise<Response> {
  const env = studioEnv();
  if (env.authProvider === "clerk") {
    return NextResponse.json(
      { title: "Clerk sign-in is not enabled in this build", detail: "Set STUDIO_AUTH_PROVIDER=oidc" },
      { status: 501 },
    );
  }
  const returnTo = safeReturnTo(request.nextUrl.searchParams.get("returnTo"), env.peerOrigin);
  const cookieLocale = request.cookies.get(LOCALE_COOKIE)?.value;
  const locale = isLocale(cookieLocale) && cookieLocale !== "en-XA" ? cookieLocale : undefined;
  const { url, flow } = await startLogin(env, returnTo, locale);
  const response = NextResponse.redirect(url);
  response.cookies.set(FLOW_COOKIE, await seal(flow, env.sessionSecret, 600), cookieOptions(env.secureCookies, 600, env.peerOrigin !== null));
  return response;
}
