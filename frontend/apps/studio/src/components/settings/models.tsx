"use client";

import { useQueries } from "@tanstack/react-query";
import { ArrowRight, Cloud, Cpu, Lock, Server, ShieldCheck } from "lucide-react";
import Link from "next/link";
import { useTranslations } from "next-intl";
import { useState } from "react";

import { PageHeader } from "@/components/page-header";
import { Button } from "@/components/ui/button";
import { Label } from "@/components/ui/label";
import { Select, SelectContent, SelectItem, SelectTrigger, SelectValue } from "@/components/ui/select";
import { Skeleton } from "@/components/ui/skeleton";
import { StatusBadge } from "@/components/visual/status-badge";
import { api } from "@/lib/api";
import { type AgentSpec, dataFlow, type ProfileEntry, tradeoffs, type VersionDetail } from "@/lib/studio";
import { useModelProfiles, useObjects } from "@/lib/studio-hooks";

/** Models & data policy (ST-12, UX G7): the same picker everywhere, in plain language. */
export function ModelsPage() {
  const t = useTranslations("models");
  const profiles = useModelProfiles();
  const agents = useObjects("agent");
  const specs = useQueries({
    queries: (agents.data ?? []).map((a) => {
      const v = a.deployments.dev ?? a.versions.at(-1)?.version;
      return { queryKey: ["version", "agent", a.name, v], queryFn: () => api<VersionDetail>(`config/v1/objects/agent/${a.name}/versions/${v}`), staleTime: Infinity };
    }),
  });
  const usage = new Map<string, string[]>();
  specs.forEach((q, i) => {
    const s = q.data?.spec as AgentSpec | undefined;
    if (!s) return;
    const p = s.model_profile ?? "cloud-frontier";
    usage.set(p, [...(usage.get(p) ?? []), s.display_name ?? agents.data?.[i]?.name ?? ""]);
  });
  const list = profiles.data ?? [];
  const busiest = [...usage.entries()].sort((a, b) => b[1].length - a[1].length)[0]?.[0];
  const [selected, setSelected] = useState<string | null>(null);
  const focus = selected ?? busiest ?? list.find((p) => p.allowed)?.name ?? "";

  return (
    <div className="space-y-8">
      <PageHeader title={t("title")} description={t("subtitle")} icon={Cpu} tone="sky" />
      {profiles.isLoading ? <Skeleton className="h-64" /> : (
        <>
          <section aria-labelledby="flow" className="nx-card space-y-4 p-4">
            <div className="flex flex-wrap items-end justify-between gap-3">
              <div>
                <h2 id="flow" className="font-semibold">{t("flowTitle")}</h2>
                <p className="text-sm text-muted-foreground">{t("flowBody")}</p>
              </div>
              <div className="space-y-1">
                <Label htmlFor="flow-profile" className="text-xs text-muted-foreground">{t("profile")}</Label>
                <Select value={focus} onValueChange={setSelected}>
                  <SelectTrigger id="flow-profile" className="w-56"><SelectValue /></SelectTrigger>
                  <SelectContent>{list.map((p) => <SelectItem key={p.name} value={p.name}>{p.name}</SelectItem>)}</SelectContent>
                </Select>
              </div>
            </div>
            <ol className="space-y-2" data-testid="data-flow">
              {dataFlow(focus, list).map((row) => (
                <li key={row.level} className="grid grid-cols-[8rem_auto_1fr] items-center gap-3 rounded-lg border p-2 text-sm sm:grid-cols-[9rem_auto_10rem_1fr]">
                  <StatusBadge tone={row.level === "restricted" ? "rose" : row.level === "confidential" ? "amber" : "slate"}>{t(`levels.${row.level}`)}</StatusBadge>
                  <ArrowRight className="size-4 text-muted-foreground rtl:rotate-180" aria-hidden="true" />
                  <span className="font-medium">{row.profile}</span>
                  <span className="col-span-3 flex flex-wrap items-center gap-2 sm:col-span-1">
                    {row.location === "on_prem" ? <Server className="size-4" aria-hidden="true" /> : <Cloud className="size-4" aria-hidden="true" />}
                    {t(`locations.${row.location === "on_prem" || row.location === "cloud" ? row.location : "unknown"}`)} · {row.provider}
                    {!row.allowed ? <StatusBadge tone="rose">{t("blockedByPolicy")}</StatusBadge> : null}
                  </span>
                </li>
              ))}
            </ol>
            <p className="text-xs text-muted-foreground">{t("strictest")}</p>
          </section>

          <ul className="grid gap-4 md:grid-cols-2 xl:grid-cols-3" data-testid="profiles">
            {list.map((p) => <ProfileCard key={p.name} entry={p} usedBy={usage.get(p.name) ?? []} />)}
          </ul>
        </>
      )}
    </div>
  );
}

