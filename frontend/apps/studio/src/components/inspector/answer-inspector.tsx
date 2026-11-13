"use client";

import { CircleAlert, Coins, Cpu, Gauge, Lightbulb, ListTree, Timer, Wrench } from "lucide-react";
import { useTranslations } from "next-intl";

import { GraphView } from "@/components/graph/graph-view";
import { Alert, AlertTitle } from "@/components/ui/alert";
import { Sheet, SheetContent, SheetDescription, SheetHeader, SheetTitle } from "@/components/ui/sheet";
import { Skeleton } from "@/components/ui/skeleton";
import { StatusBadge } from "@/components/visual/status-badge";
import { activePath, explainRun, type Graph, type RunStep, type RunTrace, totalMs } from "@/lib/studio";
import { useResolvedAgent, useRun } from "@/lib/studio-hooks";
import { cn } from "@/lib/utils";

/** Answer Inspector (ST-07, UX G1): why an answer happened, in under three minutes. */
export function AnswerInspector({ runId, onClose }: { runId: string | null; onClose: () => void }) {
  const t = useTranslations("inspector");
  const run = useRun(runId);
  return (
    <Sheet open={!!runId} onOpenChange={(o) => !o && onClose()}>
      <SheetContent className="w-full overflow-y-auto sm:max-w-2xl" data-testid="inspector">
        <SheetHeader>
          <SheetTitle>{t("title")}</SheetTitle>
          <SheetDescription>{t("subtitle")}</SheetDescription>
        </SheetHeader>
        <div className="space-y-6 px-4 pb-8">
          {run.isLoading ? <Skeleton className="h-96" /> : null}
          {run.error ? (
            <Alert variant="destructive">
              <CircleAlert className="size-4" aria-hidden="true" />
              <AlertTitle>{t("unavailable")}</AlertTitle>
            </Alert>
          ) : null}
          {run.data ? <InspectorBody trace={run.data} /> : null}
        </div>
      </SheetContent>
    </Sheet>
  );
}

