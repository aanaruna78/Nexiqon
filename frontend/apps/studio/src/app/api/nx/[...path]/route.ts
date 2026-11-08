/**
 * Backend-for-frontend passthrough: browser -> Studio server -> gateway. The browser never holds
 * the access token; it is attached here from the encrypted session, with the selected tenant.
 */

import { cookies } from "next/headers";

import { currentSession, currentTenant } from "@/lib/server/auth/current";
import { studioEnv } from "@/lib/server/env";
import { forward, isSameOrigin, upstreamUrl } from "@/lib/server/gateway";

async function handle(request: Request, ctx: RouteContext<"/api/nx/[...path]">): Promise<Response> {
  const env = studioEnv();
  if (!isSameOrigin(request, env.baseUrl)) {
    return Response.json({ title: "Cross-site request refused", status: 403 }, { status: 403 });
  }
  const session = await currentSession({ persist: true });
  if (!session) {
    return Response.json({ title: "Signed out", status: 401, code: "signed_out" }, { status: 401 });
  }
  const { path } = await ctx.params;
  const target = upstreamUrl(env.gatewayUrl, path, new URL(request.url).search);
  if (!target) return Response.json({ title: "Invalid path", status: 400 }, { status: 400 });
  await cookies(); // mark dynamic
  return forward(request, target, session.accessToken, await currentTenant());
}

export const GET = handle;
export const POST = handle;
export const PUT = handle;
export const PATCH = handle;
export const DELETE = handle;
