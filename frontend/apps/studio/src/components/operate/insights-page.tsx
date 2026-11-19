"use client";

import { BellRing, ChartLine, Coins, Lightbulb, Target, Trash2, Wrench } from "lucide-react";
import { useTranslations } from "next-intl";
import { type FormEvent, useState } from "react";
import { toast } from "sonner";

import { FixAnswer, type FixTarget } from "@/components/fix/fix-answer";
import { PageHeader } from "@/components/page-header";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import { Select, SelectContent, SelectItem, SelectTrigger, SelectValue } from "@/components/ui/select";
import { Skeleton } from "@/components/ui/skeleton";
import { StatusBadge } from "@/components/visual/status-badge";
import { useErrorToast } from "@/lib/hooks";
import { bars, budgetTone, currentMonth, pctOrDash, RATES, rateTone, usd } from "@/lib/operate";
import { useBudgets, useGaps, useKpis, useQuality, useUsage } from "@/lib/operate-hooks";
import { useObjects } from "@/lib/studio-hooks";
import { cn } from "@/lib/utils";

const PERIODS = [7, 30, 90] as const;

/** Insights and cost (ST-18, UX G3 and G8): how well assistants answer, what they cannot answer
 * yet, and what it costs. */
export function InsightsPage() {
  const t = useTranslations("insights");
  const agents = useObjects("agent");
  const [agent, setAgent] = useState<string>("__all");
  const [days, setDays] = useState<number>(30);
  const chosen = agent === "__all" ? null : agent;
  return (
    <div className="space-y-8">
      <PageHeader title={t("title")} description={t("subtitle")} icon={ChartLine} tone="violet" />
      <div className="flex flex-wrap gap-4">
        <div className="space-y-1">
          <Label htmlFor="ins-agent" className="text-xs text-muted-foreground">{t("assistant")}</Label>
          <Select value={agent} onValueChange={setAgent}>
            <SelectTrigger id="ins-agent" className="w-52" data-testid="insights-agent"><SelectValue /></SelectTrigger>
            <SelectContent>
              <SelectItem value="__all">{t("allAssistants")}</SelectItem>
              {(agents.data ?? []).map((a) => <SelectItem key={a.name} value={a.name}>{a.name}</SelectItem>)}
            </SelectContent>
          </Select>
        </div>
        <div className="space-y-1">
          <Label htmlFor="ins-days" className="text-xs text-muted-foreground">{t("period")}</Label>
          <Select value={String(days)} onValueChange={(v) => setDays(Number(v))}>
            <SelectTrigger id="ins-days" className="w-40"><SelectValue /></SelectTrigger>
            <SelectContent>
              {PERIODS.map((d) => <SelectItem key={d} value={String(d)}>{t("lastDays", { days: d })}</SelectItem>)}
            </SelectContent>
          </Select>
        </div>
      </div>
      <QualitySection agent={chosen} days={days} />
      {chosen ? <KpiSection agent={chosen} days={days} /> : null}
      <GapSection agent={chosen} days={days} />
      <CostSection agent={chosen} />
    </div>
  );
}

function Section({ id, icon: Icon, title, help, children }: { id: string; icon: typeof ChartLine; title: string; help?: string; children: React.ReactNode }) {
  return (
    <section aria-labelledby={id} className="space-y-3">
      <div>
        <h2 id={id} className="flex items-center gap-2 font-semibold">
          <Icon className="size-4" aria-hidden="true" />
          {title}
        </h2>
        {help ? <p className="text-sm text-muted-foreground">{help}</p> : null}
      </div>
      {children}
    </section>
  );
}

