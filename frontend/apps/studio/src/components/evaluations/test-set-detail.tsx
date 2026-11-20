"use client";

import { ArrowLeft, ListChecks, Pencil, Play, Plus, ScanSearch, Trash2, Wrench } from "lucide-react";
import Link from "next/link";
import { useRouter, useSearchParams } from "next/navigation";
import { useTranslations } from "next-intl";
import { type FormEvent, useState } from "react";
import { toast } from "sonner";

import { FixAnswer, type FixTarget } from "@/components/fix/fix-answer";
import { AnswerInspector } from "@/components/inspector/answer-inspector";
import { PageHeader } from "@/components/page-header";
import { Alert, AlertTitle } from "@/components/ui/alert";
import { Button } from "@/components/ui/button";
import { Checkbox } from "@/components/ui/checkbox";
import { Dialog, DialogContent, DialogDescription, DialogFooter, DialogHeader, DialogTitle } from "@/components/ui/dialog";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import { Select, SelectContent, SelectItem, SelectTrigger, SelectValue } from "@/components/ui/select";
import { Sheet, SheetContent, SheetDescription, SheetHeader, SheetTitle } from "@/components/ui/sheet";
import { Skeleton } from "@/components/ui/skeleton";
import { Textarea } from "@/components/ui/textarea";
import { StatusBadge } from "@/components/visual/status-badge";
import { type CaseInput, type EvalResult, expectation, progress, runIsActive, type TestCase, type TestSet } from "@/lib/evaluation";
import { useCases, useEvalResults, useEvalRun, useEvalRuns, useEvaluationActions, useTestSet } from "@/lib/evaluation-hooks";
import { useErrorToast } from "@/lib/hooks";
import { useObjects } from "@/lib/studio-hooks";
import { Hint } from "@/components/visual/hint";

import { RunList } from "./evaluations-page";
import { RunStatus } from "./run-status";
import { ScorecardView } from "./scorecard";

/** One test set: run it against an assistant version, see every run, edit the cases (ST-17). */
export function TestSetDetail({ id }: { id: string }) {
  const t = useTranslations("evaluations");
  const params = useSearchParams();
  const router = useRouter();
  const set = useTestSet(id);
  const runs = useEvalRuns({ testSetId: id });
  const openRun = params.get("run");

  if (set.isLoading) return <Skeleton className="h-96" />;
  if (!set.data) return <Alert variant="destructive"><AlertTitle>{t("notFound")}</AlertTitle></Alert>;
  return (
    <div className="space-y-8">
      <Button asChild variant="ghost" size="sm" className="-ms-2">
        <Link href="/evaluations"><ArrowLeft className="size-4 rtl:rotate-180" aria-hidden="true" />{t("all")}</Link>
      </Button>
      <PageHeader title={set.data.name} description={set.data.description || t("setSubtitle", { count: set.data.case_count })} icon={ListChecks} tone="amber" />
      <RunLauncher set={set.data} onStarted={(runId) => router.replace(`/evaluations/${id}?run=${runId}`)} />
      {runs.data?.length ? (
        <section aria-labelledby="set-runs" className="space-y-3">
          <h2 id="set-runs" className="font-semibold">{t("runs")}</h2>
          <RunList runs={runs.data} sets={[set.data]} onOpen={(runId) => router.replace(`/evaluations/${id}?run=${runId}`)} />
        </section>
      ) : null}
      <CasesEditor set={set.data} />
      <RunSheet runId={openRun} onClose={() => router.replace(`/evaluations/${id}`)} />
    </div>
  );
}

