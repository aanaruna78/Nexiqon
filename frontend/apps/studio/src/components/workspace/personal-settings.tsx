"use client";

import { Check, Languages, LogOut, Monitor, Moon, Palette, Sun, UserRound, Building2 } from "lucide-react";
import { useLocale, useTranslations } from "next-intl";
import { useTheme } from "next-themes";
import { type ReactNode, useSyncExternalStore } from "react";

const subscribeNothing = () => () => {};

import type { StudioMembership } from "@/app/api/session/route";
import { useShellActions } from "@/components/shell/actions";
import { Button } from "@/components/ui/button";
import { Select, SelectContent, SelectItem, SelectTrigger, SelectValue } from "@/components/ui/select";
import { Avatar } from "@/components/visual/avatar";
import { IconTile } from "@/components/visual/icon-tile";
import { type Locale, localeNames, locales } from "@/i18n/config";
import type { SessionUser } from "@/lib/server/session";
import { cn } from "@/lib/utils";

function Section({ icon, title, description, children }: { icon: typeof Palette; title: string; description: string; children: ReactNode }) {
  return (
    <section className="nx-card grid gap-5 p-5 sm:grid-cols-[minmax(0,15rem)_1fr] sm:p-6" aria-labelledby={`s-${title}`}>
      <div className="flex items-start gap-3">
        <IconTile icon={icon} tone="teal" />
        <div>
          <h2 id={`s-${title}`} className="font-semibold">{title}</h2>
          <p className="mt-1 text-sm text-muted-foreground">{description}</p>
        </div>
      </div>
      <div className="min-w-0">{children}</div>
    </section>
  );
}

/** Your own settings. Everything about the organization (members, keys, policies) is in Admin. */
export function PersonalSettings({ user, memberships, active }: { user: SessionUser; memberships: StudioMembership[]; active: StudioMembership }) {
  const t = useTranslations("personal");
  const tr = useTranslations("members.roles");
  const ts = useTranslations("shell");
  const locale = useLocale();
  const { theme, setTheme } = useTheme();
  const actions = useShellActions();
  // The theme is only known in the browser; render no selection on the server.
  const mounted = useSyncExternalStore(subscribeNothing, () => true, () => false);
  const current = mounted ? (theme ?? "system") : null;

  const themes = [
    { value: "light", icon: Sun, label: ts("light") },
    { value: "dark", icon: Moon, label: ts("dark") },
    { value: "system", icon: Monitor, label: ts("system") },
  ];

  return (
    <main id="main" tabIndex={-1} className="min-h-0 flex-1 overflow-y-auto outline-none">
      <div className="nx-page mx-auto max-w-4xl space-y-6 px-4 py-8 sm:px-6 sm:py-10">
        <header className="space-y-1">
          <h1 className="text-2xl font-semibold tracking-tight">{t("title")}</h1>
          <p className="text-muted-foreground">{t("subtitle")}</p>
        </header>

        <Section icon={UserRound} title={t("profile")} description={t("profileHelp")}>
          <div className="flex items-center gap-4">
            <Avatar name={user.name || user.email || "?"} className="size-14 text-lg" />
            <dl className="grid gap-1 text-sm">
              <div className="flex gap-2"><dt className="sr-only">{t("name")}</dt><dd className="text-base font-semibold">{user.name ?? user.email}</dd></div>
              {user.email ? <div className="flex gap-2"><dt className="text-muted-foreground">{t("email")}</dt><dd>{user.email}</dd></div> : null}
            </dl>
          </div>
        </Section>

        <Section icon={Palette} title={t("appearance")} description={t("appearanceHelp")}>
          <div role="radiogroup" aria-label={ts("theme")} className="grid grid-cols-3 gap-3">
            {themes.map(({ value, icon: Icon, label }) => {
              const selected = current === value;
              return (
                <button
                  key={value}
                  type="button"
                  role="radio"
                  aria-checked={selected}
                  onClick={() => setTheme(value)}
                  className={cn(
                    "relative flex flex-col items-center gap-2 rounded-xl border bg-card px-3 py-4 text-sm font-medium outline-none transition-colors hover:border-primary/50 focus-visible:ring-2 focus-visible:ring-ring",
                    selected && "border-primary ring-1 ring-primary",
                  )}
                  data-testid={`theme-${value}`}
                >
                  <Icon className="size-5" aria-hidden="true" />
                  {label}
                  {selected ? <Check className="absolute end-2 top-2 size-4 text-primary" aria-hidden="true" /> : null}
                </button>
              );
            })}
          </div>
        </Section>

        <Section icon={Languages} title={t("language")} description={t("languageHelp")}>
          <Select value={locale} onValueChange={(v) => actions.setLocale(v as Locale)}>
            <SelectTrigger className="w-full max-w-xs" aria-label={ts("language")} data-testid="language-select">
              <SelectValue />
            </SelectTrigger>
            <SelectContent>
              {locales.map((l) => (
                <SelectItem key={l} value={l} lang={l === "en-XA" ? "en" : l}>{localeNames[l]}</SelectItem>
              ))}
            </SelectContent>
          </Select>
        </Section>

        <Section icon={Building2} title={t("organizations")} description={t("organizationsHelp")}>
          <ul className="divide-y rounded-xl border">
            {memberships.map((m) => (
              <li key={m.tenant_id} className="flex items-center gap-3 px-4 py-3 text-sm">
                <span className="flex-1 truncate font-medium">{m.tenant_name}</span>
                <span className="text-muted-foreground">{tr(m.role)}</span>
                {m.tenant_id === active.tenant_id ? (
                  <span className="rounded-full bg-primary/10 px-2 py-0.5 text-xs font-medium text-primary">{t("current")}</span>
                ) : (
                  <Button size="sm" variant="outline" onClick={() => actions.switchOrg(m.tenant_slug, m.tenant_name)}>{t("switch")}</Button>
                )}
              </li>
            ))}
          </ul>
        </Section>

        <Section icon={LogOut} title={t("session")} description={t("sessionHelp")}>
          <Button variant="outline" onClick={() => actions.signOut()} className="gap-2">
            <LogOut className="size-4" aria-hidden="true" />
            {ts("signOut")}
          </Button>
        </Section>
      </div>
    </main>
  );
}
