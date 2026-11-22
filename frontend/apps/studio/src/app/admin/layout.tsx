import { redirect } from "next/navigation";

import { AppShell } from "@/components/shell/app-shell";
import { studioEnv } from "@/lib/server/env";
import { requireMembership } from "@/lib/server/studio";

/** The Admin area: building and running assistants, and administering the organization. */
export default async function AdminLayout({ children }: LayoutProps<"/admin">) {
  const { session, memberships, active, canAdmin } = await requireMembership();
  if (!canAdmin) redirect("/"); // members use the assistant and their own settings
  return (
    <AppShell user={session.user} memberships={memberships} active={active} environment={studioEnv().environment}>
      {children}
    </AppShell>
  );
}
