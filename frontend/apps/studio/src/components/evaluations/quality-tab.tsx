"use client";

import { ClipboardCheck, Play, Save, ShieldCheck, ShieldX } from "lucide-react";
import Link from "next/link";
import { useTranslations } from "next-intl";
import { type FormEvent, useState } from "react";
import { toast } from "sonner";

import { Alert, AlertDescription, AlertTitle } from "@/components/ui/alert";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import { Select, SelectContent, SelectItem, SelectTrigger, SelectValue } from "@/components/ui/select";
import { Skeleton } from "@/components/ui/skeleton";
import { Switch } from "@/components/ui/switch";
import { StatusBadge } from "@/components/visual/status-badge";
import { byVersion, type GateCheck, type GateReason, passTone, percent, points, type ReleaseGate } from "@/lib/evaluation";
import { useEvalRuns, useEvaluationActions, useGateCheck, useReports, useTestSets } from "@/lib/evaluation-hooks";
import { useErrorToast } from "@/lib/hooks";
import { type AgentSpec, type ConfigObject, releaseState } from "@/lib/studio";
import { useRelease } from "@/lib/studio-hooks";

import { RunStatus } from "./run-status";
import { ScorecardView } from "./scorecard";

/** An assistant's quality (QA-01/02): its release gate, whether the newest version passes it,
 * and how every version scored. */
export function QualityTab({ object, spec, onSaved }: { object: ConfigObject; spec: AgentSpec; onSaved: () => void }) {
  const gate = (spec.release_gate ?? null) as ReleaseGate | null;
  return (
    <div className="space-y-6">
      <GateSettings key={JSON.stringify(gate)} object={object} spec={spec} gate={gate} onSaved={onSaved} />
      {gate?.test_set ? <ReleaseCheck object={object} gate={gate} /> : null}
      <Scores agent={object.name} live={releaseState(object).live} testSet={gate?.test_set} />
    </div>
  );
}

