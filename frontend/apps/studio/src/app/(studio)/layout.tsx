import { redirect } from "next/navigation";

import { AppShell } from "@/components/shell/app-shell";
import { currentSession, currentTenant } from "@/lib/server/auth/current";
import { loadMemberships } from "@/lib/server/studio";

export default async function StudioLayout({ children }: LayoutProps<"/">) {
  const session = await currentSession();
  if (!session) redirect("/auth/login");
  const memberships = await loadMemberships(session.accessToken);
  if (memberships === null) redirect("/auth/login");
  if (memberships.length === 0) redirect("/onboarding");
  const selected = await currentTenant();
  const active = memberships.find((m) => m.tenant_slug === selected || m.tenant_id === selected);
  if (!active) redirect("/select-org");
  return (
    <AppShell user={session.user} memberships={memberships} active={active}>
      {children}
    </AppShell>
  );
}