/** A small bar chart with the same numbers as a table for screen readers. */
function Bars({ label, series }: { label: string; series: { key: string; value: number; text: string }[] }) {
  const heights = bars(series.map((s) => s.value));
  return (
    <figure className="space-y-1">
      <div className="flex h-24 items-end gap-0.5" aria-hidden="true">
        {series.map((s, i) => (
          <div key={s.key} className="flex-1 rounded-t bg-primary/70" style={{ height: `${Math.max(2, heights[i] * 100)}%` }} title={`${s.key}: ${s.text}`} />
        ))}
      </div>
      <figcaption className="text-xs text-muted-foreground">{label}</figcaption>
      <table className="sr-only">
        <caption>{label}</caption>
        <tbody>
          {series.map((s) => (
            <tr key={s.key}>
              <th scope="row">{s.key}</th>
              <td>{s.text}</td>
            </tr>
          ))}
        </tbody>
      </table>
    </figure>
  );
}

function QualitySection({ agent, days }: { agent: string | null; days: number }) {
  const t = useTranslations("insights");
  const q = useQuality(agent, days);
  return (
    <Section id="quality" icon={ChartLine} title={t("quality")} help={t("qualityHelp")}>
      {q.isLoading ? <Skeleton className="h-40" /> : null}
      {q.data ? (
        <>
          <dl className="grid gap-3 sm:grid-cols-2 lg:grid-cols-5" data-testid="quality-rates">
            {RATES.map((r) => {
              const now = q.data.rates[r];
              const before = q.data.previous_rates[r];
              return (
                <div key={r} className="nx-card space-y-1 p-3">
                  <dt className="text-xs text-muted-foreground">{t(`rates.${r}`)}</dt>
                  <dd className="text-xl font-semibold tabular-nums">{pctOrDash(now)}</dd>
                  <dd>
                    <StatusBadge tone={rateTone(r, now, before)}>{before === null ? t("noEarlier") : t("before", { value: pctOrDash(before) })}</StatusBadge>
                  </dd>
                </div>
              );
            })}
          </dl>
          <p className="text-sm text-muted-foreground">
            {t("totals", { conversations: q.data.totals.conversations ?? 0, turns: q.data.totals.turns ?? 0, escalations: q.data.totals.escalations ?? 0 })}
          </p>
          {q.data.daily.length ? (
            <div className="nx-card p-4">
              <Bars label={t("turnsPerDay")} series={q.data.daily.map((d) => ({ key: d.day, value: d.metrics.turns ?? 0, text: String(d.metrics.turns ?? 0) }))} />
            </div>
          ) : (
            <p className="text-sm text-muted-foreground">{t("noActivity")}</p>
          )}
        </>
      ) : null}
    </Section>
  );
}

function KpiSection({ agent, days }: { agent: string; days: number }) {
  const t = useTranslations("insights");
  const k = useKpis(agent, days);
  if (k.isLoading) return <Skeleton className="h-24" />;
  if (!k.data?.length) return null;
  return (
    <Section id="kpis" icon={Target} title={t("kpis")} help={t("kpisHelp")}>
      <dl className="grid gap-3 sm:grid-cols-2 lg:grid-cols-3" data-testid="kpis">
        {k.data.map((x) => (
          <div key={x.name} className="nx-card space-y-1 p-3">
            <dt className="text-sm font-medium">{x.name.replace(/_/g, " ")}</dt>
            <dd className="text-xl font-semibold tabular-nums">{pctOrDash(x.value)}</dd>
            <dd className="text-xs text-muted-foreground">{x.description} · {t("ofConversations", { count: x.count, total: x.conversations })}</dd>
          </div>
        ))}
      </dl>
    </Section>
  );
}

