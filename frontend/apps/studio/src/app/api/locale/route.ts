import { NextResponse } from "next/server";

import { isLocale, LOCALE_COOKIE } from "@/i18n/config";
import { studioEnv } from "@/lib/server/env";
import { isSameOrigin } from "@/lib/server/gateway";

export async function POST(request: Request): Promise<Response> {
  const env = studioEnv();
  if (!isSameOrigin(request, env.baseUrl)) return new Response(null, { status: 403 });
  const { locale } = (await request.json()) as { locale?: string };
  if (!isLocale(locale)) return Response.json({ title: "Unsupported locale" }, { status: 400 });
  const response = NextResponse.json({ locale });
  response.cookies.set(LOCALE_COOKIE, locale, { path: "/", sameSite: "lax", maxAge: 365 * 24 * 3600 });
  return response;
}
