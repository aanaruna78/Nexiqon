"use client";

import { useMutation } from "@tanstack/react-query";
import { BookOpenText, CircleAlert, ExternalLink, FlaskConical, Gauge, Quote, Search, Sparkles, Timer } from "lucide-react";
import Link from "next/link";
import { useSearchParams } from "next/navigation";
import { useTranslations } from "next-intl";
import { type FormEvent, type KeyboardEvent, useMemo, useState } from "react";

import { EmptyState } from "@/components/empty-state";
import { ProfileSelect } from "@/components/knowledge/profile-select";
import { PageHeader } from "@/components/page-header";
import { Alert, AlertDescription, AlertTitle } from "@/components/ui/alert";
import { Button } from "@/components/ui/button";
import { Checkbox } from "@/components/ui/checkbox";
import { Label } from "@/components/ui/label";
import { Sheet, SheetContent, SheetDescription, SheetHeader, SheetTitle } from "@/components/ui/sheet";
import { Skeleton } from "@/components/ui/skeleton";
import { Switch } from "@/components/ui/switch";
import { Textarea } from "@/components/ui/textarea";
import { StatusBadge } from "@/components/visual/status-badge";
import { api, ApiError } from "@/lib/api";
import { answerParts, type AnswerResponse, highlight, isWebUri, type Passage, type SearchResponse } from "@/lib/knowledge";
import { useCollections } from "@/lib/knowledge-hooks";
import { cn } from "@/lib/utils";

type Mode = "answer" | "search";