function GateSettings({ object, spec, gate, onSaved }: { object: ConfigObject; spec: AgentSpec; gate: ReleaseGate | null; onSaved: () => void }) {
  const t = useTranslations("quality");
  const onError = useErrorToast();
  const sets = useTestSets(object.name);
  const { saveDraft } = useRelease("agent", object.name);
  const [enabled, setEnabled] = useState(gate?.enabled ?? false);
  const [testSet, setTestSet] = useState(gate?.test_set ?? "");
  const [minRate, setMinRate] = useState(String(Math.round((gate?.min_pass_rate ?? 0.8) * 100)));
  const [maxDrop, setMaxDrop] = useState(String(Math.round((gate?.max_drop ?? 0.05) * 100)));
  const chosen = testSet || sets.data?.[0]?.name || "";
  const rate = Number(minRate);
  const drop = Number(maxDrop);
  const valid = !enabled || (!!chosen && rate >= 0 && rate <= 100 && drop >= 0 && drop <= 100);

  async function save(e: FormEvent) {
    e.preventDefault();
    const next: ReleaseGate = { enabled, test_set: chosen, min_pass_rate: rate / 100, max_drop: drop / 100 };
    try {
      const v = await saveDraft.mutateAsync({ ...spec, release_gate: chosen ? next : undefined });
      toast.success(t("saved", { version: v.version }));
      onSaved();
    } catch (error) {
      onError(error);
    }
  }

  return (
    <form onSubmit={save} className="nx-card space-y-4 p-4" aria-labelledby="gate-title">
      <div className="flex flex-wrap items-start justify-between gap-4">
        <div className="space-y-1">
          <h2 id="gate-title" className="flex items-center gap-2 font-semibold">
            <ShieldCheck className="size-4" aria-hidden="true" />
            {t("gateTitle")}
          </h2>
          <p className="max-w-prose text-sm text-muted-foreground">{t("gateHelp")}</p>
        </div>
        <div className="flex items-center gap-2">
          <Switch id="gate-on" checked={enabled} onCheckedChange={setEnabled} data-testid="gate-enabled" />
          <Label htmlFor="gate-on">{t("requirePass")}</Label>
        </div>
      </div>
      {!sets.isLoading && !sets.data?.length ? (
        <Alert>
          <ClipboardCheck className="size-4" aria-hidden="true" />
          <AlertTitle>{t("noSets")}</AlertTitle>
          <AlertDescription>
            <Link href="/admin/evaluations" className="text-primary underline-offset-4 hover:underline">{t("createSet")}</Link>
          </AlertDescription>
        </Alert>
      ) : (
        <div className="grid gap-4 sm:grid-cols-3">
          <div className="space-y-1.5">
            <Label htmlFor="gate-set">{t("testSet")}</Label>
            <Select value={chosen} onValueChange={setTestSet}>
              <SelectTrigger id="gate-set" data-testid="gate-set"><SelectValue placeholder={t("pickSet")} /></SelectTrigger>
              <SelectContent>
                {(sets.data ?? []).map((s) => <SelectItem key={s.id} value={s.name}>{t("setOption", { name: s.name, count: s.case_count })}</SelectItem>)}
              </SelectContent>
            </Select>
          </div>
          <div className="space-y-1.5">
            <Label htmlFor="gate-rate">{t("minPassRate")}</Label>
            <Input id="gate-rate" type="number" min={0} max={100} value={minRate} onChange={(e) => setMinRate(e.target.value)} />
          </div>
          <div className="space-y-1.5">
            <Label htmlFor="gate-drop">{t("maxDrop")}</Label>
            <Input id="gate-drop" type="number" min={0} max={100} value={maxDrop} onChange={(e) => setMaxDrop(e.target.value)} />
          </div>
        </div>
      )}
      <div className="flex justify-end">
        <Button type="submit" disabled={!valid || saveDraft.isPending} data-testid="save-gate">
          <Save className="size-4" aria-hidden="true" />
          {t("saveDraft")}
        </Button>
      </div>
    </form>
  );
}

export function GateReasons({ reasons }: { reasons: GateReason[] }) {
  const t = useTranslations("gate");
  return (
    <ul className="list-disc space-y-1 ps-5 text-sm" data-testid="gate-reasons">
      {reasons.map((r, i) => (
        <li key={i}>
          {t.has(`reasons.${r.code}`)
            ? t(`reasons.${r.code}`, {
                value: r.code === "regression" ? points(Number(r.value ?? 0)) : percent(Number(r.value ?? 0)),
                limit: r.code === "regression" ? points(-Number(r.limit ?? 0)) : percent(Number(r.limit ?? 0)),
                metric: r.metric ? (t.has(`metrics.${r.metric}`) ? t(`metrics.${r.metric}`) : r.metric) : "",
                set: r.test_set ?? "",
              })
            : r.code}
        </li>
      ))}
    </ul>
  );
}

