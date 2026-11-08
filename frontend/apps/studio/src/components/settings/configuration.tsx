"use client";

import { useQuery } from "@tanstack/react-query";
import { Archive, Bot, Cpu, KeyRound, type LucideIcon, Package, Plus, Radio, Search, Settings2, ShieldCheck, Wrench } from "lucide-react";
import Link from "next/link";
import { useRouter, useSearchParams } from "next/navigation";
import { useTranslations } from "next-intl";

import { EmptyState } from "@/components/empty-state";
import { PageHeader } from "@/components/page-header";
import type { JsonSchema } from "@/components/schema-form/schema";
import { Button } from "@/components/ui/button";
import { Skeleton } from "@/components/ui/skeleton";
import { api } from "@/lib/api";
import { cn } from "@/lib/utils";
import { IconTile, type Tone } from "@/components/visual/icon-tile";
import { StatusBadge } from "@/components/visual/status-badge";

export const KIND_VISUAL: Record<string, { icon: LucideIcon; tone: Tone }> = {
  domain_pack: { icon: Package, tone: "teal" },
  agent: { icon: Bot, tone: "violet" },
  model_profile: { icon: Cpu, tone: "sky" },
  retrieval_profile: { icon: Search, tone: "amber" },
  tool: { icon: Wrench, tone: "rose" },
  channel: { icon: Radio, tone: "sky" },
  tenant_settings: { icon: Settings2, tone: "navy" },
  security_floors: { icon: ShieldCheck, tone: "rose" },
  retention_profile: { icon: Archive, tone: "amber" },
};

export function kindVisual(kind: string): { icon: LucideIcon; tone: Tone } {
  return KIND_VISUAL[kind] ?? { icon: KeyRound, tone: "slate" };
}

export interface KindInfo {
  kind: string;
  title: string;
  description: string;
  schema: JsonSchema;
}

export interface ObjectSummary {
  kind: string;
  name: string;
  description: string;
  versions: { version: number; status: "draft" | "published" }[];
  deployments: Record<string, number>;
}

export function useKinds() {
  return useQuery({ queryKey: ["kinds"], queryFn: () => api<KindInfo[]>("config/v1/kinds"), staleTime: 10 * 60_000 });
}

export function ConfigurationPage() {
  const t = useTranslations("config");
  const params = useSearchParams();
  const router = useRouter();
  const kinds = useKinds();
  const kind = params.get("kind") ?? kinds.data?.[0]?.kind ?? "";
  const info = kinds.data?.find((k) => k.kind === kind);
  const objects = useQuery({
    queryKey: ["objects", kind],
    queryFn: () => api<ObjectSummary[]>(`config/v1/objects?kind=${kind}`),
    enabled: !!kind,
  });

  return (
    <div className="space-y-8">
      <PageHeader title={t("title")} description={t("subtitle")} icon={Settings2} tone="teal" />
      <div className="grid gap-6 md:grid-cols-[14rem_1fr]">
        <nav aria-label={t("kinds")}>
          <h2 className="mb-2 text-sm font-semibold text-muted-foreground">{t("kinds")}</h2>
          {kinds.isLoading ? <Skeleton className="h-64" /> : (
            <ul className="flex gap-1 overflow-x-auto pb-2 md:flex-col md:overflow-visible md:pb-0">
              {kinds.data?.map((k) => (
                <li key={k.kind} className="shrink-0">
                  <button
                    type="button"
                    onClick={() => router.replace(`/settings/configuration?kind=${k.kind}`)}
                    aria-current={k.kind === kind ? "true" : undefined}
                    className={cn(
                      "flex w-full items-center gap-2.5 rounded-lg px-2.5 py-2 text-start text-sm transition-colors hover:bg-card focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring",
                      k.kind === kind && "bg-card font-medium shadow-sm ring-1 ring-border",
                    )}
                  >
                    <IconTile icon={kindVisual(k.kind).icon} tone={kindVisual(k.kind).tone} size="sm" className="size-7" />
                    <span className="whitespace-nowrap">{k.title}</span>
                  </button>
                </li>
              ))}
            </ul>
          )}
        </nav>
        <section aria-labelledby="objects-heading" className="space-y-4">
          <div className="flex items-start justify-between gap-4">
            <div className="flex items-start gap-3">
            {info ? <IconTile icon={kindVisual(info.kind).icon} tone={kindVisual(info.kind).tone} /> : null}
            <div>
              <h2 id="objects-heading" className="text-lg font-semibold">{info?.title}</h2>
              {info?.description ? <p className="text-sm text-muted-foreground">{info.description}</p> : null}
            </div>
            </div>
            {kind ? (
              <Button asChild size="sm">
                <Link href={`/settings/configuration/${kind}/new`}>
                  <Plus className="size-4" aria-hidden="true" />
                  {t("newObject", { kind: info?.title ?? kind })}
                </Link>
              </Button>
            ) : null}
          </div>
          {objects.isLoading ? <Skeleton className="h-24" /> : !objects.data?.length ? (
            <EmptyState
              icon={kindVisual(kind).icon}
              tone={kindVisual(kind).tone}
              title={t("noObjects")}
              body={info?.description}
              action={
                <Button asChild size="sm">
                  <Link href={`/settings/configuration/${kind}/new`}>
                    <Plus className="size-4" aria-hidden="true" />
                    {t("newObject", { kind: info?.title ?? kind })}
                  </Link>
                </Button>
              }
            />
          ) : (
            <ul className="nx-stagger grid gap-2">
              {objects.data.map((o) => {
                const latest = o.versions.at(-1);
                const live = Object.entries(o.deployments);
                return (
                  <li key={o.name}>
                    <Link href={`/settings/configuration/${o.kind}/${o.name}`} className="nx-card nx-lift flex flex-wrap items-center gap-3 px-4 py-3 outline-none focus-visible:ring-2 focus-visible:ring-ring">
                      <span className="flex-1 font-medium" dir="ltr">{o.name}</span>
                      {latest ? <StatusBadge tone={latest.status === "published" ? "navy" : "amber"}>v{latest.version} · {t(`statuses.${latest.status}`)}</StatusBadge> : null}
                      {live.length ? live.map(([env, v]) => <StatusBadge key={env} tone="teal" live>{env} v{v}</StatusBadge>) : (
                        <span className="text-sm text-muted-foreground">{t("notDeployed")}</span>
                      )}
                    </Link>
                  </li>
                );
              })}
            </ul>
          )}
        </section>
      </div>
    </div>
  );
}