function RunLauncher({ set, onStarted }: { set: TestSet; onStarted: (runId: string) => void }) {
  const t = useTranslations("evaluations");
  const onError = useErrorToast();
  const agents = useObjects("agent");
  const { startRun } = useEvaluationActions();
  const [agent, setAgent] = useState<string>(set.agent ?? "");
  const chosen = agent || set.agent || agents.data?.[0]?.name || "";
  const object = agents.data?.find((a) => a.name === chosen);
  const versions = [...(object?.versions ?? [])].reverse();
  const [version, setVersion] = useState<string>("");
  const chosenVersion = version || (versions[0] ? String(versions[0].version) : "");

  async function start(e: FormEvent) {
    e.preventDefault();
    try {
      const run = await startRun.mutateAsync({ agent: chosen, version: Number(chosenVersion), test_set_id: set.id });
      toast.success(t("started", { version: run.version }));
      onStarted(run.id);
    } catch (error) {
      onError(error);
    }
  }

  return (
    <form onSubmit={start} className="nx-card flex flex-wrap items-end gap-4 p-4" aria-label={t("runSet")}>
      <div className="space-y-1.5">
        <Label htmlFor="run-agent">{t("agent")}</Label>
        <Select value={chosen} onValueChange={(v) => { setAgent(v); setVersion(""); }} disabled={!!set.agent}>
          <SelectTrigger id="run-agent" className="w-52"><SelectValue placeholder={t("pickAgent")} /></SelectTrigger>
          <SelectContent>
            {(agents.data ?? []).map((a) => <SelectItem key={a.name} value={a.name}>{a.name}</SelectItem>)}
          </SelectContent>
        </Select>
      </div>
      <div className="space-y-1.5">
        <Label htmlFor="run-version">{t("version")}</Label>
        <Select value={chosenVersion} onValueChange={setVersion}>
          <SelectTrigger id="run-version" className="w-52" data-testid="run-version"><SelectValue placeholder={t("pickVersion")} /></SelectTrigger>
          <SelectContent>
            {versions.map((v) => (
              <SelectItem key={v.version} value={String(v.version)}>
                {t(v.version === object?.deployments.dev ? "versionLive" : v.status === "draft" ? "versionDraft" : "versionOlder", { version: v.version })}
              </SelectItem>
            ))}
          </SelectContent>
        </Select>
      </div>
      <Button type="submit" disabled={!chosen || !chosenVersion || !set.case_count || startRun.isPending} data-testid="start-run">
        <Play className="size-4" aria-hidden="true" />
        {t("runCases", { count: set.case_count })}
      </Button>
      <p className="basis-full text-xs text-muted-foreground">{t("runHelp")}</p>
    </form>
  );
}

function CasesEditor({ set }: { set: TestSet }) {
  const t = useTranslations("evaluations");
  const onError = useErrorToast();
  const cases = useCases(set.id);
  const { deleteCase } = useEvaluationActions();
  const [editing, setEditing] = useState<TestCase | "new" | null>(null);
  return (
    <section aria-labelledby="set-cases" className="space-y-3">
      <div className="flex flex-wrap items-center justify-between gap-2">
        <h2 id="set-cases" className="font-semibold">{t("cases")}</h2>
        <Button variant="outline" size="sm" onClick={() => setEditing("new")} data-testid="add-case">
          <Plus className="size-4" aria-hidden="true" />
          {t("addCase")}
        </Button>
      </div>
      {cases.isLoading ? <Skeleton className="h-40" /> : null}
      {cases.data && !cases.data.length ? <p className="text-sm text-muted-foreground">{t("noCases")}</p> : null}
      {cases.data?.length ? (
        <ul className="nx-card divide-y" data-testid="cases">
          {cases.data.map((c) => {
            const e = expectation(c);
            return (
              <li key={c.id} className="flex flex-wrap items-start justify-between gap-3 p-3 text-sm">
                <div className="min-w-0 flex-1 space-y-1">
                  <p className="font-medium" dir="auto">{c.question}</p>
                  <p className="flex flex-wrap items-center gap-2 text-xs text-muted-foreground">
                    <StatusBadge tone={e.kind === "abstain" ? "violet" : "sky"}>{t(`expect.${e.kind}`)}</StatusBadge>
                    {e.phrases.length ? <span dir="auto">“{e.phrases.join("” · “")}”</span> : null}
                    {e.source ? <span>{e.source}</span> : null}
                    <span className="uppercase">{c.lang}</span>
                    {c.origin?.kind === "run" ? <StatusBadge tone="amber">{t("fromFix")}</StatusBadge> : null}
                  </p>
                </div>
                <span className="flex gap-1">
                  <Hint label={t("editCase")}>
                    <Button variant="ghost" size="icon" aria-label={t("editCase")} onClick={() => setEditing(c)}>
                      <Pencil className="size-4" aria-hidden="true" />
                    </Button>
                  </Hint>
                  <Hint label={t("deleteCase")}>
                    <Button variant="ghost" size="icon" aria-label={t("deleteCase")} onClick={() => deleteCase.mutate({ setId: set.id, caseId: c.id }, { onError })}>
                      <Trash2 className="size-4" aria-hidden="true" />
                    </Button>
                  </Hint>
                </span>
              </li>
            );
          })}
        </ul>
      ) : null}
      <CaseDialog set={set} value={editing} onClose={() => setEditing(null)} />
    </section>
  );
}

