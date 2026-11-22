"use client";

import { useQuery } from "@tanstack/react-query";
import { ClipboardCheck, ListChecks, Package, Plus } from "lucide-react";
import Link from "next/link";
import { useRouter } from "next/navigation";
import { useFormatter, useTranslations } from "next-intl";
import { type FormEvent, useState } from "react";

import { EmptyState } from "@/components/empty-state";
import { PageHeader } from "@/components/page-header";
import { Button } from "@/components/ui/button";
import { Dialog, DialogContent, DialogDescription, DialogFooter, DialogHeader, DialogTitle } from "@/components/ui/dialog";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import { Select, SelectContent, SelectItem, SelectTrigger, SelectValue } from "@/components/ui/select";
import { Skeleton } from "@/components/ui/skeleton";
import { Textarea } from "@/components/ui/textarea";
import { IconTile } from "@/components/visual/icon-tile";
import { StatusBadge } from "@/components/visual/status-badge";
import { api } from "@/lib/api";
import { type EvalRun, passTone, percent, type TestSet } from "@/lib/evaluation";
import { useEvalRuns, useEvaluationActions, useTestSets } from "@/lib/evaluation-hooks";
import { useErrorToast } from "@/lib/hooks";
import { NAME_PATTERN, slugify } from "@/lib/studio";
import { useObjects } from "@/lib/studio-hooks";

import { RunStatus } from "./run-status";

/** Evaluations (ST-17): test sets, and how each assistant version scored on them. */
export function EvaluationsPage() {
  const t = useTranslations("evaluations");
  const sets = useTestSets();
  const runs = useEvalRuns();
  const [open, setOpen] = useState(false);
  const latest = new Map<string, EvalRun>();
  for (const r of runs.data ?? []) if (r.status === "completed" && !latest.has(r.test_set_id)) latest.set(r.test_set_id, r);

  return (
    <div className="space-y-8">
      <PageHeader
        title={t("title")}
        description={t("subtitle")}
        icon={ClipboardCheck}
        tone="amber"
        actions={
          <Button onClick={() => setOpen(true)} data-testid="new-test-set">
            <Plus className="size-4" aria-hidden="true" />
            {t("newSet")}
          </Button>
        }
      />
      <NewSetDialog open={open} onOpenChange={setOpen} />
      {sets.isLoading ? (
        <div className="grid gap-4 sm:grid-cols-2 xl:grid-cols-3">{[0, 1, 2].map((i) => <Skeleton key={i} className="h-36" />)}</div>
      ) : !sets.data?.length ? (
        <EmptyState
          icon={ListChecks}
          tone="amber"
          title={t("emptyTitle")}
          body={t("emptyBody")}
          action={
            <Button onClick={() => setOpen(true)}>
              <Plus className="size-4" aria-hidden="true" />
              {t("newSet")}
            </Button>
          }
        />
      ) : (
        <ul className="nx-stagger grid gap-4 sm:grid-cols-2 xl:grid-cols-3" aria-label={t("sets")}>
          {sets.data.map((s) => (
            <li key={s.id}>
              <SetCard set={s} run={latest.get(s.id)} />
            </li>
          ))}
        </ul>
      )}
      {runs.data?.length ? (
        <section aria-labelledby="recent-runs" className="space-y-3">
          <h2 id="recent-runs" className="font-semibold">{t("recentRuns")}</h2>
          <RunList runs={runs.data.slice(0, 10)} sets={sets.data ?? []} />
        </section>
      ) : null}
    </div>
  );
}

function SetCard({ set: s, run }: { set: TestSet; run?: EvalRun }) {
  const t = useTranslations("evaluations");
  return (
    <Link href={`/admin/evaluations/${s.id}`} data-testid={`set-${s.name}`} className="nx-card nx-lift group flex h-full flex-col gap-4 p-5 outline-none focus-visible:ring-2 focus-visible:ring-ring">
      <div className="flex items-start justify-between gap-3">
        <div className="flex min-w-0 items-center gap-3">
          <IconTile icon={s.origin === "pack" ? Package : ListChecks} tone="amber" />
          <div className="min-w-0">
            <div className="truncate font-semibold group-hover:text-primary">{s.name}</div>
            <div className="truncate text-xs text-muted-foreground">{s.agent ? t("forAgent", { agent: s.agent }) : t("anyAgent")}</div>
          </div>
        </div>
        <StatusBadge tone="slate">{t(`origins.${s.origin}`)}</StatusBadge>
      </div>
      {s.description ? <p className="line-clamp-2 text-sm text-muted-foreground">{s.description}</p> : null}
      <div className="mt-auto flex flex-wrap items-center justify-between gap-2 text-xs text-muted-foreground">
        <span>{t("caseCount", { count: s.case_count })}</span>
        {run?.scorecard ? (
          <StatusBadge tone={passTone(run.scorecard.pass_rate)}>{t("lastScore", { version: run.version, score: percent(run.scorecard.pass_rate) })}</StatusBadge>
        ) : (
          <span>{t("neverRun")}</span>
        )}
      </div>
    </Link>
  );
}

