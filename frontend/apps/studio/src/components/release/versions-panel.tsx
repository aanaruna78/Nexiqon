"use client";

import { GitCompareArrows, History, Rocket, RotateCcw, Undo2 } from "lucide-react";
import { useFormatter, useTranslations } from "next-intl";
import { useState } from "react";
import { toast } from "sonner";

import { Alert, AlertDescription, AlertTitle } from "@/components/ui/alert";
import { Button } from "@/components/ui/button";
import { Label } from "@/components/ui/label";
import { Select, SelectContent, SelectItem, SelectTrigger, SelectValue } from "@/components/ui/select";
import { Skeleton } from "@/components/ui/skeleton";
import { StatusBadge } from "@/components/visual/status-badge";
import { ApiError } from "@/lib/api";
import { useErrorToast } from "@/lib/hooks";
import { type Change, type ConfigObject, pathWords, preview, releaseState } from "@/lib/studio";
import { useDiff, useHistory, useRelease } from "@/lib/studio-hooks";

/** Versions, a readable diff against what is live, publish + deploy, and one-click rollback (ST-06). */
export function VersionsPanel({ kind, object }: { kind: string; object: ConfigObject }) {
  const t = useTranslations("release");
  const format = useFormatter();
  const onError = useErrorToast();
  const state = releaseState(object);
  const { publish, deploy } = useRelease(kind, object.name);
  const history = useHistory(kind, object.name);
  const versions = [...object.versions].reverse();
  const [compareTo, setCompareTo] = useState<number | undefined>(state.latest?.version);
  const base = state.live ?? versions.find((v) => v.status === "published" && v.version !== compareTo)?.version;
  const diff = useDiff(kind, object.name, base, compareTo);
  const [blocked, setBlocked] = useState<string | null>(null);

  async function release(version: number) {
    setBlocked(null);
    try {
      if (object.versions.find((v) => v.version === version)?.status === "draft") await publish.mutateAsync(version);
      await deploy.mutateAsync({ version, reason: state.live ? `from v${state.live}` : "first release" });
      toast.success(t("released", { version }));
    } catch (error) {
      if (error instanceof ApiError && error.problem.code === "security_floor_violation") setBlocked(error.problem.detail ?? "");
      else onError(error);
    }
  }

  async function rollback() {
    const target = state.previousPublished;
    if (!target) return;
    try {
      await deploy.mutateAsync({ version: target.version, reason: `rollback from v${state.live}` });
      toast.success(t("rolledBack", { version: target.version }));
    } catch (error) {
      onError(error);
    }
  }

  const busy = publish.isPending || deploy.isPending;
  const candidate = compareTo ?? state.latest?.version;
  return (
    <div className="space-y-6">
      <div className="nx-card flex flex-wrap items-center justify-between gap-4 p-4">
        <div className="space-y-1">
          <p className="text-sm text-muted-foreground">{t("liveNow")}</p>
          <p className="text-lg font-semibold" data-testid="live-version">
            {state.live ? t("version", { version: state.live }) : t("notLive")}
          </p>
        </div>
        <div className="flex flex-wrap gap-2">
          {state.previousPublished ? (
            <Button variant="outline" onClick={rollback} disabled={busy} data-testid="rollback">
              <Undo2 className="size-4" aria-hidden="true" />
              {t("rollbackTo", { version: state.previousPublished.version })}
            </Button>
          ) : null}
          {candidate && candidate !== state.live ? (
            <Button onClick={() => release(candidate)} disabled={busy} data-testid="release">
              <Rocket className="size-4" aria-hidden="true" />
              {t("release", { version: candidate })}
            </Button>
          ) : null}
        </div>
      </div>

      {blocked !== null ? (
        <Alert variant="destructive">
          <AlertTitle>{t("blocked")}</AlertTitle>
          <AlertDescription>{blocked}</AlertDescription>
        </Alert>
      ) : null}

      <section aria-labelledby="diff-title" className="nx-card space-y-3 p-4">
        <div className="flex flex-wrap items-end justify-between gap-3">
          <h2 id="diff-title" className="flex items-center gap-2 font-semibold">
            <GitCompareArrows className="size-4" aria-hidden="true" />
            {base ? t("changesSince", { version: base }) : t("changes")}
          </h2>
          <div className="space-y-1">
            <Label htmlFor="compare" className="text-xs text-muted-foreground">{t("compare")}</Label>
            <Select value={compareTo ? String(compareTo) : undefined} onValueChange={(v) => setCompareTo(Number(v))}>
              <SelectTrigger id="compare" className="w-44">
                <SelectValue />
              </SelectTrigger>
              <SelectContent>
                {versions.map((v) => (
                  <SelectItem key={v.version} value={String(v.version)}>
                    {t("versionStatus", { version: v.version, status: t(`status.${v.status}`) })}
                  </SelectItem>
                ))}
              </SelectContent>
            </Select>
          </div>
        </div>
        {!base || base === compareTo ? (
          <p className="text-sm text-muted-foreground">{t("nothingToCompare")}</p>
        ) : diff.isLoading ? (
          <Skeleton className="h-24" />
        ) : (
          <DiffList changes={diff.data?.changes ?? []} />
        )}
      </section>

      <section aria-labelledby="versions-title" className="space-y-3">
        <h2 id="versions-title" className="font-semibold">{t("versions")}</h2>
        <ul className="nx-card divide-y">
          {versions.map((v) => (
            <li key={v.version} className="flex flex-wrap items-center justify-between gap-3 p-3">
              <div className="flex items-center gap-3">
                <span className="font-medium tabular-nums">v{v.version}</span>
                <StatusBadge tone={v.status === "published" ? "teal" : "amber"}>{t(`status.${v.status}`)}</StatusBadge>
                {v.version === state.live ? <StatusBadge tone="sky" live>{t("live")}</StatusBadge> : null}
              </div>
              <span className="text-xs text-muted-foreground">
                {[v.notes, v.created_by, v.created_at ? format.relativeTime(new Date(v.created_at)) : null].filter(Boolean).join(" · ")}
              </span>
            </li>
          ))}
        </ul>
      </section>

      <section aria-labelledby="history-title" className="space-y-3">
        <h2 id="history-title" className="flex items-center gap-2 font-semibold">
          <History className="size-4" aria-hidden="true" />
          {t("history")}
        </h2>
        {history.data?.length ? (
          <ol className="space-y-2 text-sm">
            {history.data.map((h, i) => (
              <li key={i} className="flex flex-wrap items-center gap-2">
                <RotateCcw className="size-3.5 text-muted-foreground" aria-hidden="true" />
                <span>{t("deployed", { from: h.from_version ?? "—", to: h.to_version, environment: h.environment })}</span>
                <span className="text-muted-foreground">{[h.reason, h.actor, format.relativeTime(new Date(h.at))].filter(Boolean).join(" · ")}</span>
              </li>
            ))}
          </ol>
        ) : (
          <p className="text-sm text-muted-foreground">{t("noHistory")}</p>
        )}
      </section>
    </div>
  );
}

export function DiffList({ changes }: { changes: Change[] }) {
  const t = useTranslations("release");
  if (!changes.length) return <p className="text-sm text-muted-foreground">{t("noChanges")}</p>;
  return (
    <ul className="space-y-2 text-sm" data-testid="diff">
      {changes.map((c, i) => (
        <li key={i} className="flex flex-wrap items-baseline gap-2">
          <StatusBadge tone={c.op === "add" ? "teal" : c.op === "remove" ? "rose" : "amber"}>{t(`ops.${c.op}`)}</StatusBadge>
          <span className="font-medium">{pathWords(c.path).join(" › ")}</span>
          {c.op !== "add" ? <del className="text-muted-foreground">{preview(c.old)}</del> : null}
          {c.op !== "remove" ? <ins className="no-underline">{preview(c.new)}</ins> : null}
        </li>
      ))}
    </ul>
  );
}
