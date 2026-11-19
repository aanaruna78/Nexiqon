/**
 * Backend-for-frontend passthrough: browser -> Studio server -> gateway. The browser never holds
 * the access token; it is attached here from the encrypted session, with the selected tenant.
 */

import { cookies } from "next/headers";

import { currentSession, currentTenant } from "@/lib/server/auth/current";
import { studioEnv } from "@/lib/server/env";
import { forward, isSameOrigin, upstreamUrl } from "@/lib/server/gateway";

/** CORS for the control-plane Studio's pages when this is a data-plane Studio (DV-08). */
function corsHeaders(request: Request, peerOrigin: string | null): Record<string, string> {
  const origin = request.headers.get("origin");
  if (!peerOrigin || origin !== peerOrigin) return {};
  return {
    "access-control-allow-origin": peerOrigin,
    "access-control-allow-credentials": "true",
    "access-control-allow-methods": "GET, POST, PUT, PATCH, DELETE",
    "access-control-allow-headers": "content-type, accept, x-nexiqon-csrf, if-none-match",
    "access-control-max-age": "600",
    vary: "Origin",
  };
}

export async function OPTIONS(request: Request): Promise<Response> {
  const cors = corsHeaders(request, studioEnv().peerOrigin);
  return new Response(null, { status: Object.keys(cors).length ? 204 : 403, headers: cors });
}

async function handle(request: Request, ctx: RouteContext<"/api/nx/[...path]">): Promise<Response> {
  const env = studioEnv();
  const cors = corsHeaders(request, env.peerOrigin);
  const response = await proxied(request, ctx, env, Object.keys(cors).length > 0);
  for (const [k, v] of Object.entries(cors)) response.headers.set(k, v);
  return response;
}

async function proxied(
  request: Request,
  ctx: RouteContext<"/api/nx/[...path]">,
  env: ReturnType<typeof studioEnv>,
  fromPeer: boolean,
): Promise<Response> {
  // Writes must come from this Studio's pages, or from its peer's (split origin), with the CSRF header.
  if (!isSameOrigin(request, fromPeer && env.peerOrigin ? env.peerOrigin : env.baseUrl)) {
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
