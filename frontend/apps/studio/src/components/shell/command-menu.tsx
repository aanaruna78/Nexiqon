"use client";

import { Building2, KeyRound, Languages, LogOut, Moon, UserPlus } from "lucide-react";
import { useRouter } from "next/navigation";
import { useTranslations } from "next-intl";
import { useTheme } from "next-themes";
import { useEffect, useState } from "react";

import {
  Command,
  CommandDialog,
  CommandEmpty,
  CommandGroup,
  CommandInput,
  CommandItem,
  CommandList,
  CommandSeparator,
} from "@/components/ui/command";
import type { StudioMembership } from "@/app/api/session/route";
import { localeNames, locales } from "@/i18n/config";

import { useShellActions } from "./actions";
import { NAV } from "./nav";

const OPEN_EVENT = "nexiqon:command-menu";

export function openCommandMenu(): void {
  window.dispatchEvent(new Event(OPEN_EVENT));
}

/** ⌘K / Ctrl+K: jump anywhere and run common actions from the keyboard (UX principle 6). */
export function CommandMenu({ memberships }: { memberships: StudioMembership[] }) {
  const t = useTranslations();
  const router = useRouter();
  const [open, setOpen] = useState(false);
  const { resolvedTheme, setTheme } = useTheme();
  const actions = useShellActions();

  useEffect(() => {
    const onKey = (e: KeyboardEvent) => {
      if (e.key.toLowerCase() === "k" && (e.metaKey || e.ctrlKey)) {
        e.preventDefault();
        setOpen((o) => !o);
      }
    };
    const onOpen = () => setOpen(true);
    window.addEventListener("keydown", onKey);
    window.addEventListener(OPEN_EVENT, onOpen);
    return () => {
      window.removeEventListener("keydown", onKey);
      window.removeEventListener(OPEN_EVENT, onOpen);
    };
  }, []);

  const run = (fn: () => void) => {
    setOpen(false);
    fn();
  };

  return (
    <CommandDialog open={open} onOpenChange={setOpen} title={t("shell.openCommand")} description={t("shell.commandPlaceholder")}>
      <Command>
      <CommandInput placeholder={t("shell.commandPlaceholder")} />
      <CommandList>
        <CommandEmpty>{t("shell.noResults")}</CommandEmpty>
        <CommandGroup heading={t("shell.navigation")}>
          {NAV.flatMap((g) => g.items).map((item) => (
            <CommandItem key={item.key} value={`go ${t(`nav.${item.key}`)}`} onSelect={() => run(() => router.push(item.href))}>
              <item.icon aria-hidden="true" />
              {t(`nav.${item.key}`)}
            </CommandItem>
          ))}
        </CommandGroup>
        <CommandSeparator />
        <CommandGroup heading={t("shell.quickActions")}>
          <CommandItem value={t("members.invite")} onSelect={() => run(() => router.push("/settings/members?invite=1"))}>
            <UserPlus aria-hidden="true" />
            {t("members.invite")}
          </CommandItem>
          <CommandItem value={t("apiKeys.create")} onSelect={() => run(() => router.push("/settings/api-keys?create=1"))}>
            <KeyRound aria-hidden="true" />
            {t("apiKeys.create")}
          </CommandItem>
          <CommandItem value={`${t("shell.theme")} ${t("shell.dark")} ${t("shell.light")}`} onSelect={() => run(() => setTheme(resolvedTheme === "dark" ? "light" : "dark"))}>
            <Moon aria-hidden="true" />
            {t("shell.theme")}: {resolvedTheme === "dark" ? t("shell.light") : t("shell.dark")}
          </CommandItem>
          {locales.map((l) => (
            <CommandItem key={l} value={`${t("shell.language")} ${localeNames[l]}`} onSelect={() => run(() => actions.setLocale(l))}>
              <Languages aria-hidden="true" />
              {t("shell.language")}: {localeNames[l]}
            </CommandItem>
          ))}
          <CommandItem value={t("shell.signOut")} onSelect={() => run(() => actions.signOut())}>
            <LogOut aria-hidden="true" />
            {t("shell.signOut")}
          </CommandItem>
        </CommandGroup>
        {memberships.length > 1 ? (
          <>
            <CommandSeparator />
            <CommandGroup heading={t("shell.switchOrg")}>
              {memberships.map((m) => (
                <CommandItem key={m.tenant_id} value={`org ${m.tenant_name}`} onSelect={() => run(() => actions.switchOrg(m.tenant_slug, m.tenant_name))}>
                  <Building2 aria-hidden="true" />
                  {m.tenant_name}
                </CommandItem>
              ))}
            </CommandGroup>
          </>
        ) : null}
      </CommandList>
      </Command>
    </CommandDialog>
  );
}
