/** Evaluations (QA-01), the release gate (QA-02) and the fix loop (ST-14): types and pure helpers. */

import type { Tone } from "@/components/visual/icon-tile";

export interface TestSet {
  id: string;
  name: string;
  agent: string | null;
  description: string;
  origin: "manual" | "pack" | "conversations";
  evaluators: string[];
  revision: number;
  case_count: number;
  created_at: string;
  updated_at: string;
}

export interface CaseInput {
  question: string;
  lang?: string;
  expected_source?: string | null;
  expected_section?: string | null;
  expected_phrases?: string[];
  must_abstain?: boolean;
  origin?: Record<string, string>;
  notes?: string;
}

export interface TestCase extends Required<Omit<CaseInput, "expected_source" | "expected_section">> {
  id: string;
  expected_source: string | null;
  expected_section: string | null;
  created_at: string;
}

export interface Metric {
  mean: number;
  cases: number;
}

export interface Scorecard {
  cases: number;
  passed: number;
  failed: number;
  errors: number;
  pass_rate: number;
  metrics: Record<string, Metric>;
  by_lang: Record<string, { cases: number; pass_rate: number }>;
  latency_ms: { p50: number; p95: number };
  tokens: number;
  cost: number;
}

export interface EvalRun {
  id: string;
  agent: string;
  version: number;
  test_set_id: string;
  test_set_revision: number;
  spec_hash: string;
  current: boolean;
  status: "queued" | "running" | "completed" | "failed";
  started_by: string;
  case_count: number;
  done_count: number;
  scorecard: Scorecard | null;
  error: string | null;
  created_at: string;
  finished_at: string | null;
}

export interface CaseScore {
  value: number;
  passed: boolean;
  detail: string;
}

export interface EvalResult {
  case_id: string;
  question: string;
  lang: string;
  answer: string;
  abstained: boolean;
  kind: string | null;
  citations: { citation: string; source_uri: string | null }[];
  scores: Record<string, CaseScore>;
  passed: boolean;
  latency_ms: number;
  tokens: number;
  cost: number;
  agent_run_id: string | null;
  error: string | null;
}

export interface ReportRow {
  agent: string;
  version: number;
  test_set_id: string;
  test_set: string;
  run_id: string;
  current: boolean;
  scorecard: Scorecard;
  finished_at: string | null;
}

export interface GateReason {
  code: string; // messages: gate.reasons.<code>
  metric?: string;
  value?: number;
  limit?: number;
  test_set?: string;
}

export interface GateCheck {
  passed: boolean;
  reasons: GateReason[];
  deltas: Record<string, number>;
  test_set_id: string | null;
  run_id: string | null;
  baseline_run_id: string | null;
  scorecard: Scorecard | null;
  baseline_scorecard: Scorecard | null;
  thresholds: { min_pass_rate: number; max_drop: number };
}

export interface ReleaseGate {
  enabled: boolean;
  test_set: string;
  min_pass_rate?: number;
  max_drop?: number;
}

export const GATE_REASONS = [
  "not_evaluated",
  "stale",
  "below_threshold",
  "regression",
  "no_test_set",
  "changed_since_evaluation",
  "evaluation_unavailable",
] as const;

export const EVALUATORS = ["source-cited", "contains-facts", "abstention", "grounded"] as const;

export const pct = (value: number): number => Math.round(value * 1000) / 10;

export function percent(value: number): string {
  return `${pct(value)}%`;
}

/** "+3.4 pts" / "−1.2 pts": deltas are shown in percentage points, with a real minus sign. */
export function points(delta: number): string {
  const v = Math.round(delta * 1000) / 10;
  if (v === 0) return "±0 pts";
  return `${v > 0 ? "+" : "−"}${Math.abs(v)} pts`;
}

export function deltaTone(delta: number, allowance = 0): Tone {
  if (delta > 0.0005) return "teal";
  if (delta < -allowance - 1e-9) return "rose";
  if (delta < -0.0005) return "amber";
  return "slate";
}

export function passTone(rate: number, threshold = 0.8): Tone {
  if (rate >= threshold) return "teal";
  if (rate >= threshold - 0.15) return "amber";
  return "rose";
}

export function runIsActive(run: Pick<EvalRun, "status">): boolean {
  return run.status === "queued" || run.status === "running";
}

export function progress(run: Pick<EvalRun, "case_count" | "done_count">): number {
  return run.case_count ? Math.min(1, run.done_count / run.case_count) : 0;
}

/** What a case expects, as short tokens for a table cell (localised by the caller). */
export function expectation(c: Pick<TestCase, "must_abstain" | "expected_source" | "expected_section" | "expected_phrases">): {
  kind: "abstain" | "facts" | "source" | "any";
  source: string | null;
  phrases: string[];
} {
  if (c.must_abstain) return { kind: "abstain", source: null, phrases: [] };
  const source = c.expected_source ? [c.expected_source, c.expected_section].filter(Boolean).join(" › ") : null;
  if (c.expected_phrases.length) return { kind: "facts", source, phrases: c.expected_phrases };
  return { kind: source ? "source" : "any", source, phrases: [] };
}

/** Newest scorecard per version for one test set, newest version first. */
export function byVersion(rows: ReportRow[], testSet?: string): ReportRow[] {
  return rows.filter((r) => !testSet || r.test_set === testSet).sort((a, b) => b.version - a.version);
}

/** Metric changes between two scorecards (candidate − baseline), only where both have the metric. */
export function compare(card: Scorecard, base: Scorecard | null): Record<string, number> {
  if (!base) return {};
  const out: Record<string, number> = { pass_rate: card.pass_rate - base.pass_rate };
  for (const [name, m] of Object.entries(card.metrics)) {
    const before = base.metrics[name];
    if (before) out[name] = m.mean - before.mean;
  }
  return Object.fromEntries(Object.entries(out).map(([k, v]) => [k, Math.round(v * 10_000) / 10_000]));
}

/** A regression test case made from a bad answer (fix loop): what the right answer must say. */
export function caseFromAnswer(o: { question: string; lang?: string; phrases: string; runId?: string | null; mustAbstain?: boolean }): CaseInput {
  const phrases = o.phrases
    .split(/\n|;/)
    .map((p) => p.trim())
    .filter((p) => p.length > 0)
    .slice(0, 10);
  return {
    question: o.question.trim(),
    lang: (o.lang ?? "en").slice(0, 2),
    expected_phrases: o.mustAbstain ? [] : phrases,
    must_abstain: !!o.mustAbstain,
    origin: o.runId ? { kind: "run", ref: o.runId } : { kind: "manual" },
  };
}

/** The test set a fix-loop case goes to when the person has not picked one. */
export function regressionSetName(agent: string): string {
  return `${agent}-regressions`.slice(0, 63);
}