function GapSection({ agent, days }: { agent: string | null; days: number }) {
  const t = useTranslations("insights");
  const g = useGaps(agent, days);
  const [fix, setFix] = useState<FixTarget | null>(null);
  return (
    <Section id="gaps" icon={Lightbulb} title={t("gaps")} help={t("gapsHelp")}>
      {g.isLoading ? <Skeleton className="h-32" /> : null}
      {g.error ? <p className="text-sm text-muted-foreground">{t("gapsUnavailable")}</p> : null}
      {g.data && !g.data.topics.length ? <p className="text-sm text-muted-foreground">{t("noGaps")}</p> : null}
      {g.data?.topics.length ? (
        <ol className="space-y-3" data-testid="gap-topics">
          {g.data.topics.map((topic, i) => (
            <li key={i} className="nx-card space-y-2 p-4">
              <div className="flex flex-wrap items-center justify-between gap-2">
                <p className="font-medium">{t("topic", { terms: topic.label.join(", ") })}</p>
                <span className="flex flex-wrap gap-1.5">
                  <StatusBadge tone="violet">{t("asked", { count: topic.count })}</StatusBadge>
                  {Object.entries(topic.reasons).map(([reason, n]) => (
                    <StatusBadge key={reason} tone={reason === "escalated" ? "rose" : reason === "not_helpful" ? "amber" : "slate"}>{t(`reasons.${reason}`, { count: n })}</StatusBadge>
                  ))}
                </span>
              </div>
              <ul className="list-disc space-y-0.5 ps-5 text-sm text-muted-foreground">
                {topic.examples.slice(0, 3).map((q) => <li key={q} dir="auto">{q}</li>)}
              </ul>
              {agent ? (
                <Button variant="outline" size="sm" onClick={() => setFix({ agent, question: topic.example, runId: null })} data-testid="gap-fix">
                  <Wrench className="size-4" aria-hidden="true" />
                  {t("answerThis")}
                </Button>
              ) : null}
            </li>
          ))}
        </ol>
      ) : null}
      {g.data && !agent && g.data.topics.length ? <p className="text-xs text-muted-foreground">{t("pickToFix")}</p> : null}
      <FixAnswer target={fix} onClose={() => setFix(null)} />
    </Section>
  );
}