function ProfileCard({ entry, usedBy }: { entry: ProfileEntry; usedBy: string[] }) {
  const t = useTranslations("models");
  const p = entry.profile;
  const tr = tradeoffs(p);
  const builtin = entry.source?.startsWith("builtin") ?? false;
  return (
    <li className="nx-card flex flex-col gap-3 p-4">
      <div className="flex items-start justify-between gap-2">
        <div>
          <h2 className="font-semibold">{entry.name}</h2>
          <p className="text-xs text-muted-foreground">{builtin ? t("builtin") : t("yours")}</p>
        </div>
        {entry.allowed ? <StatusBadge tone="teal">{t("allowed")}</StatusBadge> : <StatusBadge tone="rose">{t("blocked")}</StatusBadge>}
      </div>
      {!entry.allowed && entry.reason ? <p className="text-sm text-destructive">{entry.reason}</p> : null}
      <dl className="grid grid-cols-3 gap-2 text-center text-xs">
        <div className="rounded-lg bg-muted/60 p-2"><dt className="text-muted-foreground">{t("dataLocation")}</dt><dd className="font-medium">{t(`locations.${tr.location === "on_prem" || tr.location === "cloud" ? tr.location : "unknown"}`)}</dd></div>
        <div className="rounded-lg bg-muted/60 p-2"><dt className="text-muted-foreground">{t("quality")}</dt><dd className="font-medium">{t(`qualities.${tr.quality}`)}</dd></div>
        <div className="rounded-lg bg-muted/60 p-2"><dt className="text-muted-foreground">{t("cost")}</dt><dd className="font-medium">{t(`costs.${tr.cost}`)}</dd></div>
      </dl>
      <ul className="space-y-1 text-sm">
        <li className="flex items-center gap-2"><Cpu className="size-4 text-muted-foreground" aria-hidden="true" />{p?.chat?.provider ?? "—"} · <span dir="ltr">{p?.chat?.model ?? "—"}</span></li>
        <li className="flex items-center gap-2"><ShieldCheck className="size-4 text-muted-foreground" aria-hidden="true" />{p?.redact_pii === false ? t("noRedaction") : t("redaction")}</li>
        <li className="flex items-center gap-2"><Lock className="size-4 text-muted-foreground" aria-hidden="true" />{t("noTraining")}</li>
        {p?.routing?.length ? <li className="text-muted-foreground">{t("routes", { count: p.routing.length })}</li> : null}
        {p?.fallback_profile ? <li className="text-muted-foreground">{t("fallback", { name: p.fallback_profile })}</li> : null}
        {p?.budgets?.monthly_usd ? <li className="text-muted-foreground">{t("budget", { amount: p.budgets.monthly_usd })}</li> : null}
      </ul>
      <p className="text-xs text-muted-foreground">{usedBy.length ? t("usedBy", { names: usedBy.join(", ") }) : t("unused")}</p>
      <div className="mt-auto">
        <Button asChild variant="outline" size="sm">
          <Link href={builtin ? "/settings/configuration/model_profile/new" : `/settings/configuration/model_profile/${entry.name}`}>{builtin ? t("customise") : t("edit")}</Link>
        </Button>
      </div>
    </li>
  );
}
