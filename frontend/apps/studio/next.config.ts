import path from "node:path";

import type { NextConfig } from "next";
import createNextIntlPlugin from "next-intl/plugin";

// The container image (deploy/docker/studio.Dockerfile) sets NEXT_OUTPUT=standalone: a minimal
// server with only the files it needs, traced from the pnpm workspace root.
const standalone = process.env.NEXT_OUTPUT === "standalone";
const dev = process.env.NODE_ENV !== "production";

// The Content-Security-Policy is set per request in src/proxy.ts (it names the data origin
// in split-origin mode, which is runtime configuration).

const nextConfig: NextConfig = {
  poweredByHeader: false,
  ...(standalone ? { output: "standalone" as const, outputFileTracingRoot: path.join(__dirname, "../..") } : {}),
  // Every Studio page is per-user (session cookie), so Cache Components stay off for now.
  turbopack: {
    rules: {
      "*.css": { loaders: ["@tailwindcss/turbopack"], as: "*.css" },
    },
  },
  // The pages that moved when the chat became the home page (Admin and personal Settings split):
  // old links and bookmarks keep working.
  async redirects() {
    const pages = ["assistants", "knowledge", "playground", "conversations", "insights", "evaluations", "domain-packs", "actions", "get-started"];
    const settings = ["members", "api-keys", "audit", "configuration", "models", "organization", "webhooks"];
    return [
      ...pages.flatMap((p) => [
        { source: `/${p}`, destination: `/admin/${p}`, permanent: true },
        { source: `/${p}/:path*`, destination: `/admin/${p}/:path*`, permanent: true },
      ]),
      ...settings.flatMap((p) => [
        { source: `/settings/${p}`, destination: `/admin/${p}`, permanent: true },
        { source: `/settings/${p}/:path*`, destination: `/admin/${p}/:path*`, permanent: true },
      ]),
    ];
  },
  async headers() {
    return [
      {
        // The widget is loaded as an ES module from customers' websites (CORS fetch).
        source: "/widget/:path*",
        headers: [
          { key: "Access-Control-Allow-Origin", value: "*" },
          { key: "Cross-Origin-Resource-Policy", value: "cross-origin" },
          { key: "Cache-Control", value: "public, max-age=300" },
        ],
      },
      {
        source: "/:path*",
        headers: [
          { key: "X-Content-Type-Options", value: "nosniff" },
          { key: "Referrer-Policy", value: "strict-origin-when-cross-origin" },
          { key: "X-Frame-Options", value: "DENY" },
          { key: "Permissions-Policy", value: "camera=(), microphone=(), geolocation=()" },
          { key: "Cross-Origin-Opener-Policy", value: "same-origin" },
          ...(dev ? [] : [{ key: "Strict-Transport-Security", value: "max-age=63072000; includeSubDomains" }]),
        ],
      },
    ];
  },
};

export default createNextIntlPlugin("./src/i18n/request.ts")(nextConfig);
