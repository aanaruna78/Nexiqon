/** Server-side loading of the signed-in user's organizations for layouts. */

import type { StudioMembership } from "@/app/api/session/route";

import { studioEnv } from "./env";

export async function loadMemberships(accessToken: string): Promise<StudioMembership[] | null> {
  const response = await fetch(`${studioEnv().gatewayUrl}/identity/v1/session/memberships`, {
    headers: { authorization: `Bearer ${accessToken}` },
    cache: "no-store",
  });
  if (response.status === 401) return null;
  if (!response.ok) throw new Error(`memberships failed: ${response.status}`);
  return (await response.json()) as StudioMembership[];
}