function CostSection({ agent }: { agent: string | null }) {
  const t = useTranslations("insights");
  const onError = useErrorToast();
  const month = currentMonth();
  const usage = useUsage(month, agent);
  const { budgets, alerts, save, remove, acknowledge } = useBudgets();
  const [limit, setLimit] = useState("");
  const [scope, setScope] = useState<string>("__org");
  const agents = useObjects("agent");

  async function add(e: FormEvent) {
    e.preventDefault();
    try {
      await save.mutateAsync({ agent: scope === "__org" ? null : scope, monthly_usd: limit });
      setLimit("");
      toast.success(t("budgetSaved"));
    } catch (error) {
      onError(error);
    }
  }

  const open = (alerts.data ?? []).filter((a) => !a.acknowledged_at);
  return (
    <Section id="cost" icon={Coins} title={t("cost")} help={t("costHelp", { month })}>
      {open.length ? (
        <ul className="space-y-2" data-testid="budget-alerts">
          {open.map((a) => (
            <li key={a.id} role="status" className="flex flex-wrap items-center justify-between gap-2 rounded-xl border border-amber-500 bg-amber-50 p-3 text-sm dark:bg-amber-950">
              <span className="flex items-center gap-2">
                <BellRing className="size-4" aria-hidden="true" />
                {t("alert", { who: a.agent ?? t("organization"), pct: Math.round(a.threshold * 100), spent: usd(a.spent_usd), limit: usd(a.limit_usd) })}
              </span>
              <Button variant="outline" size="sm" onClick={() => acknowledge.mutate(a.id, { onError })}>{t("acknowledge")}</Button>
            </li>
          ))}
        </ul>
      ) : null}
      {usage.isLoading ? <Skeleton className="h-32" /> : null}
      {usage.data ? (
        <div className="grid gap-4 lg:grid-cols-[1fr_20rem]">
          <div className="nx-card space-y-3 p-4">
            <p className="text-2xl font-semibold tabular-nums" data-testid="month-cost">{usd(usage.data.cost_usd)}</p>
            <p className="text-sm text-muted-foreground">{t("tokens", { tokens: (usage.data.input_tokens + usage.data.output_tokens).toLocaleString(), calls: usage.data.calls })}</p>
            {usage.data.daily.length ? <Bars label={t("costPerDay")} series={usage.data.daily.map((d) => ({ key: d.day, value: Number(d.cost_usd), text: usd(d.cost_usd, 4) }))} /> : null}
          </div>
          <div className="nx-card space-y-2 p-4">
            <h3 className="text-sm font-medium">{agent ? t("byModel") : t("byAssistant")}</h3>
            <ul className="space-y-1 text-sm" data-testid="cost-breakdown">
              {(agent ? usage.data.by_model : usage.data.by_agent).slice(0, 8).map((g) => (
                <li key={g.key} className="flex justify-between gap-2">
                  <span className="truncate">{g.key || t("noAssistant")}</span>
                  <span className="tabular-nums">{usd(g.cost_usd, 4)}</span>
                </li>
              ))}
              {!usage.data.by_agent.length ? <li className="text-muted-foreground">{t("noSpend")}</li> : null}
            </ul>
          </div>
        </div>
      ) : null}
      <div className="nx-card space-y-3 p-4">
        <h3 className="font-medium">{t("budgets")}</h3>
        <ul className="space-y-3" data-testid="budgets">
          {(budgets.data ?? []).map((b) => (
            <li key={b.id} className="space-y-1 text-sm">
              <div className="flex flex-wrap items-center justify-between gap-2">
                <span className="font-medium">{b.agent ?? t("organization")}</span>
                <span className="flex items-center gap-2">
                  <span className="tabular-nums">{t("spentOf", { spent: usd(b.spent_usd), limit: usd(b.monthly_usd) })}</span>
                  <Button variant="ghost" size="icon" aria-label={t("removeBudget", { who: b.agent ?? t("organization") })} onClick={() => remove.mutate(b.id, { onError })}>
                    <Trash2 className="size-4" aria-hidden="true" />
                  </Button>
                </span>
              </div>
              <div className="h-2 overflow-hidden rounded-full bg-muted" role="meter" aria-valuemin={0} aria-valuemax={100} aria-valuenow={Math.round(Math.min(1, b.used) * 100)} aria-label={t("budgetUse", { who: b.agent ?? t("organization") })}>
                <div className={cn("h-full rounded-full", { teal: "bg-teal-500", amber: "bg-amber-500", rose: "bg-rose-500" }[budgetTone(b.used) as "teal"] ?? "bg-primary")} style={{ width: `${Math.min(100, b.used * 100)}%` }} />
              </div>
            </li>
          ))}
          {budgets.data && !budgets.data.length ? <li className="text-sm text-muted-foreground">{t("noBudgets")}</li> : null}
        </ul>
        <form onSubmit={add} className="flex flex-wrap items-end gap-3">
          <div className="space-y-1">
            <Label htmlFor="budget-scope">{t("budgetFor")}</Label>
            <Select value={scope} onValueChange={setScope}>
              <SelectTrigger id="budget-scope" className="w-48"><SelectValue /></SelectTrigger>
              <SelectContent>
                <SelectItem value="__org">{t("organization")}</SelectItem>
                {(agents.data ?? []).map((a) => <SelectItem key={a.name} value={a.name}>{a.name}</SelectItem>)}
              </SelectContent>
            </Select>
          </div>
          <div className="space-y-1">
            <Label htmlFor="budget-limit">{t("monthlyLimit")}</Label>
            <Input id="budget-limit" type="number" min="1" step="0.01" className="w-32" value={limit} onChange={(e) => setLimit(e.target.value)} data-testid="budget-limit" />
          </div>
          <Button type="submit" disabled={!(Number(limit) > 0) || save.isPending} data-testid="save-budget">{t("setBudget")}</Button>
        </form>
        <p className="text-xs text-muted-foreground">{t("budgetHelp")}</p>
      </div>
    </Section>
  );
}
