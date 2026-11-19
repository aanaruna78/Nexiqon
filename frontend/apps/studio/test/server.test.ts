// @vitest-environment node
import { describe, expect, it } from "vitest";

import { isSameOrigin, upstreamUrl } from "@/lib/server/gateway";
import { safeReturnTo, seal, unseal } from "@/lib/server/session";

const SECRET = "a-test-secret-that-is-long-enough-0123456789";

describe("session cookie", () => {
  it("round-trips and rejects tampering or another secret", async () => {
    const token = await seal({ accessToken: "abc", user: { sub: "u1" } }, SECRET);
    expect(await unseal<{ accessToken: string }>(token, SECRET)).toMatchObject({ accessToken: "abc" });
    const tampered = token.slice(0, -4) + (token.endsWith("AAAA") ? "BBBB" : "AAAA");
    expect(await unseal(tampered, SECRET)).toBeNull();
    expect(await unseal(token, `${SECRET}-other`)).toBeNull();
    expect(await unseal(undefined, SECRET)).toBeNull();
  });

  it("only allows same-site return paths", () => {
    expect(safeReturnTo("/settings/members?x=1")).toBe("/settings/members?x=1");
    for (const bad of ["https://evil.example", "//evil.example", "/\\evil.example", "", null]) {
      expect(safeReturnTo(bad)).toBe("/");
    }
  });
});

describe("BFF", () => {
  const gw = "http://gateway:8000";

  it("builds upstream URLs that cannot escape the gateway", () => {
    expect(upstreamUrl(gw, ["identity", "v1", "members"], "?a=1")?.toString()).toBe("http://gateway:8000/identity/v1/members?a=1");
    expect(upstreamUrl(gw, ["..", "etc"], "")).toBeNull();
    expect(upstreamUrl(gw, ["identity", ""], "")).toBeNull();
    expect(upstreamUrl(gw, [], "")).toBeNull();
    expect(upstreamUrl(gw, ["@evil.example"], "")?.origin).toBe("http://gateway:8000");
    expect(upstreamUrl(gw, ["a/b"], "")?.pathname).toBe("/a%2Fb");
  });

  it("requires the CSRF header and same origin for mutations", () => {
    const base = "http://localhost:3100";
    const req = (method: string, headers: Record<string, string>) => new Request(`${base}/api/nx/x`, { method, headers });
    expect(isSameOrigin(req("GET", {}), base)).toBe(true);
    expect(isSameOrigin(req("POST", { origin: base, "x-nexiqon-csrf": "1" }), base)).toBe(true);
    expect(isSameOrigin(req("POST", { origin: base }), base)).toBe(false);
    expect(isSameOrigin(req("POST", { origin: "https://evil.example", "x-nexiqon-csrf": "1" }), base)).toBe(false);
  });
});

describe("split-origin Studio (DV-08)", () => {
  it("sends calls for content services to the data-plane Studio and the rest here", async () => {
    const { routeFor } = await import("@/lib/split");
    expect(routeFor("conversation/v1/conversations", "https://studio-data.example")).toEqual({
      url: "https://studio-data.example/api/nx/conversation/v1/conversations",
      crossOrigin: true,
    });
    expect(routeFor("/ingestion/v1/collections", "https://studio-data.example").crossOrigin).toBe(true);
    expect(routeFor("config/v1/objects", "https://studio-data.example")).toEqual({ url: "/api/nx/config/v1/objects", crossOrigin: false });
    expect(routeFor("conversation/v1/conversations", null)).toEqual({ url: "/api/nx/conversation/v1/conversations", crossOrigin: false });
  });

  it("returns to the peer Studio after sign-in, and nowhere else", async () => {
    const { afterLogin, cookieOptions, safeReturnTo } = await import("@/lib/server/session");
    const peer = "https://studio.example";
    expect(safeReturnTo("https://studio.example/conversations?c=1", peer)).toBe("https://studio.example/conversations?c=1");
    expect(safeReturnTo("https://evil.example/x", peer)).toBe("/");
    expect(safeReturnTo("https://studio.example.evil.example/x", peer)).toBe("/");
    expect(safeReturnTo("https://studio.example/x", null)).toBe("/");
    expect(afterLogin("https://studio-data.example", "/x")).toBe("https://studio-data.example/x");
    expect(afterLogin("https://studio-data.example", "https://studio.example/y")).toBe("https://studio.example/y");
    expect(cookieOptions(true, 60, true).sameSite).toBe("none");
    expect(cookieOptions(false, 60, true).sameSite).toBe("lax");
    expect(cookieOptions(true).sameSite).toBe("lax");
  });

  it("puts the data origin in connect-src only when split", async () => {
    const { contentSecurityPolicy } = await import("@/lib/csp");
    const split = contentSecurityPolicy({ dev: false, dataOrigin: "https://studio-data.example" });
    expect(split).toContain("connect-src 'self' https://studio-data.example");
    expect(contentSecurityPolicy({ dev: false })).toContain("connect-src 'self';");
    expect(contentSecurityPolicy({ dev: true })).toContain("'unsafe-eval'");
    expect(split).toContain("frame-ancestors 'none'");
  });
});
