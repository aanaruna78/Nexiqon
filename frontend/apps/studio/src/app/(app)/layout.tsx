import { WorkspaceShell } from "@/components/workspace/workspace-shell";
import { requireMembership } from "@/lib/server/studio";

/** Everyone's pages: the assistant (home) and personal settings. Admin lives under /admin. */
export default async function WorkspaceLayout({ children }: LayoutProps<"/">) {
  const { session, memberships, active, canAdmin } = await requireMembership();
  return (
    <WorkspaceShell user={session.user} memberships={memberships} active={active} canAdmin={canAdmin}>
      {children}
    </WorkspaceShell>
  );
}
