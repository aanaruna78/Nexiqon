"use client";

import { Coins, Gauge, Languages, Timer } from "lucide-react";
import { useTranslations } from "next-intl";

import type { Tone } from "@/components/visual/icon-tile";
import { StatusBadge } from "@/components/visual/status-badge";
import { compare, deltaTone, EVALUATORS, passTone, pct, percent, points, type Scorecard } from "@/lib/evaluation";
import { cn } from "@/lib/utils";

const DOT: Partial<Record<Tone, string>> = { teal: "bg-teal-500", amber: "bg-amber-500", rose: "bg-rose-500" };

function barColour(value: number, threshold: number): string {
  if (value >= threshold) return "bg-teal-500";
  if (value >= threshold - 0.15) return "bg-amber-500";
  return "bg-rose-500";
}

/** One run's scorecard: pass rate, each evaluator, languages, speed and cost, and how each moved
 * against a baseline (the live version) when one is given. */
export function ScorecardView({
  card,
  baseline,
  threshold = 0.8,
  allowance = 0.05,
}: {
  card: Scorecard;
  baseline?: Scorecard | null;
  threshold?: number;
  allowance?: number;
}) {
  const t = useTranslations("evaluations");
  const deltas = compare(card, baseline ?? null);
  const order = (name: string) => {
    const i = (EVALUATORS as readonly string[]).indexOf(name);
    return i < 0 ? 99 : i;
  };
  const metrics = Object.keys(card.metrics).sort((a, b) => order(a) - order(b));
  const languages = Object.entries(card.by_lang)
    .map(([lang, v]) => `${lang} ${percent(v.pass_rate)}`)
    .join(" · ");
  return (
    <div className="space-y-4" data-testid="scorecard">
      <div className="grid gap-3 sm:grid-cols-2 lg:grid-cols-4">
        <Tile
          icon={Gauge}
          label={t("passRate")}
          value={percent(card.pass_rate)}
          hint={t("passedOf", { passed: card.passed, cases: card.cases })}
          tone={passTone(card.pass_rate, threshold)}
          delta={deltas.pass_rate}
          allowance={allowance}
        />
        <Tile icon={Timer} label={t("latency")} value={t("ms", { value: card.latency_ms.p50 })} hint={t("p95", { value: card.latency_ms.p95 })} />
        <Tile icon={Coins} label={t("cost")} value={`$${card.cost.toFixed(4)}`} hint={t("tokens", { count: card.tokens })} />
        <Tile icon={Languages} label={t("languages")} value={String(Object.keys(card.by_lang).length)} hint={languages} />
      </div>
      {card.errors ? <p className="text-sm text-destructive">{t("errors", { count: card.errors })}</p> : null}
      <ul className="nx-card divide-y" aria-label={t("metrics")}>
        {metrics.map((name) => {
          const m = card.metrics[name];
          const value = pct(m.mean);
          const d = deltas[name];
          const title = t.has(`evaluators.${name}.title`) ? t(`evaluators.${name}.title`) : name;
          return (
            <li key={name} className="grid gap-2 p-3 sm:grid-cols-[14rem_1fr_7rem] sm:items-center">
              <div className="min-w-0">
                <p className="text-sm font-medium">{title}</p>
                <p className="text-xs text-muted-foreground">{t("appliedTo", { count: m.cases })}</p>
              </div>
              <div className="h-2 overflow-hidden rounded-full bg-muted" role="meter" aria-valuemin={0} aria-valuemax={100} aria-valuenow={value} aria-label={title}>
                <div className={cn("h-full rounded-full", barColour(m.mean, threshold))} style={{ width: `${value}%` }} />
              </div>
              <div className="flex items-center justify-end gap-2 text-sm tabular-nums">
                <span>{value}%</span>
                {d !== undefined ? <StatusBadge tone={deltaTone(d, allowance)}>{points(d)}</StatusBadge> : null}
              </div>
            </li>
          );
        })}
      </ul>
    </div>
  );
}

function Tile({
  icon: Icon,
  label,
  value,
  hint,
  tone,
  delta,
  allowance = 0,
}: {
  icon: typeof Gauge;
  label: string;
  value: string;
  hint?: string;
  tone?: Tone;
  delta?: number;
  allowance?: number;
}) {
  return (
    <div className="nx-card space-y-1 p-3">
      <p className="flex items-center gap-1.5 text-xs text-muted-foreground">
        <Icon className="size-3.5" aria-hidden="true" />
        {label}
      </p>
      <p className="flex flex-wrap items-center gap-2 text-xl font-semibold tabular-nums">
        {tone ? <span className={cn("size-2 rounded-full", DOT[tone] ?? "bg-muted-foreground")} aria-hidden="true" /> : null}
        {value}
        {delta !== undefined ? <StatusBadge tone={deltaTone(delta, allowance)}>{points(delta)}</StatusBadge> : null}
      </p>
      {hint ? (
        <p className="truncate text-xs text-muted-foreground" title={hint}>
          {hint}
        </p>
      ) : null}
    </div>
  );
}
