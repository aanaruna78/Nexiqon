"use client";

import { useQuery } from "@tanstack/react-query";
import { Plus, Settings2 } from "lucide-react";
import Link from "next/link";
import { useRouter, useSearchParams } from "next/navigation";
import { useTranslations } from "next-intl";

import { EmptyState } from "@/components/empty-state";
import { PageHeader } from "@/components/page-header";
import type { JsonSchema } from "@/components/schema-form/schema";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { Skeleton } from "@/components/ui/skeleton";
import { api } from "@/lib/api";
import { cn } from "@/lib/utils";

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
      <PageHeader title={t("title")} description={t("subtitle")} />
      <div className="grid gap-6 md:grid-cols-[14rem_1fr]">
        <nav aria-label={t("kinds")}>
          <h2 className="mb-2 text-sm font-semibold text-muted-foreground">{t("kinds")}</h2>
          {kinds.isLoading ? <Skeleton className="h-64" /> : (
            <ul className="space-y-1">
              {kinds.data?.map((k) => (
                <li key={k.kind}>
                  <button
                    type="button"
                    onClick={() => router.replace(`/settings/configuration?kind=${k.kind}`)}
                    aria-current={k.kind === kind ? "true" : undefined}
                    className={cn(
                      "w-full rounded-md px-3 py-2 text-start text-sm hover:bg-muted focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring",
                      k.kind === kind && "bg-accent font-medium text-accent-foreground",
                    )}
                  >
                    {k.title}
                  </button>
                </li>
              ))}
            </ul>
          )}
        </nav>
        <section aria-labelledby="objects-heading" className="space-y-4">
          <div className="flex items-start justify-between gap-4">
            <div>
              <h2 id="objects-heading" className="text-lg font-semibold">{info?.title}</h2>
              {info?.description ? <p className="text-sm text-muted-foreground">{info.description}</p> : null}
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
            <EmptyState icon={Settings2} title={t("noObjects")} />
          ) : (
            <ul className="divide-y rounded-lg border">
              {objects.data.map((o) => {
                const latest = o.versions.at(-1);
                const live = Object.entries(o.deployments);
                return (
                  <li key={o.name}>
                    <Link href={`/settings/configuration/${o.kind}/${o.name}`} className="flex flex-wrap items-center gap-3 px-4 py-3 hover:bg-muted focus-visible:bg-muted focus-visible:outline-none">
                      <span className="flex-1 font-medium" dir="ltr">{o.name}</span>
                      {latest ? <Badge variant="outline">v{latest.version} · {t(`statuses.${latest.status}`)}</Badge> : null}
                      {live.length ? live.map(([env, v]) => <Badge key={env} variant="secondary">{env} v{v}</Badge>) : (
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
