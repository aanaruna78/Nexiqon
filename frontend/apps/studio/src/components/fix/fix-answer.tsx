"use client";

import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { BookCheck, ClipboardPlus, FileWarning, MessageSquareQuote, RefreshCw, SquareArrowOutUpRight } from "lucide-react";
import Link from "next/link";
import { useLocale, useTranslations } from "next-intl";
import { type FormEvent, useState } from "react";
import { toast } from "sonner";

import { Button } from "@/components/ui/button";
import { Checkbox } from "@/components/ui/checkbox";
import { Label } from "@/components/ui/label";
import { Select, SelectContent, SelectItem, SelectTrigger, SelectValue } from "@/components/ui/select";
import { Sheet, SheetContent, SheetDescription, SheetHeader, SheetTitle } from "@/components/ui/sheet";
import { Textarea } from "@/components/ui/textarea";
import { StatusBadge } from "@/components/visual/status-badge";
import { api } from "@/lib/api";
import { caseFromAnswer, regressionSetName } from "@/lib/evaluation";
import { useEvaluationActions, useTestSets } from "@/lib/evaluation-hooks";
import { useErrorToast } from "@/lib/hooks";
import type { KnowledgeDocument, Run } from "@/lib/knowledge";
import { useCollections } from "@/lib/knowledge-hooks";
import { useResolvedAgent, useRun } from "@/lib/studio-hooks";

export interface FixTarget {
  agent: string;
  question: string;
  answer?: string;
  runId?: string | null; // the agent run that gave the answer (its sources come from the trace)
  version?: number | null; // re-test this version (a draft) instead of the live one
  lang?: string;
}

interface Retest {
  answer: { text?: string; abstained?: boolean; citations?: { marker: string; citation: string }[] } | null;
  run_id: string;
  status: string;
}

/**
 * The one-click fix loop (ST-14, UX G2): from a bad answer, teach the right answer (a reviewed
 * Q&A snippet), take an outdated page out of answers, open the source to edit it, ask again, and
 * keep it fixed with a regression case — all without leaving the answer.
 */
export function FixAnswer({ target, onClose }: { target: FixTarget | null; onClose: () => void }) {
  const t = useTranslations("fix");
  return (
    <Sheet open={!!target} onOpenChange={(o) => !o && onClose()}>
      <SheetContent className="w-full overflow-y-auto sm:max-w-xl" data-testid="fix-answer">
        <SheetHeader>
          <SheetTitle>{t("title")}</SheetTitle>
          <SheetDescription>{t("subtitle")}</SheetDescription>
        </SheetHeader>
        {target ? <FixBody key={`${target.runId}-${target.question}`} target={target} /> : null}
      </SheetContent>
    </Sheet>
  );
}

function FixBody({ target }: { target: FixTarget }) {
  const t = useTranslations("fix");
  return (
    <div className="space-y-6 px-4 pb-8">
      <section className="space-y-2" aria-labelledby="fix-question">
        <h3 id="fix-question" className="text-xs font-medium tracking-wide text-muted-foreground uppercase">{t("question")}</h3>
        <p className="font-medium">{target.question}</p>
        {target.answer ? <blockquote className="rounded-xl border-s-4 border-amber-500 bg-muted/40 p-3 text-sm whitespace-pre-line">{target.answer}</blockquote> : null}
      </section>
      <TeachAnswer target={target} />
      <Sources target={target} />
      <AskAgain target={target} />
      <KeepFixed target={target} />
    </div>
  );
}

function StepTitle({ id, icon: Icon, n, title }: { id: string; icon: typeof BookCheck; n: number; title: string }) {
  return (
    <h3 id={id} className="flex items-center gap-2 font-semibold">
      <span className="grid size-6 place-items-center rounded-full bg-primary/10 text-xs text-primary tabular-nums" aria-hidden="true">{n}</span>
      <Icon className="size-4 text-muted-foreground" aria-hidden="true" />
      {title}
    </h3>
  );
}

