"use client";

import { Languages, LayoutDashboard, LogOut, MessageSquare, Monitor, Moon, Settings, Sun } from "lucide-react";
import Link from "next/link";
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
import { useShellActions } from "@/components/shell/actions";
import { Avatar } from "@/components/visual/avatar";
import { Hint } from "@/components/visual/hint";
import { type Locale, localeNames, locales } from "@/i18n/config";
import type { SessionUser } from "@/lib/server/session";

/** The account menu: where you are going (assistant, Admin, Settings), theme, language, sign out. */
export function UserMenu({ user, canAdmin }: { user: SessionUser; canAdmin: boolean }) {
  const t = useTranslations();
  const locale = useLocale();
  const { theme, setTheme } = useTheme();
  const actions = useShellActions();
  const name = user.name || user.email || "?";
  return (
    <DropdownMenu>
      <Hint label={t("shell.accountHint")} side="bottom">
        <DropdownMenuTrigger asChild>
          <button type="button" className="rounded-full outline-none ring-offset-2 ring-offset-background focus-visible:ring-2 focus-visible:ring-ring" data-testid="user-menu">
            <span className="sr-only">{t("shell.account")}: {name}</span>
            <Avatar name={name} className="size-9" />
          </button>
        </DropdownMenuTrigger>
      </Hint>
      <DropdownMenuContent align="end" className="w-64">
        <DropdownMenuLabel className="font-normal">
          <span className="block truncate font-medium">{user.name ?? user.email}</span>
          {user.name && user.email ? <span className="block truncate text-xs text-muted-foreground">{user.email}</span> : null}
        </DropdownMenuLabel>
        <DropdownMenuSeparator />
        <DropdownMenuItem asChild>
          <Link href="/"><MessageSquare className="size-4" aria-hidden="true" />{t("workspace.assistant")}</Link>
        </DropdownMenuItem>
        {canAdmin ? (
          <DropdownMenuItem asChild>
            <Link href="/admin" data-testid="admin-link"><LayoutDashboard className="size-4" aria-hidden="true" />{t("workspace.admin")}</Link>
          </DropdownMenuItem>
        ) : null}
        <DropdownMenuItem asChild>
          <Link href="/settings" data-testid="settings-link"><Settings className="size-4" aria-hidden="true" />{t("workspace.settings")}</Link>
        </DropdownMenuItem>
        <DropdownMenuSeparator />
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
  );
}
