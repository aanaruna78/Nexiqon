"use client";

import { ChevronsUpDown, CircleHelp, Languages, LogOut, Monitor, Moon, Plus, Search, Sun, Check } from "lucide-react";
import Link from "next/link";
import { usePathname } from "next/navigation";
import { useLocale, useTranslations } from "next-intl";
import { useTheme } from "next-themes";
import { useState } from "react";

import {
  DropdownMenu,
  DropdownMenuContent,
  DropdownMenuItem,
  DropdownMenuLabel,
  DropdownMenuRadioGroup,
  DropdownMenuRadioItem,
  DropdownMenuSeparator,
  DropdownMenuSub,
  DropdownMenuSubContent,
  DropdownMenuSubTrigger,
  DropdownMenuTrigger,
} from "@/components/ui/dropdown-menu";
import {
  Sidebar,
  SidebarContent,
  SidebarFooter,
  SidebarGroup,
  SidebarGroupContent,
  SidebarGroupLabel,
  SidebarHeader,
  SidebarMenu,
  SidebarMenuButton,
  SidebarMenuItem,
  SidebarRail,
  useSidebar,
} from "@/components/ui/sidebar";
import type { StudioMembership } from "@/app/api/session/route";
import { Avatar } from "@/components/visual/avatar";
import { BrandMark } from "@/components/visual/brand-mark";
import { Hint } from "@/components/visual/hint";
import type { Tone } from "@/components/visual/icon-tile";
import { direction, type Locale, localeNames, locales } from "@/i18n/config";
import type { SessionUser } from "@/lib/server/session";
import { cn } from "@/lib/utils";
import { STUDIO_VERSION } from "@/lib/version";

import { useShellActions } from "./actions";
import { openCommandMenu } from "./command-menu";
import { HelpDialog } from "./help-dialog";
import { activeItem, NAV } from "./nav";

/** Icon tints for the dark sidebar (all >= 7:1 on the navy background). */
const SIDEBAR_TONE: Record<Tone, string> = {
  teal: "text-teal-300",
  navy: "text-slate-300",
  amber: "text-amber-300",
  violet: "text-violet-300",
  rose: "text-rose-300",
  sky: "text-sky-300",
  slate: "text-slate-300",
};

const ROLE_PILL: Record<string, string> = {
  owner: "bg-amber-300/15 text-amber-200",
  admin: "bg-violet-300/15 text-violet-200",
  editor: "bg-teal-300/15 text-teal-200",
  member: "bg-slate-300/15 text-slate-200",
};

const ENV_PILL: Record<string, string> = {
  development: "bg-sky-300/15 text-sky-200 ring-sky-300/30",
  staging: "bg-amber-300/15 text-amber-200 ring-amber-300/30",
  production: "bg-rose-300/15 text-rose-200 ring-rose-300/30",
};

export type StudioEnvironment = "development" | "staging" | "production";