export function InspectorBody({ trace }: { trace: RunTrace }) {
  const t = useTranslations("inspector");
  const resolved = useResolvedAgent(trace.agent);
  const usage = trace.result.usage;
  const why = explainRun(trace);
  const ms = totalMs(trace);
  const retrieve = trace.steps.find((s) => s.type === "retrieve");
  const sources = (retrieve?.sources as { citation: string; score: number; classification: string }[] | undefined) ?? [];
  const cited = new Set((trace.result.answer?.citations ?? []).map((c) => c.citation));
  const tools = trace.steps.filter((s) => s.type === "call_tool");
  const slowest = Math.max(1, ...trace.steps.map((s) => Number(s.ms) || 0));

  return (
    <>
      <dl className="grid grid-cols-2 gap-3 sm:grid-cols-4" data-testid="inspector-facts">
        <Fact icon={Gauge} label={t("status")} value={t(`statuses.${trace.status}`)} />
        <Fact icon={Timer} label={t("time")} value={t("ms", { value: ms })} />
        <Fact icon={Cpu} label={t("model")} value={usage?.model ? `${usage.model}` : "—"} hint={usage?.profile ?? undefined} />
        <Fact
          icon={Coins}
          label={t("cost")}
          value={usage ? `$${usage.cost_usd.toFixed(4)}` : "—"}
          hint={usage ? t("tokens", { input: usage.input_tokens, output: usage.output_tokens, calls: usage.model_calls }) : undefined}
        />
      </dl>

      <section aria-labelledby="why" className="nx-card space-y-3 p-4">
        <h3 id="why" className="flex items-center gap-2 font-semibold">
          <Lightbulb className="size-4 text-primary" aria-hidden="true" />
          {t("whyTitle")}
        </h3>
        <ol className="space-y-2" data-testid="why">
          {why.map((w, i) => (
            <li key={i} className="flex items-start gap-2 text-sm">
              <span className={cn("mt-1.5 size-2 shrink-0 rounded-full", { teal: "bg-teal-500", amber: "bg-amber-500", rose: "bg-rose-500", sky: "bg-sky-500", violet: "bg-violet-500", navy: "bg-slate-500", slate: "bg-muted-foreground" }[w.tone])} aria-hidden="true" />
              <span>{t(`why.${w.key}`, w.values ?? {})}</span>
            </li>
          ))}
        </ol>
      </section>

      {trace.result.answer?.text ? (
        <section aria-labelledby="answer" className="space-y-2">
          <h3 id="answer" className="font-semibold">{t("answer")}</h3>
          <blockquote className="rounded-xl border-s-4 border-primary bg-muted/40 p-3 text-sm whitespace-pre-line">{trace.result.answer.text}</blockquote>
        </section>
      ) : null}

      {sources.length ? (
        <section aria-labelledby="sources" className="space-y-2">
          <h3 id="sources" className="font-semibold">{t("sources", { count: sources.length })}</h3>
          <ul className="space-y-2" data-testid="inspector-sources">
            {sources.map((s, i) => {
              const pct = Math.round(Math.max(0, Math.min(1, Number(s.score) || 0)) * 100);
              return (
                <li key={i} className="space-y-1 text-sm">
                  <div className="flex flex-wrap items-center justify-between gap-2">
                    <span className="font-medium">{s.citation}</span>
                    <span className="flex items-center gap-2">
                      {cited.has(s.citation) ? <StatusBadge tone="teal">{t("cited")}</StatusBadge> : null}
                      <StatusBadge tone="slate">{s.classification}</StatusBadge>
                      <span className="tabular-nums text-muted-foreground">{(Number(s.score) || 0).toFixed(3)}</span>
                    </span>
                  </div>
                  <div className="h-1.5 overflow-hidden rounded-full bg-muted" role="meter" aria-valuemin={0} aria-valuemax={100} aria-valuenow={pct} aria-label={t("score", { citation: s.citation })}>
                    <div className="h-full rounded-full bg-primary" style={{ width: `${pct}%` }} />
                  </div>
                </li>
              );
            })}
          </ul>
          <p className="text-xs text-muted-foreground">{t("aclNote")}</p>
        </section>
      ) : null}

      {tools.length ? (
        <section aria-labelledby="tools" className="space-y-2">
          <h3 id="tools" className="flex items-center gap-2 font-semibold">
            <Wrench className="size-4" aria-hidden="true" />
            {t("tools")}
          </h3>
          <ul className="space-y-1 text-sm">
            {tools.map((s, i) => (
              <li key={i} className="flex items-center gap-2">
                <StatusBadge tone={s.ok ? "teal" : "rose"}>{s.ok ? t("ok") : String(s.error ?? t("failedShort"))}</StatusBadge>
                <span className="font-medium">{String(s.tool ?? "—")}</span>
                <span className="text-muted-foreground tabular-nums">{t("ms", { value: Math.round(s.ms) })}</span>
              </li>
            ))}
          </ul>
        </section>
      ) : null}

      <section aria-labelledby="path" className="space-y-2">
        <h3 id="path" className="flex items-center gap-2 font-semibold">
          <ListTree className="size-4" aria-hidden="true" />
          {t("path")}
        </h3>
        {resolved.data?.graph ? <GraphView graph={resolved.data.graph as Graph} active={activePath(trace.steps)} /> : null}
        <ol className="space-y-1.5" data-testid="steps">
          {trace.steps.map((s, i) => (
            <StepRow key={i} step={s} slowest={slowest} />
          ))}
        </ol>
      </section>

      <p className="text-xs text-muted-foreground">
        {t("versions", { versions: Object.entries(trace.agent_versions).map(([k, v]) => `${k} v${v}`).join(", "), id: trace.id })}
      </p>
    </>
  );
}

function StepRow({ step, slowest }: { step: RunStep; slowest: number }) {
  const t = useTranslations("inspector");
  const tg = useTranslations("graph");
  const width = Math.max(2, Math.round(((Number(step.ms) || 0) / slowest) * 100));
  return (
    <li className="grid grid-cols-[8rem_1fr_4.5rem] items-center gap-2 text-sm">
      <span className="truncate">
        <span className="font-medium">{step.node}</span> <span className="text-xs text-muted-foreground">{tg(`types.${step.type}`)}</span>
      </span>
      <span className="flex items-center gap-2">
        <span className="h-2 rounded-full bg-primary/70" style={{ width: `${width}%` }} aria-hidden="true" />
        {step.outcome ? <span className="text-xs text-muted-foreground">{step.outcome}</span> : null}
      </span>
      <span className="text-end tabular-nums text-muted-foreground">{t("ms", { value: Math.round(Number(step.ms) || 0) })}</span>
    </li>
  );
}

function Fact({ icon: Icon, label, value, hint }: { icon: typeof Gauge; label: string; value: string; hint?: string }) {
  return (
    <div className="nx-card space-y-1 p-3">
      <dt className="flex items-center gap-1.5 text-xs text-muted-foreground">
        <Icon className="size-3.5" aria-hidden="true" />
        {label}
      </dt>
      <dd className="truncate font-semibold" title={value}>{value}</dd>
      {hint ? <dd className="truncate text-xs text-muted-foreground">{hint}</dd> : null}
    </div>
  );
}
