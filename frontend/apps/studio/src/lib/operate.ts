/** Conversations review (ST-16), insights and cost (ST-18): types and pure helpers. */

import type { Tone } from "@/components/visual/icon-tile";

export interface Conversation {
  id: string;
  agent: string;
  channel: string;
  locale: string;
  actor_id: string;
  status: string;
  title: string | null;
  handoff_summary: string | null;
  created_at: string;
  last_message_at: string | null;
  retain_until: string | null;
  queue_status: "open" | "claimed" | "resolved" | null;
  assignee: string | null;
  resolved_at: string | null;
}

export interface ConversationMessage {
  id: string;
  role: "user" | "assistant" | "staff";
  content: string;
  contract: {
    kind?: string;
    abstained?: boolean;
    citations?: { marker: string; citation: string }[];
    author?: string;
    route?: string;
  };
  run_id: string | null;
  created_at: string;
}

export interface ConversationDetail extends Conversation {
  messages: ConversationMessage[];
}

export interface UsageGroup {
  key: string;
  calls: number;
  input_tokens: number;
  output_tokens: number;
  cost_usd: string;
}

export interface UsageSummary {
  month: string;
  calls: number;
  input_tokens: number;
  output_tokens: number;
  cost_usd: string;
  by_agent: UsageGroup[];
  by_model: UsageGroup[];
  by_profile: UsageGroup[];
  daily: { day: string; calls: number; tokens: number; cost_usd: string }[];
}

export interface Budget {
  id: string;
  agent: string | null;
  monthly_usd: string;
  thresholds: number[];
  month: string;
  spent_usd: string;
  used: number;
}

export interface BudgetAlert {
  id: string;
  agent: string | null;
  month: string;
  threshold: number;
  spent_usd: string;
  limit_usd: string;
  created_at: string;
  acknowledged_at: string | null;
}

export type RateName = "answer_rate" | "citation_rate" | "escalation_rate" | "satisfaction" | "tool_error_rate";

export interface Quality {
  days: number;
  agent: string | null;
  totals: Record<string, number>;
  rates: Record<RateName, number | null>;
  previous_rates: Record<RateName, number | null>;
  daily: { day: string; metrics: Record<string, number> }[];
}

export interface Kpi {
  name: string;
  description: string;
  event: string;
  value: number | null;
  count: number;
  conversations: number;
}

export interface GapTopic {
  label: string[];
  count: number;
  reasons: Record<string, number>;
  example: string;
  examples: string[];
  conversations: string[];
}

export interface GapReport {
  days: number;
  agent: string | null;
  questions: number;
  topics: GapTopic[];
}

export const RATES: RateName[] = ["answer_rate", "citation_rate", "escalation_rate", "satisfaction", "tool_error_rate"];
/** Rates where going down is good. */
const LOWER_IS_BETTER = new Set<RateName>(["escalation_rate", "tool_error_rate"]);

export function rateTone(name: RateName, now: number | null, before: number | null): Tone {
  if (now === null || before === null) return "slate";
  const diff = now - before;
  if (Math.abs(diff) < 0.005) return "slate";
  const better = LOWER_IS_BETTER.has(name) ? diff < 0 : diff > 0;
  return better ? "teal" : "rose";
}

export function pctOrDash(v: number | null | undefined): string {
  return v === null || v === undefined ? "—" : `${Math.round(v * 1000) / 10}%`;
}

export function usd(v: string | number, digits = 2): string {
  const n = typeof v === "string" ? Number(v) : v;
  return `$${n.toLocaleString("en-US", { minimumFractionDigits: digits, maximumFractionDigits: digits })}`;
}

export function budgetTone(used: number): Tone {
  if (used >= 1) return "rose";
  if (used >= 0.8) return "amber";
  return "teal";
}

/** Bar heights (0..1) for a series, scaled to its largest value. */
export function bars(values: number[]): number[] {
  const max = Math.max(0, ...values);
  return values.map((v) => (max > 0 ? v / max : 0));
}

/** Who needs someone first: open before claimed, then the longest waiting. */
export function queueOrder(items: Conversation[]): Conversation[] {
  const rank = (c: Conversation) => (c.queue_status === "open" ? 0 : c.queue_status === "claimed" ? 1 : 2);
  const at = (c: Conversation) => c.last_message_at ?? c.created_at;
  return [...items].sort((a, b) => rank(a) - rank(b) || at(a).localeCompare(at(b)));
}

/** The question that led to a given assistant message (for "Fix this answer"). */
export function questionBefore(messages: ConversationMessage[], index: number): string | null {
  for (let i = index - 1; i >= 0; i--) if (messages[i].role === "user") return messages[i].content;
  return null;
}

export function currentMonth(now = new Date()): string {
  return `${now.getUTCFullYear()}-${String(now.getUTCMonth() + 1).padStart(2, "0")}`;
}