/** The agent's collections (as deployed in dev), else every collection. */
function useAgentCollections(agent: string) {
  const resolved = useResolvedAgent(agent);
  const collections = useCollections();
  const names = ((resolved.data?.config as { knowledge?: { collections?: string[] } } | undefined)?.knowledge?.collections ?? []) as string[];
  const all = collections.data ?? [];
  const mine = all.filter((c) => names.includes(c.name));
  return mine.length ? mine : all;
}

function TeachAnswer({ target }: { target: FixTarget }) {
  const t = useTranslations("fix");
  const onError = useErrorToast();
  const collections = useAgentCollections(target.agent);
  const [collection, setCollection] = useState<string>("");
  const [answer, setAnswer] = useState("");
  const [run, setRun] = useState<string | null>(null);
  const chosen = collection || collections[0]?.id || "";
  const sync = useQuery({
    queryKey: ["ingestion-run", run],
    queryFn: () => api<Run>(`ingestion/v1/runs/${run}`),
    enabled: !!run,
    refetchInterval: (q) => (q.state.data && ["completed", "failed", "cancelled"].includes(q.state.data.status) ? false : 1500),
  });
  const add = useMutation({
    mutationFn: () => api<{ run_id: string | null; replaced: boolean }>(`ingestion/v1/collections/${chosen}/snippets`, { method: "POST", json: { question: target.question, answer } }),
    onSuccess: (r) => {
      setRun(r.run_id);
      toast.success(r.replaced ? t("snippetReplaced") : t("snippetAdded"));
    },
    onError,
  });
  const state = sync.data?.status;
  return (
    <section aria-labelledby="fix-teach" className="nx-card space-y-3 p-4">
      <StepTitle id="fix-teach" icon={MessageSquareQuote} n={1} title={t("teachTitle")} />
      <p className="text-sm text-muted-foreground">{t("teachHelp")}</p>
      <form
        className="space-y-3"
        onSubmit={(e: FormEvent) => {
          e.preventDefault();
          if (answer.trim() && chosen) add.mutate();
        }}
      >
        <div className="space-y-1.5">
          <Label htmlFor="fix-answer-text">{t("rightAnswer")}</Label>
          <Textarea id="fix-answer-text" rows={3} value={answer} onChange={(e) => setAnswer(e.target.value)} data-testid="fix-snippet-answer" />
        </div>
        {collections.length > 1 ? (
          <div className="space-y-1.5">
            <Label htmlFor="fix-collection">{t("collection")}</Label>
            <Select value={chosen} onValueChange={setCollection}>
              <SelectTrigger id="fix-collection"><SelectValue /></SelectTrigger>
              <SelectContent>
                {collections.map((c) => <SelectItem key={c.id} value={c.id}>{c.name}</SelectItem>)}
              </SelectContent>
            </Select>
          </div>
        ) : null}
        <div className="flex flex-wrap items-center gap-3">
          <Button type="submit" disabled={!answer.trim() || !chosen || add.isPending} data-testid="fix-add-snippet">{t("addSnippet")}</Button>
          {run ? (
            <StatusBadge tone={state === "completed" ? "teal" : state === "failed" ? "rose" : "amber"} live={state !== "completed" && state !== "failed"}>
              {state === "completed" ? t("snippetLive") : state === "failed" ? t("snippetFailed") : t("snippetSyncing")}
            </StatusBadge>
          ) : null}
        </div>
        {!collections.length ? <p className="text-xs text-muted-foreground">{t("noCollections")}</p> : null}
      </form>
    </section>
  );
}

