/** Server-side loading of the signed-in user's organizations for layouts. */

import { redirect } from "next/navigation";
import { cache } from "react";

import type { StudioMembership } from "@/app/api/session/route";
import { currentSession, currentTenant } from "@/lib/server/auth/current";

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

/** Roles that may open the Admin area (build and run assistants, administer the organization). */
export const ADMIN_AREA_ROLES = new Set(["owner", "admin", "editor"]);

/**
 * The signed-in person and their current organization, for any page behind sign-in. Sends them to
 * sign in, create their first organization, or choose one, as needed. Cached per request, so a
 * layout and its page share one lookup.
 */
export const requireMembership = cache(async () => {
  const session = await currentSession();
  if (!session) redirect("/auth/login");
  const memberships = await loadMemberships(session.accessToken);
  if (memberships === null) redirect("/auth/login");
  if (memberships.length === 0) redirect("/onboarding");
  const selected = await currentTenant();
  const active = memberships.find((m) => m.tenant_slug === selected || m.tenant_id === selected);
  if (!active) redirect("/select-org");
  return { session, memberships, active, canAdmin: ADMIN_AREA_ROLES.has(active.role) };
});