function CaseDialog({ set, value, onClose }: { set: TestSet; value: TestCase | "new" | null; onClose: () => void }) {
  return (
    <Dialog open={value !== null} onOpenChange={(o) => !o && onClose()}>
      <DialogContent>{value !== null ? <CaseForm key={value === "new" ? "new" : value.id} set={set} value={value} onClose={onClose} /> : null}</DialogContent>
    </Dialog>
  );
}

function CaseForm({ set, value, onClose }: { set: TestSet; value: TestCase | "new"; onClose: () => void }) {
  const t = useTranslations("evaluations");
  const tc = useTranslations("common");
  const onError = useErrorToast();
  const { addCases, replaceCase } = useEvaluationActions();
  const current = value === "new" ? null : value;
  const [question, setQuestion] = useState(current?.question ?? "");
  const [lang, setLang] = useState(current?.lang ?? "en");
  const [abstain, setAbstain] = useState(current?.must_abstain ?? false);
  const [phrases, setPhrases] = useState((current?.expected_phrases ?? []).join("\n"));
  const [source, setSource] = useState(current?.expected_source ?? "");
  const [section, setSection] = useState(current?.expected_section ?? "");

  async function submit(e: FormEvent) {
    e.preventDefault();
    const body: CaseInput = {
      question: question.trim(),
      lang,
      must_abstain: abstain,
      expected_phrases: abstain ? [] : phrases.split("\n").map((p) => p.trim()).filter(Boolean).slice(0, 10),
      expected_source: abstain ? null : source.trim() || null,
      expected_section: abstain ? null : section.trim() || null,
      origin: current?.origin ?? { kind: "manual" },
      notes: current?.notes ?? "",
    };
    try {
      if (current) await replaceCase.mutateAsync({ setId: set.id, caseId: current.id, body });
      else await addCases.mutateAsync({ setId: set.id, cases: [body] });
      onClose();
    } catch (error) {
      onError(error);
    }
  }

  return (
    <form onSubmit={submit} className="space-y-4">
      <DialogHeader>
        <DialogTitle>{current ? t("editCase") : t("addCase")}</DialogTitle>
        <DialogDescription>{t("caseHelp")}</DialogDescription>
      </DialogHeader>
      <div className="space-y-1.5">
        <Label htmlFor="case-question">{t("question")}</Label>
        <Textarea id="case-question" rows={2} value={question} onChange={(e) => setQuestion(e.target.value)} dir="auto" data-testid="case-question" />
      </div>
      <div className="flex flex-wrap items-center gap-4">
        <div className="space-y-1.5">
          <Label htmlFor="case-lang">{t("lang")}</Label>
          <Input id="case-lang" className="w-20" value={lang} maxLength={2} onChange={(e) => setLang(e.target.value.toLowerCase())} />
        </div>
        <div className="flex items-center gap-2 pt-5">
          <Checkbox id="case-abstain" checked={abstain} onCheckedChange={(v) => setAbstain(v === true)} />
          <Label htmlFor="case-abstain" className="font-normal">{t("mustAbstain")}</Label>
        </div>
      </div>
      {!abstain ? (
        <>
          <div className="space-y-1.5">
            <Label htmlFor="case-phrases">{t("phrases")}</Label>
            <Textarea id="case-phrases" rows={2} value={phrases} onChange={(e) => setPhrases(e.target.value)} placeholder={t("phrasesPlaceholder")} dir="auto" data-testid="case-phrases" />
          </div>
          <div className="grid gap-3 sm:grid-cols-2">
            <div className="space-y-1.5">
              <Label htmlFor="case-source">{t("source")}</Label>
              <Input id="case-source" value={source} onChange={(e) => setSource(e.target.value)} placeholder="billing.md" />
            </div>
            <div className="space-y-1.5">
              <Label htmlFor="case-section">{t("section")}</Label>
              <Input id="case-section" value={section} onChange={(e) => setSection(e.target.value)} />
            </div>
          </div>
        </>
      ) : null}
      <DialogFooter>
        <Button type="button" variant="outline" onClick={onClose}>{tc("cancel")}</Button>
        <Button type="submit" disabled={question.trim().length < 3 || addCases.isPending || replaceCase.isPending} data-testid="save-case">{tc("save")}</Button>
      </DialogFooter>
    </form>
  );
}