/** Will the newest version pass the gate? Run its evaluation from here. */
function ReleaseCheck({ object, gate }: { object: ConfigObject; gate: ReleaseGate }) {
  const t = useTranslations("quality");
  const onError = useErrorToast();
  const state = releaseState(object);
  const candidate = object.versions.at(-1);
  const sets = useTestSets(object.name);
  const testSet = sets.data?.find((s) => s.name === gate.test_set);
  const runs = useEvalRuns({ agent: object.name, testSetId: testSet?.id });
  const { startRun } = useEvaluationActions();
  const busy = runs.data?.find((r) => r.version === candidate?.version && (r.status === "queued" || r.status === "running"));
  const check = useGateCheck(
    object.name,
    candidate && !busy
      ? { version: candidate.version, spec_hash: candidate.spec_hash, baseline_version: state.live, test_set: gate.test_set, min_pass_rate: gate.min_pass_rate, max_drop: gate.max_drop }
      : null,
    runs.data?.find((r) => r.version === candidate?.version && r.status === "completed")?.id,
  );
  if (!candidate) return null;

  async function run() {
    if (!testSet || !candidate) return;
    try {
      await startRun.mutateAsync({ agent: object.name, version: candidate.version, test_set_id: testSet.id });
    } catch (error) {
      onError(error);
    }
  }

  const result: GateCheck | undefined = check.data;
  return (
    <section aria-labelledby="check-title" className="nx-card space-y-4 p-4" data-testid="release-check">
      <div className="flex flex-wrap items-center justify-between gap-3">
        <h2 id="check-title" className="flex items-center gap-2 font-semibold">
          {result?.passed ? <ShieldCheck className="size-4 text-teal-600" aria-hidden="true" /> : <ShieldX className="size-4 text-amber-600" aria-hidden="true" />}
          {t("checkTitle", { version: candidate.version })}
        </h2>
        <div className="flex items-center gap-2">
          {busy ? <RunStatus run={busy} /> : result ? <StatusBadge tone={result.passed ? "teal" : "amber"}>{result.passed ? t("ready") : t("notReady")}</StatusBadge> : null}
          <Button variant="outline" size="sm" onClick={run} disabled={!testSet || !!busy || startRun.isPending} data-testid="run-gate-evaluation">
            <Play className="size-4" aria-hidden="true" />
            {t("evaluate", { version: candidate.version })}
          </Button>
        </div>
      </div>
      {check.isLoading && !busy ? <Skeleton className="h-24" /> : null}
      {result && !result.passed ? <GateReasons reasons={result.reasons} /> : null}
      {result?.scorecard ? (
        <>
          <p className="text-sm text-muted-foreground">{state.live && result.baseline_scorecard ? t("comparedWith", { version: state.live }) : t("noBaseline")}</p>
          <ScorecardView card={result.scorecard} baseline={result.baseline_scorecard} threshold={result.thresholds.min_pass_rate} allowance={result.thresholds.max_drop} />
        </>
      ) : null}
      {result?.run_id && testSet ? (
        <Link href={`/admin/evaluations/${testSet.id}?run=${result.run_id}`} className="text-sm text-primary underline-offset-4 hover:underline">{t("openRun")}</Link>
      ) : null}
    </section>
  );
}

function Scores({ agent, live, testSet }: { agent: string; live: number | null; testSet?: string }) {
  const t = useTranslations("quality");
  const reports = useReports(agent);
  const rows = byVersion(reports.data ?? [], testSet);
  if (reports.isLoading) return <Skeleton className="h-32" />;
  return (
    <section aria-labelledby="scores-title" className="space-y-3">
      <h2 id="scores-title" className="font-semibold">{t("scoresTitle")}</h2>
      {!rows.length ? (
        <p className="text-sm text-muted-foreground">{t("noScores")}</p>
      ) : (
        <ul className="nx-card divide-y" data-testid="version-scores">
          {rows.map((r) => (
            <li key={`${r.version}-${r.test_set_id}`} className="flex flex-wrap items-center justify-between gap-3 p-3 text-sm">
              <span className="flex items-center gap-2">
                <span className="font-medium tabular-nums">v{r.version}</span>
                {r.version === live ? <StatusBadge tone="sky" live>{t("live")}</StatusBadge> : null}
                <span className="text-muted-foreground">{r.test_set}</span>
                {!r.current ? <StatusBadge tone="slate">{t("olderCases")}</StatusBadge> : null}
              </span>
              <Link href={`/admin/evaluations/${r.test_set_id}?run=${r.run_id}`} className="outline-none focus-visible:ring-2 focus-visible:ring-ring">
                <StatusBadge tone={passTone(r.scorecard.pass_rate)}>{percent(r.scorecard.pass_rate)}</StatusBadge>
              </Link>
            </li>
          ))}
        </ul>
      )}
    </section>
  );
}
