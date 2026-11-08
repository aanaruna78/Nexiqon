"use client";

import type { ReactNode } from "react";

import { SidebarInset, SidebarProvider } from "@/components/ui/sidebar";
import type { StudioMembership } from "@/app/api/session/route";
import type { SessionUser } from "@/lib/server/session";
import { accentVars } from "@/lib/theme";

import { AppSidebar } from "./app-sidebar";
import { CommandMenu } from "./command-menu";
import { Header } from "./header";
import { SkipLink } from "./skip-link";
import { StudioProvider } from "./studio-context";

export interface ShellProps {
  user: SessionUser;
  memberships: StudioMembership[];
  active: StudioMembership;
  accent?: string | null;
  children: ReactNode;
}

export function AppShell({ user, memberships, active, accent, children }: ShellProps) {
  return (
    <StudioProvider user={user} active={active}>
    <SidebarProvider style={accentVars(accent)}>
      <SkipLink />
      <AppSidebar user={user} memberships={memberships} active={active} />
      <SidebarInset className="bg-surface">
        <Header />
        <main id="main" tabIndex={-1} className="mx-auto w-full max-w-6xl flex-1 px-4 py-6 outline-none sm:px-6 sm:py-8 lg:px-8">
          {children}
        </main>
      </SidebarInset>
      <CommandMenu memberships={memberships} />
    </SidebarProvider>
    </StudioProvider>
  );
}
