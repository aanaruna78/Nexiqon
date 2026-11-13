"use client";

import { useMutation, useQuery } from "@tanstack/react-query";
import { CircleAlert, EyeOff, Search, UsersRound } from "lucide-react";
import { useTranslations } from "next-intl";
import { type FormEvent, useState } from "react";

import { Alert, AlertDescription, AlertTitle } from "@/components/ui/alert";
import { Button } from "@/components/ui/button";
import { Checkbox } from "@/components/ui/checkbox";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import { StatusBadge } from "@/components/visual/status-badge";
import { api, ApiError } from "@/lib/api";
import type { SearchResponse } from "@/lib/knowledge";
import { useCollections } from "@/lib/knowledge-hooks";

type Audience = "user" | "widget";

/** "View as" (ST-08, UX G5): exactly what someone in these groups, or a website visitor, can retrieve. */
export function ViewAs({ collections: names, retrievalProfile, modelProfile }: { collections: string[]; retrievalProfile?: string; modelProfile?: string }) {
  const t = useTranslations("viewAs");
  const all = useCollections();
  const groups = useQuery({
    queryKey: ["groups"],
    queryFn: () => api<{ id: string; name: string; description: string }[]>("identity/v1/groups"),
  });
  const [audience, setAudience] = useState<Audience>("user");
  const [chosen, setChosen] = useState<string[]>([]);
  const [query, setQuery] = useState("");
  const ids = (all.data ?? []).filter((c) => names.includes(c.name)).map((c) => c.id);

  const run = useMutation({
    mutationFn: () =>
      api<SearchResponse & { hidden: number | null }>("retrieval/v1/search", {
        method: "POST",
        json: {
          query,
          collection_ids: ids,
          retrieval_profile: retrievalProfile,
          model_profile: modelProfile,
          view_as: { groups: chosen, actor_type: audience },
        },
      }),
  });

  function submit(e: FormEvent) {
    e.preventDefault();
    if (query.trim() && ids.length) run.mutate();
  }

  if (!names.length) return <p className="text-sm text-muted-foreground">{t("noKnowledge")}</p>;
  const result = run.data;
  return (
    <div className="grid gap-6 lg:grid-cols-[18rem_1fr]">
      <form onSubmit={submit} className="nx-card h-fit space-y-5 p-4" aria-label={t("who")}>
        <fieldset className="space-y-2">
          <legend className="text-sm font-medium">{t("who")}</legend>
          <div role="radiogroup" className="grid gap-2">
            {(["user", "widget"] as const).map((a) => (
              <label key={a} className="flex items-center gap-2 text-sm">
                <input type="radio" name="audience" value={a} checked={audience === a} onChange={() => setAudience(a)} className="accent-[var(--primary)]" />
                {t(`audiences.${a}`)}
              </label>
            ))}
          </div>
        </fieldset>
        <fieldset className="space-y-2">
          <legend className="flex items-center gap-2 text-sm font-medium">
            <UsersRound className="size-4" aria-hidden="true" />
            {t("groups")}
          </legend>
          {groups.data?.length ? (
            groups.data.map((g) => (
              <div key={g.id} className="flex items-center gap-2">
                <Checkbox id={`va-${g.id}`} checked={chosen.includes(g.name)} onCheckedChange={(on) => setChosen(on ? [...chosen, g.name] : chosen.filter((x) => x !== g.name))} />
                <Label htmlFor={`va-${g.id}`} className="font-normal">{g.name}</Label>
              </div>
            ))
          ) : (
            <p className="text-xs text-muted-foreground">{t("noGroups")}</p>
          )}
          <p className="text-xs text-muted-foreground">{t("groupsHelp")}</p>
        </fieldset>
        <div className="space-y-2">
          <Label htmlFor="va-query">{t("question")}</Label>
          <Input id="va-query" value={query} onChange={(e) => setQuery(e.target.value)} placeholder={t("placeholder")} data-testid="view-as-query" />
        </div>
        <Button type="submit" className="w-full" disabled={run.isPending || !query.trim() || !ids.length} data-testid="view-as-run">
          <Search className="size-4" aria-hidden="true" />
          {t("preview")}
        </Button>
      </form>
      <div className="min-w-0 space-y-4" aria-live="polite">
        {run.error ? (
          <Alert variant="destructive">
            <CircleAlert className="size-4" aria-hidden="true" />
            <AlertTitle>{t("failed")}</AlertTitle>
            <AlertDescription>{run.error instanceof ApiError ? run.error.problem.detail : null}</AlertDescription>
          </Alert>
        ) : null}
        {result ? (
          <>
            <div className="nx-card flex flex-wrap items-center gap-3 p-4" data-testid="view-as-summary">
              <StatusBadge tone="teal">{t("visible", { count: result.passages.length })}</StatusBadge>
              {result.hidden ? (
                <span className="flex items-center gap-1.5 text-sm">
                  <EyeOff className="size-4 text-amber-600" aria-hidden="true" />
                  {t("hidden", { count: result.hidden })}
                </span>
              ) : (
                <span className="text-sm text-muted-foreground">{t("nothingHidden")}</span>
              )}
            </div>
            {result.passages.length ? (
              <ol className="space-y-2">
                {result.passages.map((p) => (
                  <li key={p.id} className="nx-card space-y-1 p-3">
                    <div className="flex flex-wrap items-center justify-between gap-2">
                      <span className="text-sm font-medium">{p.citation}</span>
                      <StatusBadge tone="slate">{p.classification}</StatusBadge>
                    </div>
                    <p className="line-clamp-2 text-sm text-muted-foreground">{p.text}</p>
                  </li>
                ))}
              </ol>
            ) : (
              <p className="text-sm text-muted-foreground">{t("none")}</p>
            )}
          </>
        ) : (
          <p className="text-sm text-muted-foreground">{t("intro")}</p>
        )}
      </div>
    </div>
  );
}