export function Playground() {
  const t = useTranslations("playground");
  const params = useSearchParams();
  const collections = useCollections();
  const [selected, setSelected] = useState<string[] | null>(null);
  const [mode, setMode] = useState<Mode>("answer");
  const [query, setQuery] = useState("");
  const [modelProfile, setModelProfile] = useState<string | null>(null);
  const [retrievalProfile, setRetrievalProfile] = useState<string | null>(null);
  const [smallToBig, setSmallToBig] = useState(true);
  const [rerank, setRerank] = useState(false);
  const [preview, setPreview] = useState<Passage | null>(null);

  const all = useMemo(() => collections.data ?? [], [collections.data]);
  const initial = params.get("collection");
  const chosen = selected ?? (initial ? [initial] : all.slice(0, 1).map((c) => c.id));
  const first = all.find((c) => c.id === chosen[0]);
  const model = modelProfile ?? first?.model_profile ?? "cloud-frontier";
  const retrieval = retrievalProfile ?? first?.retrieval_profile ?? "standard";

  const run = useMutation({
    mutationFn: async (): Promise<{ mode: Mode; query: string; search: SearchResponse; answer?: AnswerResponse }> => {
      const body = {
        query,
        collection_ids: chosen,
        model_profile: model,
        retrieval_profile: retrieval,
        small_to_big: smallToBig,
        rerank,
      };
      if (mode === "search") return { mode, query, search: await api<SearchResponse>("retrieval/v1/search", { method: "POST", json: body }) };
      const answer = await api<AnswerResponse>("retrieval/v1/answer", { method: "POST", json: body });
      return { mode, query, search: answer.search, answer };
    },
  });

  function submit(event?: FormEvent) {
    event?.preventDefault();
    if (query.trim() && chosen.length) run.mutate();
  }

  function onKey(event: KeyboardEvent<HTMLTextAreaElement>) {
    if (event.key === "Enter" && (event.metaKey || event.ctrlKey)) submit();
  }

  if (collections.isLoading) return <Skeleton className="h-96" />;
  if (!all.length) {
    return (
      <div className="space-y-8">
        <PageHeader title={t("title")} description={t("subtitle")} icon={FlaskConical} tone="amber" />
        <EmptyState
          icon={BookOpenText}
          tone="amber"
          title={t("noCollections")}
          body={t("noCollectionsBody")}
          action={<Button asChild><Link href="/knowledge">{t("goToKnowledge")}</Link></Button>}
        />
      </div>
    );
  }

  const result = run.data;
  return (
    <div className="space-y-6">
      <PageHeader title={t("title")} description={t("subtitle")} icon={FlaskConical} tone="amber" />
      <div className="grid gap-6 lg:grid-cols-[18rem_1fr]">
        <aside className="nx-card h-fit space-y-5 p-4" aria-label={t("settings")}>
          <fieldset className="space-y-2">
            <legend className="text-sm font-medium">{t("collections")}</legend>
            {all.map((c) => (
              <div key={c.id} className="flex items-center gap-2">
                <Checkbox
                  id={`pg-${c.id}`}
                  checked={chosen.includes(c.id)}
                  onCheckedChange={(on) => setSelected(on ? [...new Set([...chosen, c.id])] : chosen.filter((x) => x !== c.id))}
                />
                <Label htmlFor={`pg-${c.id}`} className="font-normal">{c.name}</Label>
              </div>
            ))}
          </fieldset>
          <div className="space-y-2">
            <Label htmlFor="pg-model">{t("modelProfile")}</Label>
            <ProfileSelect kind="model_profile" id="pg-model" value={model} onChange={setModelProfile} />
          </div>
          <div className="space-y-2">
            <Label htmlFor="pg-retrieval">{t("retrievalProfile")}</Label>
            <ProfileSelect kind="retrieval_profile" id="pg-retrieval" value={retrieval} onChange={setRetrievalProfile} />
          </div>
          <div className="flex items-center justify-between gap-3">
            <Label htmlFor="pg-s2b" className="font-normal">{t("smallToBig")}</Label>
            <Switch id="pg-s2b" checked={smallToBig} onCheckedChange={setSmallToBig} />
          </div>
          <div className="flex items-center justify-between gap-3">
            <Label htmlFor="pg-rerank" className="font-normal">{t("rerank")}</Label>
            <Switch id="pg-rerank" checked={rerank} onCheckedChange={setRerank} />
          </div>
        </aside>
        <div className="min-w-0 space-y-5">
          <form onSubmit={submit} className="nx-card space-y-3 p-4">
            <div className="flex flex-wrap items-center justify-between gap-2">
              <Label htmlFor="pg-query" className="text-base font-semibold">{t("question")}</Label>
              <div role="radiogroup" aria-label={t("mode")} className="inline-flex rounded-lg bg-muted p-1">
                {(["answer", "search"] as const).map((m) => (
                  <button
                    key={m}
                    type="button"
                    role="radio"
                    aria-checked={mode === m}
                    onClick={() => setMode(m)}
                    className={cn(
                      "inline-flex items-center gap-1.5 rounded-md px-3 py-1 text-sm font-medium text-foreground/75 transition-colors focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring",
                      mode === m && "bg-background text-foreground shadow-sm",
                    )}
                  >
                    {m === "answer" ? <Sparkles className="size-4" aria-hidden="true" /> : <Search className="size-4" aria-hidden="true" />}
                    {t(`modes.${m}`)}
                  </button>
                ))}
              </div>
            </div>
            <Textarea
              id="pg-query"
              value={query}
              onChange={(e) => setQuery(e.target.value)}
              onKeyDown={onKey}
              rows={3}
              placeholder={t("placeholder")}
              aria-describedby="pg-query-help"
              data-testid="playground-query"
            />
            <div className="flex flex-wrap items-center justify-between gap-2">
              <p id="pg-query-help" className="text-xs text-muted-foreground">{t("shortcut")}</p>
              <Button type="submit" disabled={run.isPending || !query.trim() || !chosen.length} data-testid="playground-run">
                {mode === "answer" ? <Sparkles className="size-4" aria-hidden="true" /> : <Search className="size-4" aria-hidden="true" />}
                {run.isPending ? t("working") : mode === "answer" ? t("ask") : t("search")}
              </Button>
            </div>
          </form>
          {run.isPending ? <Skeleton className="h-48" /> : null}
          {run.error ? (
            <Alert variant="destructive" data-testid="playground-error">
              <CircleAlert className="size-4" aria-hidden="true" />
              <AlertTitle>{run.error instanceof ApiError ? (run.error.problem.title ?? t("failed")) : t("failed")}</AlertTitle>
              <AlertDescription>{run.error instanceof ApiError ? run.error.problem.detail : null}</AlertDescription>
            </Alert>
          ) : null}
          {result && !run.isPending ? (
            <div className="space-y-5" aria-live="polite">
              {result.answer ? <AnswerCard answer={result.answer} onCite={setPreview} /> : null}
              {result.mode === "search" && result.search.abstain ? (
                <Alert>
                  <CircleAlert className="size-4" aria-hidden="true" />
                  <AlertTitle>{t("weakEvidence")}</AlertTitle>
                  <AlertDescription>{t("weakEvidenceBody")}</AlertDescription>
                </Alert>
              ) : null}
              <Diagnostics search={result.search} />
              <section aria-labelledby="pg-passages" className="space-y-3">
                <h2 id="pg-passages" className="text-sm font-semibold">{t("passages", { count: result.search.passages.length })}</h2>
                <ol className="nx-stagger space-y-3">
                  {result.search.passages.map((p, i) => (
                    <li key={p.id}>
                      <PassageCard passage={p} index={i + 1} query={result.query} onOpen={() => setPreview(p)} />
                    </li>
                  ))}
                </ol>
              </section>
            </div>
          ) : null}
        </div>
      </div>
      <SourcePreview passage={preview} query={result?.query ?? ""} onClose={() => setPreview(null)} />
    </div>
  );
}

