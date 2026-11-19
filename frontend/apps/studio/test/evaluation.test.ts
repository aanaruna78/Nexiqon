import { describe, expect, it } from "vitest";

import {
  byVersion,
  caseFromAnswer,
  compare,
  deltaTone,
  EVALUATORS,
  expectation,
  GATE_REASONS,
  passTone,
  percent,
  points,
  progress,
  regressionSetName,
  type ReportRow,
  runIsActive,
  type Scorecard,
} from "@/lib/evaluation";

import ar from "../messages/ar.json";
import en from "../messages/en.json";

const card = (rate: number, metrics: Record<string, number> = {}): Scorecard => ({
  cases: 10,
  passed: Math.round(rate * 10),
  failed: 10 - Math.round(rate * 10),
  errors: 0,
  pass_rate: rate,
  metrics: Object.fromEntries(Object.entries(metrics).map(([k, mean]) => [k, { mean, cases: 10 }])),
  by_lang: { en: { cases: 10, pass_rate: rate } },
  latency_ms: { p50: 900, p95: 2100 },
  tokens: 1000,
  cost: 0.01,
});

describe("scores and deltas", () => {
  it("formats rates and percentage-point changes", () => {
    expect(percent(0.75)).toBe("75%");
    expect(percent(0.8333)).toBe("83.3%");
    expect(points(0.034)).toBe("+3.4 pts");
    expect(points(-0.1)).toBe("−10 pts");
    expect(points(0)).toBe("±0 pts");
  });

  it("colours changes by whether they stay within the allowance", () => {
    expect(deltaTone(0.02)).toBe("teal");
    expect(deltaTone(-0.03, 0.05)).toBe("amber");
    expect(deltaTone(-0.1, 0.05)).toBe("rose");
    expect(deltaTone(0)).toBe("slate");
    expect(passTone(0.9)).toBe("teal");
    expect(passTone(0.7)).toBe("amber");
    expect(passTone(0.4)).toBe("rose");
  });

  it("compares a candidate with the live version only where both were measured", () => {
    const d = compare(card(0.8, { grounded: 0.9, abstention: 1 }), card(0.9, { grounded: 1 }));
    expect(d).toEqual({ pass_rate: -0.1, grounded: -0.1 });
    expect(compare(card(0.8), null)).toEqual({});
  });

  it("lists the newest version first, optionally for one test set", () => {
    const row = (version: number, set: string): ReportRow => ({ agent: "a", version, test_set_id: set, test_set: set, run_id: `${version}`, current: true, scorecard: card(1), finished_at: null });
    expect(byVersion([row(1, "x"), row(3, "x"), row(2, "y")]).map((r) => r.version)).toEqual([3, 2, 1]);
    expect(byVersion([row(1, "x"), row(3, "x"), row(2, "y")], "x").map((r) => r.version)).toEqual([3, 1]);
  });

  it("tracks a run's progress", () => {
    expect(runIsActive({ status: "running" })).toBe(true);
    expect(runIsActive({ status: "completed" })).toBe(false);
    expect(progress({ case_count: 4, done_count: 1 })).toBe(0.25);
    expect(progress({ case_count: 0, done_count: 0 })).toBe(0);
  });
});

describe("cases", () => {
  it("summarises what a case expects", () => {
    expect(expectation({ must_abstain: true, expected_source: "x.md", expected_section: null, expected_phrases: ["a"] }).kind).toBe("abstain");
    const facts = expectation({ must_abstain: false, expected_source: "billing.md", expected_section: "Plans", expected_phrases: ["12 dollars"] });
    expect(facts).toEqual({ kind: "facts", source: "billing.md › Plans", phrases: ["12 dollars"] });
    expect(expectation({ must_abstain: false, expected_source: "a.md", expected_section: null, expected_phrases: [] }).kind).toBe("source");
    expect(expectation({ must_abstain: false, expected_source: null, expected_section: null, expected_phrases: [] }).kind).toBe("any");
  });

  it("turns a fixed answer into a regression case", () => {
    const c = caseFromAnswer({ question: "  How long are backups kept? ", lang: "en-GB", phrases: "90 days\n\n kept ; ", runId: "r-1" });
    expect(c).toEqual({ question: "How long are backups kept?", lang: "en", expected_phrases: ["90 days", "kept"], must_abstain: false, origin: { kind: "run", ref: "r-1" } });
    const abstain = caseFromAnswer({ question: "Who is the CEO?", phrases: "ignored", mustAbstain: true });
    expect(abstain.expected_phrases).toEqual([]);
    expect(abstain.must_abstain).toBe(true);
    expect(abstain.origin).toEqual({ kind: "manual" });
    expect(regressionSetName("support")).toBe("support-regressions");
    expect(regressionSetName("x".repeat(70)).length).toBe(63);
  });
});

describe("messages", () => {
  it("explain every gate reason and evaluator in both languages", () => {
    for (const messages of [en, ar]) {
      for (const code of GATE_REASONS) expect(messages.gate.reasons[code]).toBeTruthy();
      for (const name of EVALUATORS) {
        expect(messages.evaluations.evaluators[name].title).toBeTruthy();
        expect(messages.gate.metrics[name]).toBeTruthy();
      }
    }
  });
});
