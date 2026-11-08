"use client";

import { Building2, Check, ChevronsUpDown, Languages, LogOut, Monitor, Moon, Plus, Sun } from "lucide-react";
import Link from "next/link";
import { usePathname } from "next/navigation";
import { useLocale, useTranslations } from "next-intl";
import { useTheme } from "next-themes";

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
} from "@/components/ui/sidebar";
import type { StudioMembership } from "@/app/api/session/route";
import { type Locale, localeNames, locales } from "@/i18n/config";
import type { SessionUser } from "@/lib/server/session";

import { useShellActions } from "./actions";
import { activeItem, NAV } from "./nav";

function initials(user: SessionUser): string {
  const source = user.name || user.email || "?";
  return source
    .split(/[\s@.]+/)
    .filter(Boolean)
    .slice(0, 2)
    .map((p) => p[0]?.toUpperCase())
    .join("");
}

export function AppSidebar({ user, memberships, active }: { user: SessionUser; memberships: StudioMembership[]; active: StudioMembership }) {
  const t = useTranslations();
  const pathname = usePathname();
  const current = activeItem(pathname);
  const locale = useLocale();
  const { theme, setTheme } = useTheme();
  const actions = useShellActions();

  return (
    <Sidebar collapsible="icon" aria-label={t("nav.settings")}>
      <SidebarHeader>
        <SidebarMenu>
          <SidebarMenuItem>
            <DropdownMenu>
              <DropdownMenuTrigger asChild>
                <SidebarMenuButton size="lg" data-testid="org-switcher">
                  <span className="sr-only">{t("shell.switchOrg")}: </span>
                  <span className="flex size-8 shrink-0 items-center justify-center rounded-md bg-sidebar-primary text-sidebar-primary-foreground" aria-hidden="true">
                    <Building2 className="size-4" />
                  </span>
                  <span className="grid flex-1 text-start leading-tight">
                    <span className="truncate font-semibold">{active.tenant_name}</span>
                    <span className="truncate text-xs opacity-80">{t(`members.roles.${active.role}`)}</span>
                  </span>
                  <ChevronsUpDown className="ms-auto size-4" aria-hidden="true" />
                </SidebarMenuButton>
              </DropdownMenuTrigger>
              <DropdownMenuContent className="w-64" align="start">
                <DropdownMenuLabel>{t("shell.organizations")}</DropdownMenuLabel>
                {memberships.map((m) => (
                  <DropdownMenuItem key={m.tenant_id} onSelect={() => actions.switchOrg(m.tenant_slug, m.tenant_name)}>
                    <span className="flex-1 truncate">{m.tenant_name}</span>
                    {m.tenant_id === active.tenant_id ? <Check className="size-4" aria-label="current" /> : null}
                  </DropdownMenuItem>
                ))}
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

      <SidebarContent>
        {NAV.map((group) => (
          <SidebarGroup key={group.key}>
            <SidebarGroupLabel>{t(`nav.${group.key}`)}</SidebarGroupLabel>
            <SidebarGroupContent>
              <SidebarMenu>
                {group.items.map((item) => {
                  const isActive = current?.href === item.href;
                  return (
                    <SidebarMenuItem key={item.key}>
                      <SidebarMenuButton asChild isActive={isActive} tooltip={t(`nav.${item.key}`)}>
                        <Link href={item.href} aria-current={isActive ? "page" : undefined}>
                          <item.icon aria-hidden="true" />
                          <span>{t(`nav.${item.key}`)}</span>
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

      <SidebarFooter>
        <SidebarMenu>
          <SidebarMenuItem>
            <DropdownMenu>
              <DropdownMenuTrigger asChild>
                <SidebarMenuButton size="lg" data-testid="user-menu">
                  <span className="sr-only">{t("shell.account")}: </span>
                  <span className="flex size-8 shrink-0 items-center justify-center rounded-full bg-sidebar-accent text-xs font-semibold" aria-hidden="true">
                    {initials(user)}
                  </span>
                  <span className="grid flex-1 text-start leading-tight">
                    <span className="truncate font-medium">{user.name ?? user.email}</span>
                    {user.name && user.email ? <span className="truncate text-xs opacity-80">{user.email}</span> : null}
                  </span>
                  <ChevronsUpDown className="ms-auto size-4" aria-hidden="true" />
                </SidebarMenuButton>
              </DropdownMenuTrigger>
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
    </Sidebar>
  );
}