function AnswerCard({ answer, onCite }: { answer: AnswerResponse; onCite: (p: Passage) => void }) {
  const t = useTranslations("playground");
  const byMarker = new Map(answer.citations.map((c) => [c.marker, c]));
  const passageById = new Map(answer.search.passages.map((p) => [p.id, p]));
  return (
    <section className={cn("nx-card space-y-3 p-5", answer.abstained && "border-amber-300 dark:border-amber-400/40")} aria-labelledby="pg-answer" data-testid="playground-answer">
      <div className="flex items-center justify-between gap-2">
        <h2 id="pg-answer" className="flex items-center gap-2 font-semibold">
          <Sparkles className="size-4 text-primary" aria-hidden="true" />
          {t("answer")}
        </h2>
        {answer.abstained ? <StatusBadge tone="amber">{t("abstained")}</StatusBadge> : <StatusBadge tone="teal">{t("grounded", { count: answer.citations.length })}</StatusBadge>}
      </div>
      {answer.abstained ? (
        <p className="text-sm text-muted-foreground">{t(`abstainReasons.${answer.reason ?? "unsupported"}`)}</p>
      ) : null}
      {answer.answer ? (
        <p className="leading-relaxed">
          {answerParts(answer.answer).map((part, i) =>
            "marker" in part ? (
              <CitationChip key={i} marker={part.marker} label={byMarker.get(part.marker)?.citation} onClick={() => {
                const c = byMarker.get(part.marker);
                const p = c ? passageById.get(c.passage_id) : undefined;
                if (p) onCite(p);
              }} />
            ) : (
              <span key={i}>{part.text}</span>
            ),
          )}
        </p>
      ) : null}
      {answer.removed.length ? (
        <p className="text-xs text-muted-foreground" data-testid="removed-citations">
          {t("removedCitations", { count: answer.removed.length, reasons: [...new Set(answer.removed.map((r) => t(`removeReasons.${r.reason}`)))].join(", ") })}
        </p>
      ) : null}
      {answer.model.model ? <p className="text-xs text-muted-foreground">{t("generatedBy", { model: String(answer.model.model), profile: String(answer.model.profile ?? "") })}</p> : null}
    </section>
  );
}

function CitationChip({ marker, label, onClick }: { marker: string; label?: string; onClick: () => void }) {
  const t = useTranslations("playground");
  return (
    <button
      type="button"
      onClick={onClick}
      className="mx-0.5 inline-flex h-5 min-w-5 items-center justify-center rounded-md bg-primary/10 px-1 align-text-top text-xs font-semibold text-primary hover:bg-primary/20 focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring"
      aria-label={t("openCitation", { marker, label: label ?? "" })}
      title={label}
    >
      {marker}
    </button>
  );
}