/** A run's scorecard and every answer, failures first, each one fixable (ST-14). */
function RunSheet({ runId, onClose }: { runId: string | null; onClose: () => void }) {
  const t = useTranslations("evaluations");
  const run = useEvalRun(runId);
  const done = !!run.data && !runIsActive(run.data);
  const results = useEvalResults(runId, done);
  const [inspect, setInspect] = useState<string | null>(null);
  const [fix, setFix] = useState<FixTarget | null>(null);
  const r = run.data;
  return (
    <Sheet open={!!runId} onOpenChange={(o) => !o && onClose()}>
      <SheetContent className="w-full overflow-y-auto sm:max-w-3xl" data-testid="run-sheet">
        <SheetHeader>
          <SheetTitle>{r ? t("runTitle", { agent: r.agent, version: r.version }) : t("run")}</SheetTitle>
          <SheetDescription>{r ? <RunStatus run={r} /> : null}</SheetDescription>
        </SheetHeader>
        <div className="space-y-6 px-4 pb-8">
          {run.isLoading ? <Skeleton className="h-64" /> : null}
          {r && runIsActive(r) ? (
            <div className="space-y-2">
              <div className="h-2 overflow-hidden rounded-full bg-muted" role="progressbar" aria-valuemin={0} aria-valuemax={100} aria-valuenow={Math.round(progress(r) * 100)} aria-label={t("progress")}>
                <div className="h-full rounded-full bg-primary transition-all" style={{ width: `${Math.round(progress(r) * 100)}%` }} />
              </div>
              <p className="text-sm text-muted-foreground">{t("asking", { done: r.done_count, total: r.case_count })}</p>
            </div>
          ) : null}
          {r?.scorecard ? <ScorecardView card={r.scorecard} /> : null}
          {results.data ? (
            <ul className="space-y-3" data-testid="results">
              {results.data.map((x) => (
                <ResultRow key={x.case_id} result={x} onInspect={setInspect} onFix={() => r && setFix({ agent: r.agent, question: x.question, answer: x.answer, runId: x.agent_run_id, version: r.version, lang: x.lang })} />
              ))}
            </ul>
          ) : null}
        </div>
        <AnswerInspector runId={inspect} onClose={() => setInspect(null)} />
        <FixAnswer target={fix} onClose={() => setFix(null)} />
      </SheetContent>
    </Sheet>
  );
}

function ResultRow({ result: x, onInspect, onFix }: { result: EvalResult; onInspect: (id: string) => void; onFix: () => void }) {
  const t = useTranslations("evaluations");
  return (
    <li className="nx-card space-y-2 p-3 text-sm" data-testid={x.passed ? "result-passed" : "result-failed"}>
      <div className="flex flex-wrap items-start justify-between gap-2">
        <p className="font-medium" dir="auto">{x.question}</p>
        <StatusBadge tone={x.passed ? "teal" : "rose"}>{x.passed ? t("passed") : t("failedCase")}</StatusBadge>
      </div>
      {x.error ? <p className="text-destructive">{x.error}</p> : <p className="whitespace-pre-line text-muted-foreground" dir="auto">{x.answer || t("noAnswer")}</p>}
      {x.citations.length ? (
        <div className="flex flex-wrap gap-1.5">
          {x.citations.map((c, i) => <span key={i} className="rounded-md bg-primary/10 px-1.5 text-xs text-primary">{c.citation}</span>)}
        </div>
      ) : null}
      <ul className="space-y-1">
        {Object.entries(x.scores).map(([name, s]) => (
          <li key={name} className="flex items-start gap-2 text-xs">
            <span className={s.passed ? "text-teal-600 dark:text-teal-400" : "text-rose-600 dark:text-rose-400"} aria-hidden="true">{s.passed ? "✓" : "✕"}</span>
            <span>
              <span className="font-medium">{t.has(`evaluators.${name}.title`) ? t(`evaluators.${name}.title`) : name}</span>
              <span className="text-muted-foreground"> — {s.detail}</span>
              <span className="sr-only">{s.passed ? t("passed") : t("failedCase")}</span>
            </span>
          </li>
        ))}
      </ul>
      <div className="flex flex-wrap gap-2">
        {x.agent_run_id ? (
          <Button variant="ghost" size="sm" onClick={() => onInspect(x.agent_run_id!)}>
            <ScanSearch className="size-4" aria-hidden="true" />
            {t("why")}
          </Button>
        ) : null}
        {!x.passed ? (
          <Button variant="outline" size="sm" onClick={onFix} data-testid="fix-result">
            <Wrench className="size-4" aria-hidden="true" />
            {t("fix")}
          </Button>
        ) : null}
      </div>
    </li>
  );
}