function Sources({ target }: { target: FixTarget }) {
  const t = useTranslations("fix");
  const trace = useRun(target.runId ?? null);
  const retrieve = trace.data?.steps.find((s) => s.type === "retrieve");
  const sources = ((retrieve?.sources as { citation: string; document_id?: string | null }[] | undefined) ?? []).filter((s) => s.document_id);
  const cited = new Set((trace.data?.result.answer?.citations ?? []).map((c) => c.citation));
  // One row per document, the ones the answer cited first: they are the likeliest to be wrong.
  const ranked = [...sources].sort((a, b) => Number(cited.has(b.citation)) - Number(cited.has(a.citation)));
  const unique = [...new Map(ranked.reverse().map((s) => [s.document_id!, s])).values()].reverse();
  return (
    <section aria-labelledby="fix-sources" className="nx-card space-y-3 p-4">
      <StepTitle id="fix-sources" icon={FileWarning} n={2} title={t("sourcesTitle")} />
      <p className="text-sm text-muted-foreground">{t("sourcesHelp")}</p>
      {!target.runId || (!trace.isLoading && !unique.length) ? <p className="text-sm text-muted-foreground">{t("noSources")}</p> : null}
      <ul className="divide-y" data-testid="fix-sources">
        {unique.map((s) => <SourceRow key={s.document_id} id={s.document_id!} citation={s.citation} cited={cited.has(s.citation)} />)}
      </ul>
    </section>
  );
}

function SourceRow({ id, citation, cited }: { id: string; citation: string; cited: boolean }) {
  const t = useTranslations("fix");
  const client = useQueryClient();
  const onError = useErrorToast();
  const doc = useQuery({ queryKey: ["document", id], queryFn: () => api<KnowledgeDocument & { outdated_at?: string | null }>(`ingestion/v1/documents/${id}`), retry: false });
  const flag = useMutation({
    mutationFn: (outdated: boolean) => api<KnowledgeDocument>(`ingestion/v1/documents/${id}`, { method: "PATCH", json: { outdated } }),
    onSuccess: async (_, outdated) => {
      toast.success(outdated ? t("markedOutdated") : t("markedCurrent"));
      await client.invalidateQueries({ queryKey: ["document", id] });
    },
    onError,
  });
  const outdated = !!doc.data?.outdated_at;
  return (
    <li className="flex flex-wrap items-center justify-between gap-2 py-2 text-sm">
      <span className="flex min-w-0 flex-col">
        <span className="truncate font-medium">{citation}</span>
        <span className="flex gap-2">
          {cited ? <StatusBadge tone="teal">{t("cited")}</StatusBadge> : null}
          {outdated ? <StatusBadge tone="amber">{t("outdated")}</StatusBadge> : null}
        </span>
      </span>
      <span className="flex items-center gap-1">
        {doc.data ? (
          <Button asChild variant="ghost" size="sm">
            <Link href={`/admin/knowledge/${doc.data.collection_id}`}>
              <SquareArrowOutUpRight className="size-4" aria-hidden="true" />
              {t("openSource")}
            </Link>
          </Button>
        ) : null}
        <Button variant="outline" size="sm" disabled={!doc.data || flag.isPending} onClick={() => flag.mutate(!outdated)} data-testid="fix-outdated">
          {outdated ? t("markCurrent") : t("markOutdated")}
        </Button>
      </span>
    </li>
  );
}

function AskAgain({ target }: { target: FixTarget }) {
  const t = useTranslations("fix");
  const locale = useLocale();
  const onError = useErrorToast();
  const ask = useMutation({
    mutationFn: () =>
      api<Retest>(`agent-runtime/v1/agents/${target.agent}/runs`, {
        method: "POST",
        json: {
          thread_id: `retest-${crypto.randomUUID()}`,
          input: target.question,
          locale: (target.lang ?? locale).slice(0, 2),
          ...(target.version ? { version: target.version } : {}),
        },
      }),
    onError,
  });
  const answer = ask.data?.answer;
  return (
    <section aria-labelledby="fix-retest" className="nx-card space-y-3 p-4">
      <StepTitle id="fix-retest" icon={RefreshCw} n={3} title={t("retestTitle")} />
      <p className="text-sm text-muted-foreground">{target.version ? t("retestDraft", { version: target.version }) : t("retestLive")}</p>
      <Button variant="outline" onClick={() => ask.mutate()} disabled={ask.isPending} data-testid="fix-retest">
        <RefreshCw className="size-4" aria-hidden="true" />
        {ask.isPending ? t("asking") : t("askAgain")}
      </Button>
      {ask.data ? (
        <div className="space-y-2" aria-live="polite" data-testid="fix-retest-answer">
          <blockquote className="rounded-xl border-s-4 border-primary bg-muted/40 p-3 text-sm whitespace-pre-line">{answer?.text ?? t("noAnswer")}</blockquote>
          <div className="flex flex-wrap gap-2">
            {answer?.abstained ? <StatusBadge tone="amber">{t("stillUnsure")}</StatusBadge> : <StatusBadge tone="teal">{t("answered")}</StatusBadge>}
            {answer?.citations?.map((c) => <span key={c.marker} className="rounded-md bg-primary/10 px-1.5 text-xs text-primary">[{c.marker}] {c.citation}</span>)}
          </div>
        </div>
      ) : null}
    </section>
  );
}

