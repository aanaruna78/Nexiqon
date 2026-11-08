/** Forwarding from Studio's server to the Nexiqon gateway (BFF). */

/** Build the upstream URL, refusing anything that would leave the gateway origin. */
export function upstreamUrl(gatewayUrl: string, segments: string[], search: string): URL | null {
  if (segments.length === 0 || segments.some((s) => s === ".." || s === "." || s.includes("\\") || s === "")) {
    return null;
  }
  const base = new URL(gatewayUrl);
  const url = new URL(`${base.pathname.replace(/\/$/, "")}/${segments.map(encodeURIComponent).join("/")}${search}`, base);
  return url.origin === base.origin ? url : null;
}

/** Mutating requests must come from Studio's own pages (CSRF defence on top of SameSite cookies). */
export function isSameOrigin(request: Request, baseUrl: string): boolean {
  if (["GET", "HEAD", "OPTIONS"].includes(request.method)) return true;
  const origin = request.headers.get("origin");
  return request.headers.get("x-nexiqon-csrf") === "1" && origin === new URL(baseUrl).origin;
}

const FORWARD_REQUEST_HEADERS = ["content-type", "accept", "if-none-match", "accept-language"];
const FORWARD_RESPONSE_HEADERS = ["content-type", "etag", "cache-control"];

export async function forward(
  request: Request,
  target: URL,
  accessToken: string,
  tenant: string | undefined,
): Promise<Response> {
  const headers = new Headers();
  for (const name of FORWARD_REQUEST_HEADERS) {
    const value = request.headers.get(name);
    if (value) headers.set(name, value);
  }
  headers.set("authorization", `Bearer ${accessToken}`);
  if (tenant) headers.set("x-nexiqon-tenant", tenant);
  const traceparent = request.headers.get("traceparent");
  if (traceparent) headers.set("traceparent", traceparent);
  const hasBody = !["GET", "HEAD"].includes(request.method);
  const upstream = await fetch(target, {
    method: request.method,
    headers,
    body: hasBody ? await request.arrayBuffer() : undefined,
    redirect: "manual",
    cache: "no-store",
  });
  const out = new Headers();
  for (const name of FORWARD_RESPONSE_HEADERS) {
    const value = upstream.headers.get(name);
    if (value) out.set(name, value);
  }
  return new Response(upstream.status === 304 ? null : upstream.body, { status: upstream.status, headers: out });
}
