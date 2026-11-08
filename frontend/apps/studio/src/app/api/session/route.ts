import { currentSession, currentTenant } from "@/lib/server/auth/current";
import { studioEnv } from "@/lib/server/env";

export interface StudioMembership {
  tenant_id: string;
  tenant_slug: string;
  tenant_name: string;
  role: string;
}

export async function GET(): Promise<Response> {
  const session = await currentSession({ persist: true });
  if (!session) return Response.json({ signedIn: false }, { status: 401 });
  const env = studioEnv();
  const upstream = await fetch(`${env.gatewayUrl}/identity/v1/session/memberships`, {
    headers: { authorization: `Bearer ${session.accessToken}` },
    cache: "no-store",
  });
  const memberships: StudioMembership[] = upstream.ok ? await upstream.json() : [];
  return Response.json({ signedIn: true, user: session.user, tenant: await currentTenant(), memberships });
}