function KeepFixed({ target }: { target: FixTarget }) {
  const t = useTranslations("fix");
  const onError = useErrorToast();
  const sets = useTestSets(target.agent);
  const { createSet, addCases } = useEvaluationActions();
  const fallback = regressionSetName(target.agent);
  const [setId, setSetId] = useState<string>("");
  const [phrases, setPhrases] = useState("");
  const [abstain, setAbstain] = useState(false);
  const [saved, setSaved] = useState<string | null>(null);
  const options = sets.data ?? [];
  const chosen = setId || options.find((s) => s.name === fallback)?.id || "";

  async function save(e: FormEvent) {
    e.preventDefault();
    const body = caseFromAnswer({ question: target.question, lang: target.lang, phrases, runId: target.runId, mustAbstain: abstain });
    try {
      if (chosen) {
        await addCases.mutateAsync({ setId: chosen, cases: [body] });
        setSaved(options.find((s) => s.id === chosen)?.name ?? fallback);
      } else {
        const created = await createSet.mutateAsync({ name: fallback, agent: target.agent, description: t("regressionsDescription"), cases: [body] });
        setSaved(created.name);
      }
      toast.success(t("caseSaved"));
    } catch (error) {
      onError(error);
    }
  }

  return (
    <section aria-labelledby="fix-keep" className="nx-card space-y-3 p-4">
      <StepTitle id="fix-keep" icon={ClipboardPlus} n={4} title={t("keepTitle")} />
      <p className="text-sm text-muted-foreground">{t("keepHelp")}</p>
      <form className="space-y-3" onSubmit={save}>
        <div className="space-y-1.5">
          <Label htmlFor="fix-set">{t("testSet")}</Label>
          <Select value={chosen || "__new"} onValueChange={(v) => setSetId(v === "__new" ? "" : v)}>
            <SelectTrigger id="fix-set"><SelectValue /></SelectTrigger>
            <SelectContent>
              {!options.some((s) => s.name === fallback) ? <SelectItem value="__new">{t("newSet", { name: fallback })}</SelectItem> : null}
              {options.map((s) => <SelectItem key={s.id} value={s.id}>{s.name}</SelectItem>)}
            </SelectContent>
          </Select>
        </div>
        <div className="flex items-center gap-2">
          <Checkbox id="fix-abstain" checked={abstain} onCheckedChange={(v) => setAbstain(v === true)} />
          <Label htmlFor="fix-abstain" className="font-normal">{t("shouldAbstain")}</Label>
        </div>
        {!abstain ? (
          <div className="space-y-1.5">
            <Label htmlFor="fix-phrases">{t("mustSay")}</Label>
            <Textarea id="fix-phrases" rows={2} value={phrases} onChange={(e) => setPhrases(e.target.value)} placeholder={t("mustSayPlaceholder")} data-testid="fix-phrases" />
          </div>
        ) : null}
        <div className="flex flex-wrap items-center gap-3">
          <Button type="submit" disabled={(!abstain && !phrases.trim()) || addCases.isPending || createSet.isPending} data-testid="fix-save-case">{t("saveCase")}</Button>
          {saved ? (
            <Link href="/admin/evaluations" className="text-sm text-primary underline-offset-4 hover:underline">
              {t("savedIn", { name: saved })}
            </Link>
          ) : null}
        </div>
      </form>
    </section>
  );
}
