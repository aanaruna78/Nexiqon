/**
 * Content-Security-Policy (S-02). Studio's browser code talks only to Studio itself, and in
 * split-origin mode (DV-08) also to the data-plane Studio. Next.js inlines its bootstrap scripts,
 * hence 'unsafe-inline' for scripts; the dev server also needs eval and a websocket.
 */
export function contentSecurityPolicy(o: { dev: boolean; dataOrigin?: string | null }): string {
  const connect = ["'self'", ...(o.dataOrigin ? [o.dataOrigin] : []), ...(o.dev ? ["ws:", "wss:"] : [])];
  return [
    "default-src 'self'",
    `script-src 'self' 'unsafe-inline'${o.dev ? " 'unsafe-eval'" : ""}`,
    "style-src 'self' 'unsafe-inline'",
    "img-src 'self' data: blob:",
    "font-src 'self' data:",
    `connect-src ${connect.join(" ")}`,
    "object-src 'none'",
    "base-uri 'self'",
    "form-action 'self'",
    "frame-ancestors 'none'",
    ...(o.dev ? [] : ["upgrade-insecure-requests"]),
  ].join("; ");
}