export function RunList({ runs, sets, onOpen }: { runs: EvalRun[]; sets: TestSet[]; onOpen?: (id: string) => void }) {
  const t = useTranslations("evaluations");
  const format = useFormatter();
  const names = new Map(sets.map((s) => [s.id, s.name]));
  return (
    <ul className="nx-card divide-y" data-testid="eval-runs">
      {runs.map((r) => {
        const body = (
          <>
            <span className="flex min-w-0 flex-col">
              <span className="font-medium">{t("runTitle", { agent: r.agent, version: r.version })}</span>
              <span className="truncate text-xs text-muted-foreground">
                {[names.get(r.test_set_id), r.started_by, format.relativeTime(new Date(r.created_at))].filter(Boolean).join(" · ")}
              </span>
            </span>
            <span className="flex items-center gap-2">
              {!r.current && r.status === "completed" ? <StatusBadge tone="slate">{t("olderCases")}</StatusBadge> : null}
              <RunStatus run={r} />
            </span>
          </>
        );
        const cls = "flex w-full flex-wrap items-center justify-between gap-3 p-3 text-start text-sm outline-none hover:bg-muted/40 focus-visible:ring-2 focus-visible:ring-ring";
        return (
          <li key={r.id}>
            {onOpen ? (
              <button type="button" className={cls} onClick={() => onOpen(r.id)} data-testid="open-run">{body}</button>
            ) : (
              <Link className={cls} href={`/admin/evaluations/${r.test_set_id}?run=${r.id}`}>{body}</Link>
            )}
          </li>
        );
      })}
    </ul>
  );
}

interface GalleryPack {
  name: string;
  title: string;
}

function NewSetDialog({ open, onOpenChange }: { open: boolean; onOpenChange: (open: boolean) => void }) {
  const t = useTranslations("evaluations");
  const tc = useTranslations("common");
  const router = useRouter();
  const onError = useErrorToast();
  const agents = useObjects("agent");
  const gallery = useQuery({ queryKey: ["pack-gallery"], queryFn: () => api<GalleryPack[]>("config/v1/packs/gallery"), enabled: open });
  const { createSet, fromPack } = useEvaluationActions();
  const [mode, setMode] = useState<"pack" | "empty">("pack");
  const [name, setName] = useState("");
  const [agent, setAgent] = useState<string>("__any");
  const [pack, setPack] = useState<string>("");
  const [description, setDescription] = useState("");
  const chosenPack = pack || gallery.data?.[0]?.name || "";
  const finalName = mode === "pack" ? name || `${chosenPack}-gold` : name;
  const nameOk = NAME_PATTERN.test(finalName);

  async function submit(e: FormEvent) {
    e.preventDefault();
    if (!nameOk) return;
    const forAgent = agent === "__any" ? null : agent;
    try {
      const created =
        mode === "pack"
          ? await fromPack.mutateAsync({ pack: chosenPack, name: finalName, agent: forAgent })
          : await createSet.mutateAsync({ name: finalName, agent: forAgent, description });
      onOpenChange(false);
      router.push(`/admin/evaluations/${created.id}`);
    } catch (error) {
      onError(error);
    }
  }

  return (
    <Dialog open={open} onOpenChange={onOpenChange}>
      <DialogContent>
        <form onSubmit={submit} className="space-y-4">
          <DialogHeader>
            <DialogTitle>{t("newSet")}</DialogTitle>
            <DialogDescription>{t("newSetHelp")}</DialogDescription>
          </DialogHeader>
          <div role="group" aria-label={t("startFrom")} className="inline-flex rounded-lg border p-0.5">
            {(["pack", "empty"] as const).map((m) => (
              <Button key={m} type="button" size="sm" variant={mode === m ? "secondary" : "ghost"} aria-pressed={mode === m} onClick={() => setMode(m)}>
                {m === "pack" ? t("fromPack") : t("empty")}
              </Button>
            ))}
          </div>
          {mode === "pack" ? (
            <div className="space-y-1.5">
              <Label htmlFor="set-pack">{t("pack")}</Label>
              <Select value={chosenPack} onValueChange={setPack}>
                <SelectTrigger id="set-pack"><SelectValue placeholder={t("pickPack")} /></SelectTrigger>
                <SelectContent>
                  {(gallery.data ?? []).map((p) => <SelectItem key={p.name} value={p.name}>{p.title}</SelectItem>)}
                </SelectContent>
              </Select>
              <p className="text-xs text-muted-foreground">{t("fromPackHelp")}</p>
            </div>
          ) : null}
          <div className="space-y-1.5">
            <Label htmlFor="set-name">{t("name")}</Label>
            <Input id="set-name" value={finalName} onChange={(e) => setName(slugify(e.target.value))} aria-invalid={!!finalName && !nameOk} data-testid="set-name" />
          </div>
          <div className="space-y-1.5">
            <Label htmlFor="set-agent">{t("agent")}</Label>
            <Select value={agent} onValueChange={setAgent}>
              <SelectTrigger id="set-agent"><SelectValue /></SelectTrigger>
              <SelectContent>
                <SelectItem value="__any">{t("anyAgent")}</SelectItem>
                {(agents.data ?? []).map((a) => <SelectItem key={a.name} value={a.name}>{a.name}</SelectItem>)}
              </SelectContent>
            </Select>
          </div>
          {mode === "empty" ? (
            <div className="space-y-1.5">
              <Label htmlFor="set-description">{t("description")}</Label>
              <Textarea id="set-description" rows={2} value={description} onChange={(e) => setDescription(e.target.value)} />
            </div>
          ) : null}
          <DialogFooter>
            <Button type="button" variant="outline" onClick={() => onOpenChange(false)}>{tc("cancel")}</Button>
            <Button type="submit" disabled={!nameOk || (mode === "pack" && !chosenPack) || createSet.isPending || fromPack.isPending} data-testid="create-test-set">
              {t("create")}
            </Button>
          </DialogFooter>
        </form>
      </DialogContent>
    </Dialog>
  );
}
