"use client";

import { useQuery } from "@tanstack/react-query";
import { CheckCircle2, Circle } from "lucide-react";
import Link from "next/link";
import { useTranslations } from "next-intl";

import { PageHeader } from "@/components/page-header";
import { Button } from "@/components/ui/button";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import { api } from "@/lib/api";
import { useTerm } from "@/lib/hooks";

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

export function Home() {
  const t = useTranslations("home");
  const term = useTerm();
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
  const steps = [
    { key: "pack", href: "/settings/configuration?kind=domain_pack" },
    { key: "agent", href: "/settings/configuration/agent/new" },
    { key: "deploy", href: "/settings/configuration?kind=agent" },
    { key: "members", href: "/settings/members?invite=1" },
    { key: "keys", href: "/settings/api-keys?create=1" },
  ] as const;
  const done = steps.filter((s) => data?.[s.key]).length;

  return (
    <div className="space-y-8">
      <PageHeader title={t("title")} description={t("subtitle", { knowledge: term("knowledge_source", "documentation").toLowerCase() })} />
      <Card>
        <CardHeader className="flex flex-row items-center justify-between">
          <CardTitle className="text-lg">{t("checklistTitle")}</CardTitle>
          <span className="text-sm text-muted-foreground" aria-live="polite">
            {isLoading ? "…" : t("progress", { done, total: steps.length })}
          </span>
        </CardHeader>
        <CardContent>
          <ol className="divide-y">
            {steps.map((step) => {
              const complete = Boolean(data?.[step.key]);
              return (
                <li key={step.key} className="flex items-center gap-3 py-3">
                  {complete ? (
                    <CheckCircle2 className="size-5 text-success" aria-hidden="true" />
                  ) : (
                    <Circle className="size-5 text-muted-foreground" aria-hidden="true" />
                  )}
                  <span className="flex-1">{t(`steps.${step.key}`)}</span>
                  <span className="sr-only">{complete ? t("done") : t("todo")}</span>
                  {!complete ? (
                    <Button asChild variant="outline" size="sm">
                      <Link href={step.href}>
                        {t("open")}
                        <span className="sr-only">: {t(`steps.${step.key}`)}</span>
                      </Link>
                    </Button>
                  ) : null}
                </li>
              );
            })}
          </ol>
        </CardContent>
      </Card>
    </div>
  );
}