function Diagnostics({ search }: { search: SearchResponse }) {
  const t = useTranslations("playground");
  const timings = Object.entries(search.timings_ms).filter(([k]) => k !== "total");
  const total = search.timings_ms.total ?? 0;
  const evidence = Math.round(search.evidence_score * 100);
  return (
    <div className="grid gap-3 sm:grid-cols-2" data-testid="diagnostics">
      <div className="nx-card space-y-2 p-4">
        <div className="flex items-center justify-between text-sm">
          <span className="flex items-center gap-2 font-medium"><Gauge className="size-4" aria-hidden="true" />{t("evidence")}</span>
          <span className="tabular-nums">{evidence}%</span>
        </div>
        <div className="h-2 overflow-hidden rounded-full bg-muted" role="meter" aria-valuemin={0} aria-valuemax={100} aria-valuenow={evidence} aria-label={t("evidence")}>
          <div className={cn("h-full rounded-full", search.abstain ? "bg-amber-500" : "bg-primary")} style={{ width: `${evidence}%` }} />
        </div>
        <p className="text-xs text-muted-foreground">
          {[search.embedding_model, search.reranked ? t("reranked") : null].filter(Boolean).join(" · ")}
        </p>
      </div>
      <div className="nx-card space-y-2 p-4">
        <div className="flex items-center justify-between text-sm">
          <span className="flex items-center gap-2 font-medium"><Timer className="size-4" aria-hidden="true" />{t("latency")}</span>
          <span className="tabular-nums">{t("ms", { value: Math.round(total) })}</span>
        </div>
        <ul className="flex flex-wrap gap-x-3 gap-y-1 text-xs text-muted-foreground">
          {timings.map(([k, v]) => (
            <li key={k}>{t(`stages.${k}`)} <span className="tabular-nums">{t("ms", { value: Math.round(v) })}</span></li>
          ))}
        </ul>
      </div>
    </div>
  );
}

function Highlighted({ text, query }: { text: string; query: string }) {
  return (
    <>
      {highlight(text, query).map((s, i) =>
        s.match ? <mark key={i} className="rounded-sm bg-amber-200/70 px-0.5 text-inherit dark:bg-amber-400/30">{s.text}</mark> : <span key={i}>{s.text}</span>,
      )}
    </>
  );
}

function PassageCard({ passage: p, index, query, onOpen }: { passage: Passage; index: number; query: string; onOpen: () => void }) {
  const t = useTranslations("playground");
  return (
    <article className="nx-card space-y-2 p-4" data-testid="passage">
      <div className="flex items-start justify-between gap-3">
        <div className="flex min-w-0 items-start gap-2">
          <span className="inline-flex size-6 shrink-0 items-center justify-center rounded-md bg-muted text-xs font-semibold">{index}</span>
          <div className="min-w-0">
            <h3 className="truncate text-sm font-medium">{p.citation}</h3>
            <p className="text-xs text-muted-foreground">
              {t(`kinds.${p.kind}`)} · {t("tokens", { count: p.token_count })}
            </p>
          </div>
        </div>
        <Button variant="outline" size="sm" onClick={onOpen} aria-label={`${t("viewSource")}: ${p.citation}`}>
          <Quote className="size-3.5" aria-hidden="true" />
          {t("viewSource")}
        </Button>
      </div>
      <p className="line-clamp-4 text-sm whitespace-pre-line text-muted-foreground">
        <Highlighted text={p.text} query={query} />
      </p>
    </article>
  );
}

function SourcePreview({ passage: p, query, onClose }: { passage: Passage | null; query: string; onClose: () => void }) {
  const t = useTranslations("playground");
  return (
    <Sheet open={!!p} onOpenChange={(o) => !o && onClose()}>
      <SheetContent className="w-full overflow-y-auto sm:max-w-xl" data-testid="source-preview">
        {p ? (
          <>
            <SheetHeader>
              <SheetTitle>{p.title ?? p.citation}</SheetTitle>
              <SheetDescription>{p.citation}</SheetDescription>
            </SheetHeader>
            <div className="space-y-4 px-4 pb-6">
              <div className="flex flex-wrap gap-2">
                {isWebUri(p.source_uri) ? (
                  <Button asChild variant="outline" size="sm">
                    <a href={p.source_uri} target="_blank" rel="noreferrer noopener">
                      <ExternalLink className="size-3.5" aria-hidden="true" />
                      {t("openOriginal")}
                    </a>
                  </Button>
                ) : null}
                <Button asChild variant="outline" size="sm">
                  <Link href={`/knowledge/${p.collection_id}`}>
                    <BookOpenText className="size-3.5" aria-hidden="true" />
                    {t("openCollection")}
                  </Link>
                </Button>
              </div>
              <blockquote className="rounded-xl border-s-4 border-primary bg-muted/40 p-4 text-sm leading-relaxed whitespace-pre-line">
                <Highlighted text={p.text} query={query} />
              </blockquote>
              <p className="text-xs break-all text-muted-foreground" dir="ltr">{p.source_uri}</p>
            </div>
          </>
        ) : null}
      </SheetContent>
    </Sheet>
  );
}