export function AppSidebar({
  user,
  memberships,
  active,
  environment,
}: {
  user: SessionUser;
  memberships: StudioMembership[];
  active: StudioMembership;
  environment: StudioEnvironment;
}) {
  const t = useTranslations();
  const pathname = usePathname();
  const current = activeItem(pathname);
  const locale = useLocale();
  const { theme, setTheme } = useTheme();
  const { isMobile, state } = useSidebar();
  const actions = useShellActions();
  const [helpOpen, setHelpOpen] = useState(false);
  const side = direction(locale) === "rtl" ? "left" : "right";
  const collapsed = state === "collapsed" && !isMobile;
  const envName = t(`shell.environments.${environment}`);

  return (
    <Sidebar collapsible="icon" aria-label={t("nav.settings")}>
      <SidebarHeader className="gap-3 border-b border-sidebar-border/60 px-3 pt-4 pb-3">
        {/* Brand + environment */}
        <div className="flex items-center gap-2.5 px-1 group-data-[collapsible=icon]:justify-center group-data-[collapsible=icon]:px-0">
          <Link href="/" className="flex min-w-0 items-center gap-2.5 rounded-md outline-none focus-visible:ring-2 focus-visible:ring-sidebar-ring">
            <BrandMark className="size-8 shrink-0" />
            <span className="truncate text-[15px] font-semibold tracking-tight group-data-[collapsible=icon]:hidden">
              Nexiqon <span className="font-normal opacity-70">Studio</span>
            </span>
          </Link>
          <Hint label={t("shell.environmentHint", { name: envName })} side="bottom">
            <span
              className={cn(
                "ms-auto cursor-default rounded-md px-1.5 py-0.5 text-[10px] font-semibold uppercase tracking-wider ring-1 ring-inset group-data-[collapsible=icon]:hidden",
                ENV_PILL[environment],
              )}
            >
              <span className="sr-only">{t("shell.environment")}: </span>
              {envName}
            </span>
          </Hint>
        </div>

        {/* Search */}
        <SidebarMenu>
          <SidebarMenuItem>
            <SidebarMenuButton
              onClick={openCommandMenu}
              tooltip={{ children: `${t("shell.search")} (Ctrl+K)`, side, hidden: !collapsed }}
              className="h-9 border border-sidebar-border bg-white/[0.04] text-sidebar-foreground/80 hover:bg-white/[0.08] hover:text-sidebar-foreground"
            >
              <Search aria-hidden="true" />
              <span>{t("shell.search")}…</span>
              <kbd aria-hidden="true" className="ms-auto rounded border border-sidebar-border px-1 font-mono text-[10px] opacity-80 group-data-[collapsible=icon]:hidden">
                ⌘K
              </kbd>
            </SidebarMenuButton>
          </SidebarMenuItem>
        </SidebarMenu>

        {/* Organization */}
        <SidebarMenu>
          <SidebarMenuItem>
            <DropdownMenu>
              <Hint label={t("shell.switchOrg")} side={side}>
                <DropdownMenuTrigger asChild>
                  <SidebarMenuButton size="lg" data-testid="org-switcher" className="border border-sidebar-border bg-gradient-to-br from-white/[0.07] to-white/[0.02] shadow-sm hover:from-white/[0.1]">
                    <span className="sr-only">{t("shell.switchOrg")}: </span>
                    <Avatar name={active.tenant_name} className="size-8 rounded-lg ring-0" />
                    <span className="grid flex-1 gap-0.5 text-start leading-tight">
                      <span className="truncate font-semibold">{active.tenant_name}</span>
                      <span className={cn("w-fit rounded px-1.5 text-[10px] font-medium", ROLE_PILL[active.role])}>{t(`members.roles.${active.role}`)}</span>
                    </span>
                    <ChevronsUpDown className="ms-auto size-4 opacity-70" aria-hidden="true" />
                  </SidebarMenuButton>
                </DropdownMenuTrigger>
              </Hint>
              <DropdownMenuContent className="w-72" align="start" side={isMobile ? "bottom" : side}>
                <DropdownMenuLabel className="text-xs text-muted-foreground">{t("shell.organizations")}</DropdownMenuLabel>
                <div className="max-h-72 overflow-y-auto">
                  {memberships.map((m) => (
                    <DropdownMenuItem key={m.tenant_id} onSelect={() => actions.switchOrg(m.tenant_slug, m.tenant_name)} className="gap-2.5 py-2">
                      <Avatar name={m.tenant_name} className="size-7 rounded-md text-[10px] ring-0" />
                      <span className="grid flex-1 leading-tight">
                        <span className="truncate font-medium">{m.tenant_name}</span>
                        <span className="text-xs text-muted-foreground">{t(`members.roles.${m.role}`)}</span>
                      </span>
                      {m.tenant_id === active.tenant_id ? <Check className="size-4 text-primary" aria-label="current" /> : null}
                    </DropdownMenuItem>
                  ))}
                </div>
                <DropdownMenuSeparator />
                <DropdownMenuItem asChild>
                  <Link href="/onboarding">
                    <Plus className="size-4" aria-hidden="true" />
                    {t("shell.createOrg")}
                  </Link>
                </DropdownMenuItem>
              </DropdownMenuContent>
            </DropdownMenu>
          </SidebarMenuItem>
        </SidebarMenu>
      </SidebarHeader>

      <SidebarContent className="gap-0 px-1">
        {NAV.map((group) => (
          <SidebarGroup key={group.key} className="py-1.5">
            <SidebarGroupLabel className="text-[10px] font-semibold uppercase tracking-[0.12em] text-sidebar-foreground/55">
              {t(`nav.${group.key}`)}
            </SidebarGroupLabel>
            <SidebarGroupContent>
              <SidebarMenu className="gap-0.5">
                {group.items.map((item) => {
                  const isActive = current?.href === item.href;
                  const label = t(`nav.${item.key}`);
                  return (
                    <SidebarMenuItem key={item.key}>
                      <SidebarMenuButton
                        asChild
                        isActive={isActive}
                        tooltip={{
                          side,
                          hidden: isMobile,
                          className: "max-w-60",
                          children: (
                            <span className="grid gap-0.5">
                              <span className="font-medium">{label}</span>
                              <span className="opacity-80">{t(`navHints.${item.key}`)}</span>
                              {item.phase ? <span className="opacity-80">{t("shell.soonHint", { phase: item.phase })}</span> : null}
                            </span>
                          ),
                        }}
                        className={cn(
                          "relative h-9 gap-2.5 rounded-lg transition-all duration-150",
                          "before:absolute before:inset-y-2 before:-start-1 before:w-[3px] before:rounded-full before:bg-sidebar-primary before:opacity-0 before:transition-opacity",
                          "hover:bg-white/[0.06]",
                          "data-[active=true]:bg-gradient-to-r data-[active=true]:from-white/[0.12] data-[active=true]:to-white/[0.03] data-[active=true]:font-medium data-[active=true]:text-white data-[active=true]:shadow-sm data-[active=true]:before:opacity-100 rtl:data-[active=true]:bg-gradient-to-l",
                        )}
                      >
                        <Link href={item.href} aria-current={isActive ? "page" : undefined}>
                          <span
                            className={cn(
                              "flex size-6 shrink-0 items-center justify-center rounded-md transition-colors",
                              isActive ? "bg-sidebar-primary text-sidebar-primary-foreground shadow-[0_0_12px_-2px_var(--sidebar-primary)]" : cn("bg-white/[0.06]", SIDEBAR_TONE[item.tone]),
                            )}
                            aria-hidden="true"
                          >
                            <item.icon className="size-3.5" />
                          </span>
                          <span className="truncate">{label}</span>
                          {item.phase ? (
                            <span className="ms-auto rounded-full bg-white/[0.08] px-1.5 py-px text-[10px] font-medium text-sidebar-foreground/75 group-data-[collapsible=icon]:hidden">
                              {t("shell.soon")}
                            </span>
                          ) : null}
                        </Link>
                      </SidebarMenuButton>
                    </SidebarMenuItem>
                  );
                })}
              </SidebarMenu>
            </SidebarGroupContent>
          </SidebarGroup>
        ))}
      </SidebarContent>

      <SidebarFooter className="gap-1 px-3 pb-3">
        <SidebarMenu>
          <SidebarMenuItem>
            <SidebarMenuButton
              onClick={() => setHelpOpen(true)}
              tooltip={{ children: t("shell.help"), side, hidden: !collapsed }}
              className="h-9 text-sidebar-foreground/80 hover:bg-white/[0.06]"
            >
              <CircleHelp aria-hidden="true" />
              <span>{t("shell.help")}</span>
              <span className="ms-auto text-[10px] opacity-60 group-data-[collapsible=icon]:hidden">{t("shell.version", { version: STUDIO_VERSION })}</span>
            </SidebarMenuButton>
          </SidebarMenuItem>
          <SidebarMenuItem>
            <DropdownMenu>
              <Hint label={t("shell.accountHint")} side={side}>
                <DropdownMenuTrigger asChild>
                  <SidebarMenuButton size="lg" data-testid="user-menu" className="border border-transparent hover:border-sidebar-border hover:bg-white/[0.05]">
                    <span className="sr-only">{t("shell.account")}: </span>
                    <Avatar name={user.name || user.email || "?"} className="size-8 ring-2 ring-sidebar" />
                    <span className="grid flex-1 text-start leading-tight">
                      <span className="truncate font-medium">{user.name ?? user.email}</span>
                      {user.name && user.email ? <span className="truncate text-xs opacity-70">{user.email}</span> : null}
                    </span>
                    <ChevronsUpDown className="ms-auto size-4 opacity-70" aria-hidden="true" />
                  </SidebarMenuButton>
                </DropdownMenuTrigger>
              </Hint>
              <DropdownMenuContent className="w-60" side="top" align="start">
                <DropdownMenuSub>
                  <DropdownMenuSubTrigger>
                    <Sun className="size-4" aria-hidden="true" />
                    {t("shell.theme")}
                  </DropdownMenuSubTrigger>
                  <DropdownMenuSubContent>
                    <DropdownMenuRadioGroup value={theme ?? "system"} onValueChange={setTheme}>
                      <DropdownMenuRadioItem value="light"><Sun className="size-4" aria-hidden="true" />{t("shell.light")}</DropdownMenuRadioItem>
                      <DropdownMenuRadioItem value="dark"><Moon className="size-4" aria-hidden="true" />{t("shell.dark")}</DropdownMenuRadioItem>
                      <DropdownMenuRadioItem value="system"><Monitor className="size-4" aria-hidden="true" />{t("shell.system")}</DropdownMenuRadioItem>
                    </DropdownMenuRadioGroup>
                  </DropdownMenuSubContent>
                </DropdownMenuSub>
                <DropdownMenuSub>
                  <DropdownMenuSubTrigger>
                    <Languages className="size-4" aria-hidden="true" />
                    {t("shell.language")}
                  </DropdownMenuSubTrigger>
                  <DropdownMenuSubContent>
                    <DropdownMenuRadioGroup value={locale} onValueChange={(v) => actions.setLocale(v as Locale)}>
                      {locales.map((l) => (
                        <DropdownMenuRadioItem key={l} value={l} lang={l === "en-XA" ? "en" : l}>
                          {localeNames[l]}
                        </DropdownMenuRadioItem>
                      ))}
                    </DropdownMenuRadioGroup>
                  </DropdownMenuSubContent>
                </DropdownMenuSub>
                <DropdownMenuSeparator />
                <DropdownMenuItem onSelect={() => actions.signOut()} data-testid="sign-out">
                  <LogOut className="size-4" aria-hidden="true" />
                  {t("shell.signOut")}
                </DropdownMenuItem>
              </DropdownMenuContent>
            </DropdownMenu>
          </SidebarMenuItem>
        </SidebarMenu>
      </SidebarFooter>
      <SidebarRail />
      <HelpDialog open={helpOpen} onOpenChange={setHelpOpen} />
    </Sidebar>
  );
}
