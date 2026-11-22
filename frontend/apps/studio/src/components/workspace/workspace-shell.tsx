"use client";

import { Check, ChevronsUpDown, LayoutDashboard } from "lucide-react";
import Link from "next/link";
import { useTranslations } from "next-intl";
import type { ReactNode } from "react";

import type { StudioMembership } from "@/app/api/session/route";
import { useShellActions } from "@/components/shell/actions";
import { InboxBell } from "@/components/shell/inbox-bell";
import { SkipLink } from "@/components/shell/skip-link";
import { StudioProvider } from "@/components/shell/studio-context";
import { Button } from "@/components/ui/button";
import { DropdownMenu, DropdownMenuContent, DropdownMenuItem, DropdownMenuLabel, DropdownMenuTrigger } from "@/components/ui/dropdown-menu";
import { BrandMark } from "@/components/visual/brand-mark";
import { Hint } from "@/components/visual/hint";
import type { SessionUser } from "@/lib/server/session";

import { UserMenu } from "./user-menu";

/** The frame for everyone's pages (the assistant, personal settings): a slim top bar and the page. */
export function WorkspaceShell({
  user,
  memberships,
  active,
  canAdmin,
  children,
}: {
  user: SessionUser;
  memberships: StudioMembership[];
  active: StudioMembership;
  canAdmin: boolean;
  children: ReactNode;
}) {
  const t = useTranslations();
  const actions = useShellActions();
  return (
    <StudioProvider user={user} active={active}>
      <div className="flex h-dvh flex-col bg-background">
        <SkipLink />
        <header className="flex h-14 flex-none items-center gap-3 border-b px-3 sm:px-4">
          <Link href="/" className="flex items-center gap-2 rounded-lg px-1 outline-none focus-visible:ring-2 focus-visible:ring-ring" aria-label={t("workspace.home")}>
            <BrandMark className="size-8" />
            <span className="hidden text-[15px] font-semibold tracking-tight sm:inline">Nexiqon</span>
          </Link>
          <span className="h-5 w-px bg-border" aria-hidden="true" />
          {memberships.length > 1 ? (
            <DropdownMenu>
              <Hint label={t("shell.switchOrg")} side="bottom">
                <DropdownMenuTrigger asChild>
                  <Button variant="ghost" size="sm" className="h-8 max-w-56 gap-1.5 font-medium" data-testid="org-switcher">
                    <span className="truncate">{active.tenant_name}</span>
                    <ChevronsUpDown className="size-3.5 opacity-60" aria-hidden="true" />
                  </Button>
                </DropdownMenuTrigger>
              </Hint>
              <DropdownMenuContent align="start" className="w-64">
                <DropdownMenuLabel className="text-xs font-medium text-muted-foreground">{t("shell.organizations")}</DropdownMenuLabel>
                {memberships.map((m) => (
                  <DropdownMenuItem key={m.tenant_id} onSelect={() => m.tenant_id !== active.tenant_id && actions.switchOrg(m.tenant_slug, m.tenant_name)}>
                    <span className="flex-1 truncate">{m.tenant_name}</span>
                    {m.tenant_id === active.tenant_id ? <Check className="size-4" aria-hidden="true" /> : null}
                  </DropdownMenuItem>
                ))}
              </DropdownMenuContent>
            </DropdownMenu>
          ) : (
            <span className="truncate px-2 text-sm font-medium" data-testid="org-switcher">{active.tenant_name}</span>
          )}
          <div className="ms-auto flex items-center gap-1.5">
            {canAdmin ? (
              <>
                <InboxBell />
                <Hint label={t("workspace.adminHint")} side="bottom">
                  <Button asChild variant="outline" size="sm" className="h-9 gap-1.5 rounded-lg">
                    <Link href="/admin" data-testid="admin-button">
                      <LayoutDashboard className="size-4" aria-hidden="true" />
                      <span className="hidden sm:inline">{t("workspace.admin")}</span>
                    </Link>
                  </Button>
                </Hint>
              </>
            ) : null}
            <UserMenu user={user} canAdmin={canAdmin} />
          </div>
        </header>
        <div className="flex min-h-0 flex-1 flex-col">{children}</div>
      </div>
    </StudioProvider>
  );
}
