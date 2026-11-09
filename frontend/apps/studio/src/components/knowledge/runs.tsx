"use client";

import { CircleAlert, History } from "lucide-react";
import { useFormatter, useNow, useTranslations } from "next-intl";

import { Table, TableBody, TableCell, TableHead, TableHeader, TableRow } from "@/components/ui/table";
import { StatusBadge } from "@/components/visual/status-badge";
import { type Run, runIsActive, runProgress } from "@/lib/knowledge";

const RUN_TONE = { queued: "sky", running: "sky", completed: "teal", failed: "rose" } as const;

/** Live progress for running syncs, uploads and reindexes (polled; see knowledge-hooks). */
export function ActiveRuns({ runs, sourceName }: { runs: Run[]; sourceName: (id: string | null) => string }) {
  const t = useTranslations("knowledge.runs");
  const active = runs.filter(runIsActive);
  if (!active.length) return null;
  return (
    <div className="space-y-2" aria-live="polite" data-testid="active-runs">
      {active.map((run) => {
        const p = runProgress(run);
        const percent = Math.round(p.ratio * 100);
        return (
          <div key={run.id} className="nx-card space-y-2 p-4">
            <div className="flex items-center justify-between gap-3 text-sm">
              <span className="font-medium">{t(`kinds.${run.kind}`, { source: sourceName(run.source_id) })}</span>
              <span className="text-muted-foreground tabular-nums">
                {run.discovered ? t("progress", { done: p.done, total: p.total }) : t("discovering")}
              </span>
            </div>
            <div
              className="h-2 overflow-hidden rounded-full bg-muted"
              role="progressbar"
              aria-valuemin={0}
              aria-valuemax={100}
              aria-valuenow={percent}
              aria-label={t(`kinds.${run.kind}`, { source: sourceName(run.source_id) })}
            >
              <div className="h-full rounded-full bg-primary transition-[width] duration-500 motion-reduce:transition-none" style={{ width: `${Math.max(percent, run.discovered ? 2 : 0)}%` }} />
            </div>
            <Counters run={run} />
          </div>
        );
      })}
    </div>
  );
}

function Counters({ run }: { run: Run }) {
  const t = useTranslations("knowledge.runs");
  const items = (["processed", "unchanged", "failed", "quarantined", "deleted"] as const).filter((k) => run[k] > 0);
  if (!items.length) return null;
  return (
    <p className="flex flex-wrap gap-x-3 text-xs text-muted-foreground">
      {items.map((k) => (
        <span key={k}>{t(`counters.${k}`, { count: run[k] })}</span>
      ))}
    </p>
  );
}

export function RunHistory({ runs, sourceName }: { runs: Run[]; sourceName: (id: string | null) => string }) {
  const t = useTranslations("knowledge.runs");
  const tc = useTranslations("common");
  const format = useFormatter();
  const now = useNow({ updateInterval: 30_000 });
  if (!runs.length) {
    return (
      <p className="flex items-center justify-center gap-2 rounded-xl border border-dashed p-8 text-sm text-muted-foreground">
        <History className="size-4" aria-hidden="true" />
        {t("none")}
      </p>
    );
  }
  return (
    <div className="nx-card overflow-x-auto">
      <Table>
        <TableHeader>
          <TableRow>
            <TableHead>{t("run")}</TableHead>
            <TableHead>{tc("status")}</TableHead>
            <TableHead>{t("result")}</TableHead>
            <TableHead className="hidden md:table-cell">{t("when")}</TableHead>
          </TableRow>
        </TableHeader>
        <TableBody>
          {runs.map((run) => (
            <TableRow key={run.id}>
              <TableCell className="font-medium">{t(`kinds.${run.kind}`, { source: sourceName(run.source_id) })}</TableCell>
              <TableCell>
                <StatusBadge tone={RUN_TONE[run.status]} live={runIsActive(run)}>{t(`statuses.${run.status}`)}</StatusBadge>
              </TableCell>
              <TableCell className="text-sm">
                <Counters run={run} />
                {run.error ? (
                  <p className="mt-1 flex items-start gap-1.5 text-xs text-destructive">
                    <CircleAlert className="mt-0.5 size-3.5 shrink-0" aria-hidden="true" />
                    <span className="break-words">{run.error}</span>
                  </p>
                ) : null}
                {run.truncated ? <p className="mt-1 text-xs text-muted-foreground">{t("truncated")}</p> : null}
                {run.incomplete ? <p className="mt-1 text-xs text-amber-800 dark:text-amber-200" data-testid="run-incomplete">{t("incomplete")}</p> : null}
                {run.warnings.length ? <p className="mt-1 text-xs text-muted-foreground">{t("warnings", { count: run.warnings.length })}</p> : null}
              </TableCell>
              <TableCell className="hidden text-muted-foreground md:table-cell">{format.relativeTime(new Date(run.created_at), now)}</TableCell>
            </TableRow>
          ))}
        </TableBody>
      </Table>
    </div>
  );
}
