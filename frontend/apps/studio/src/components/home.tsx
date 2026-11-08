"use client";

import { useQuery } from "@tanstack/react-query";
import { ArrowRight, Bot, CheckCircle2, KeyRound, Package, Rocket, ScrollText, Settings2, Users } from "lucide-react";
import Link from "next/link";
import { useTranslations } from "next-intl";

import { useStudio } from "@/components/shell/studio-context";
import { IconTile, type Tone } from "@/components/visual/icon-tile";
import { ProgressRing } from "@/components/visual/progress-ring";
import { StatusBadge } from "@/components/visual/status-badge";
import { api } from "@/lib/api";
import { useTerm } from "@/lib/hooks";
import { cn } from "@/lib/utils";

interface ConfigObject {
  kind: string;
  deployments: Record<string, number>;
}

async function settled<T>(p: Promise<T>, fallback: T): Promise<T> {
  try {
    return await p;
  } catch {
    return fallback;
  }
}

const STEPS = [
  { key: "pack", href: "/settings/configuration?kind=domain_pack", icon: Package, tone: "teal" },
  { key: "agent", href: "/settings/configuration/agent/new", icon: Bot, tone: "violet" },
  { key: "deploy", href: "/settings/configuration?kind=agent", icon: Rocket, tone: "amber" },
  { key: "members", href: "/settings/members?invite=1", icon: Users, tone: "sky" },
  { key: "keys", href: "/settings/api-keys?create=1", icon: KeyRound, tone: "rose" },
] as const;

const TILES: { key: "invite" | "key" | "configure" | "audit"; href: string; icon: typeof Users; tone: Tone; title: string }[] = [
  { key: "invite", href: "/settings/members?invite=1", icon: Users, tone: "violet", title: "members.invite" },
  { key: "key", href: "/settings/api-keys?create=1", icon: KeyRound, tone: "amber", title: "apiKeys.create" },
  { key: "configure", href: "/settings/configuration", icon: Settings2, tone: "teal", title: "nav.configuration" },
  { key: "audit", href: "/settings/audit", icon: ScrollText, tone: "sky", title: "nav.audit" },
];

export function Home() {
  const t = useTranslations();
  const term = useTerm();
  const { user } = useStudio();
  const { data, isLoading } = useQuery({
    queryKey: ["home-checklist"],
    queryFn: async () => {
      const [objects, members, keys] = await Promise.all([
        settled(api<ConfigObject[]>("config/v1/objects"), []),
        settled(api<unknown[]>("identity/v1/members"), []),
        settled(api<unknown[]>("identity/v1/api-keys"), []),
      ]);
      const agents = objects.filter((o) => o.kind === "agent");
      return {
        pack: objects.some((o) => o.kind === "domain_pack"),
        agent: agents.length > 0,
        deploy: agents.some((a) => a.deployments.dev),
        members: members.length > 1,
        keys: keys.length > 0,
      };
    },
  });
  const done = STEPS.filter((s) => data?.[s.key]).length;
  const progress = t("home.progress", { done, total: STEPS.length });
  const firstName = (user.name ?? user.email ?? "").split(/[\s@]/)[0];

  return (
    <div className="space-y-8">
      {/* Hero */}
      <section className="nx-card nx-mesh nx-page relative overflow-hidden p-6 sm:p-8">
        <div className="nx-grid-pattern pointer-events-none absolute inset-0 opacity-40 [mask-image:linear-gradient(to_bottom,black,transparent)]" aria-hidden="true" />
        <div className="relative flex flex-col gap-6 sm:flex-row sm:items-center sm:justify-between">
          <div className="space-y-2">
            {firstName ? <p className="text-sm font-medium text-primary">{t("home.greeting", { name: firstName })}</p> : null}
            <h1 className="text-2xl font-semibold tracking-tight sm:text-3xl">{t("home.title")}</h1>
            <p className="max-w-xl text-muted-foreground">
              {t("home.subtitle", { knowledge: term("knowledge_source", "documentation").toLowerCase() })}
            </p>
          </div>
          <div className="flex items-center gap-4">
            {isLoading ? <div className="nx-shimmer size-[88px] rounded-full" /> : <ProgressRing value={done} total={STEPS.length} label={progress} />}
            <div className="space-y-1">
              <p className="text-sm font-semibold">{t("home.checklistTitle")}</p>
              <p className="text-sm text-muted-foreground" aria-live="polite">{isLoading ? "…" : progress}</p>
            </div>
          </div>
        </div>
      </section>

      {/* Quick actions */}
      <section aria-labelledby="quick-actions" className="space-y-3">
        <h2 id="quick-actions" className="text-sm font-semibold uppercase tracking-wide text-muted-foreground">{t("home.quickActions")}</h2>
        <ul className="nx-stagger grid grid-cols-2 gap-3 lg:grid-cols-4">
          {TILES.map((tile) => (
            <li key={tile.key}>
              <Link href={tile.href} className="nx-card nx-lift group flex h-full flex-col gap-2 p-3 outline-none focus-visible:ring-2 focus-visible:ring-ring sm:gap-3 sm:p-4">
                <IconTile icon={tile.icon} tone={tile.tone} />
                <span className="font-medium">{t(tile.title)}</span>
                <span className="hidden text-sm text-muted-foreground sm:block">{t(`home.tiles.${tile.key}`)}</span>
                <ArrowRight className="mt-auto size-4 text-muted-foreground transition-transform group-hover:translate-x-1 rtl:rotate-180 rtl:group-hover:-translate-x-1" aria-hidden="true" />
              </Link>
            </li>
          ))}
        </ul>
      </section>

      {/* Checklist */}
      <section aria-labelledby="setup-steps" className="space-y-3">
        <div className="flex items-end justify-between gap-4">
          <div>
            <h2 id="setup-steps" className="text-lg font-semibold">{t("home.checklistTitle")}</h2>
            <p className="text-sm text-muted-foreground">{done === STEPS.length ? t("home.allDone") : t("home.stepsHint")}</p>
          </div>
        </div>
        <ol className="nx-stagger grid gap-3">
          {STEPS.map((step, index) => {
            const complete = Boolean(data?.[step.key]);
            return (
              <li key={step.key} className={cn("nx-card flex items-center gap-4 p-4", complete && "bg-accent/30")}>
                <span className="w-5 text-center text-sm font-semibold tabular-nums text-muted-foreground" aria-hidden="true">{index + 1}</span>
                <IconTile icon={complete ? CheckCircle2 : step.icon} tone={complete ? "teal" : step.tone} size="sm" />
                <span className={cn("flex-1 font-medium", complete && "text-muted-foreground line-through decoration-1")}>{t(`home.steps.${step.key}`)}</span>
                {complete ? (
                  <StatusBadge tone="teal">{t("home.done")}</StatusBadge>
                ) : isLoading ? (
                  <span className="nx-shimmer h-8 w-16 rounded-md" />
                ) : (
                  <Link href={step.href} className="inline-flex items-center gap-1 rounded-md px-3 py-1.5 text-sm font-medium text-primary hover:bg-accent focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring">
                    {t("home.open")}
                    <span className="sr-only">: {t(`home.steps.${step.key}`)}</span>
                    <ArrowRight className="size-3.5 rtl:rotate-180" aria-hidden="true" />
                  </Link>
                )}
              </li>
            );
          })}
        </ol>
      </section>
    </div>
  );
}
