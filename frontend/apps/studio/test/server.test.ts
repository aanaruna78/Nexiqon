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
