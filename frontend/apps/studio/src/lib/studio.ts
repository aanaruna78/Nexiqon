/** Assistants, Domain Packs, actions and models: types (mirroring contracts/openapi) and pure helpers. */

import type { Tone } from "@/components/visual/icon-tile";

// ------------------------------------------------------------------ configuration objects

export interface VersionInfo {
  version: number;
  status: "draft" | "published";
  notes?: string;
  created_by?: string;
  created_at?: string;
  published_at?: string | null;
}

export interface ConfigObject {
  kind: string;
  name: string;
  description: string;
  versions: VersionInfo[];
  deployments: Record<string, number>;
}

export interface VersionDetail extends VersionInfo {
  spec: Record<string, unknown>;
}

export interface Change {
  op: "add" | "remove" | "replace";
  path: string;
  old?: unknown;
  new?: unknown;
}

export interface DeploymentEvent {
  environment: string;
  from_version: number | null;
  to_version: number;
  actor: string;
  reason: string;
  at: string;
}

export type Localised = Record<string, string>;

export interface AgentSpec {
  pack: { name: string; version?: number };
  display_name: string;
  description?: string;
  model_profile?: string;
  retrieval_profile?: string;
  retention_profile?: string;
  knowledge?: { collections?: string[] };
  tools?: string[];
  behaviour?: { tone?: string; product_name?: string; [k: string]: unknown };
  guardrails?: Record<string, unknown>;
  escalation?: Record<string, unknown>;
  [k: string]: unknown;
}

export interface Intent {
  name: string;
  description?: string;
  route: "knowledge" | "action" | "handoff" | "smalltalk";
  tools?: string[];
  examples?: string[];
}

export interface GraphNode {
  id: string;
  type: string;
  config?: Record<string, unknown>;
}

export interface GraphEdge {
  from: string;
  to: string;
  when?: string | null;
}

export interface Graph {
  entry: string;
  nodes: GraphNode[];
  edges: GraphEdge[];
}

export interface Prompt {
  variables?: string[];
  template: string | Localised;
}

export interface PackSpec {
  metadata: { title: string; description?: string; pack_version: string; locales?: string[] };
  vocabulary?: Record<string, Localised>;
  intents: Intent[];
  graph: Graph;
  prompts: Record<string, Prompt>;
  tools?: { name: string; risk_level?: string; confirmation?: string }[];
  guardrails: {
    allowed_topics?: string[];
    blocked_topics?: string[];
    min_evidence_score?: number;
    max_answer_tokens?: number;
    pii_redaction?: boolean;
    cite_sources?: boolean;
  };
  escalation?: { on_low_evidence?: boolean; on_user_request?: boolean; after_failed_turns?: number; handoff_tool?: string };
  channels?: {
    widget?: { title?: Localised; greeting?: Localised; starter_questions?: Record<string, string[]>; accent_color?: string };
  };
  [k: string]: unknown;
}

export const NAME_PATTERN = /^[a-z0-9][a-z0-9-]{1,62}$/;

export function slugify(text: string): string {
  return text
    .toLowerCase()
    .normalize("NFKD")
    .replace(/[^a-z0-9]+/g, "-")
    .replace(/^-+|-+$/g, "")
    .slice(0, 63);
}

/** Which version is live in an environment, and whether a newer published one is waiting. */
export function releaseState(obj: ConfigObject, environment = "dev"): {
  live: number | null;
  latest: VersionInfo | undefined;
  latestPublished: VersionInfo | undefined;
  draft: VersionInfo | undefined;
  previousPublished: VersionInfo | undefined;
} {
  const live = obj.deployments[environment] ?? null;
  const published = obj.versions.filter((v) => v.status === "published");
  const latest = obj.versions.at(-1);
  return {
    live,
    latest,
    latestPublished: published.at(-1),
    draft: latest?.status === "draft" ? latest : undefined,
    previousPublished: published.filter((v) => live !== null && v.version < live).at(-1),
  };
}

/** A diff path in words: "guardrails.max_answer_tokens" -> ["guardrails", "max answer tokens"]. */
export function pathWords(path: string): string[] {
  return path.split(".").map((p) => (/^\d+$/.test(p) ? `#${Number(p) + 1}` : p.replace(/_/g, " ")));
}

export function preview(value: unknown, max = 80): string {
  if (value === undefined) return "";
  const text = typeof value === "string" ? value : JSON.stringify(value);
  return text.length > max ? `${text.slice(0, max - 1)}…` : text;
}

export function textFor(value: string | Localised | undefined, locale: string): string {
  if (!value) return "";
  if (typeof value === "string") return value;
  return value[locale] ?? value.en ?? Object.values(value)[0] ?? "";
}

// ------------------------------------------------------------------ runs (Answer Inspector)

export interface RunStep {
  node: string;
  type: string;
  outcome: string | null;
  ms: number;
  [k: string]: unknown;
}

export interface Usage {
  model_calls: number;
  input_tokens: number;
  output_tokens: number;
  cost_usd: number;
  model?: string;
  provider?: string;
  profile?: string;
}

export interface RunTrace {
  id: string;
  thread_id: string;
  agent: string;
  agent_versions: Record<string, number>;
  kind: string;
  status: string;
  steps: RunStep[];
  result: {
    answer?: { text?: string; citations?: { marker: string; citation: string; source_uri?: string | null }[]; abstained?: boolean; kind?: string; removed?: { marker: string; reason: string }[] } | null;
    interrupt?: Record<string, unknown> | null;
    handoff?: Record<string, unknown> | null;
    intent?: string | null;
    route?: string | null;
    usage?: Usage | null;
  };
  error: string | null;
  created_at: string;
  finished_at: string | null;
}

export interface Why {
  key: string; // messages: inspector.why.<key>
  values?: Record<string, string | number>;
  tone: Tone;
}

/** The plain-language "why" of a run, as message keys: one line per decision that shaped it. */
export function explainRun(trace: RunTrace): Why[] {
  const out: Why[] = [];
  const step = (type: string) => trace.steps.find((s) => s.type === type);
  const route = step("route");
  if (route?.blocked) out.push({ key: "blocked", values: { topic: String(route.blocked) }, tone: "rose" });
  else if (route?.method === "request") out.push({ key: "askedForPerson", tone: "sky" });
  else if (route) {
    out.push({
      key: route.method === "model" ? "routedByModel" : route.method === "examples" ? "routedByExamples" : "routedFallback",
      values: { intent: String(route.intent ?? "—"), route: String(route.outcome ?? "") },
      tone: route.outcome === "unclear" ? "amber" : "teal",
    });
  }
  if (route?.injection) out.push({ key: "injection", tone: "amber" });
  const retrieve = step("retrieve");
  if (retrieve) {
    const evidence = typeof retrieve.evidence === "number" ? Math.round(retrieve.evidence * 100) : null;
    if (!retrieve.passages) out.push({ key: "noSources", tone: "amber" });
    else out.push({ key: "foundSources", values: { count: Number(retrieve.passages), evidence: evidence ?? 0 }, tone: "teal" });
  }
  const validate = step("validate_evidence");
  if (validate?.outcome === "insufficient") out.push({ key: "weakEvidence", tone: "amber" });
  for (const tool of trace.steps.filter((s) => s.type === "call_tool")) {
    out.push(
      tool.ok
        ? { key: "toolOk", values: { tool: String(tool.tool) }, tone: "teal" }
        : { key: "toolFailed", values: { tool: String(tool.tool ?? "—"), error: String(tool.error ?? "") }, tone: "rose" },
    );
  }
  const respond = step("respond");
  const neutralised = Number(respond?.neutralised ?? 0);
  if (neutralised) out.push({ key: "neutralised", values: { count: neutralised }, tone: "amber" });
  const guard = (respond?.guard as string[] | undefined) ?? [];
  if (guard.includes("system_prompt")) out.push({ key: "withheld", tone: "rose" });
  else if (guard.length) out.push({ key: "guarded", values: { count: guard.length }, tone: "amber" });
  const removed = trace.result.answer?.removed?.length ?? 0;
  if (removed) out.push({ key: "citationsRemoved", values: { count: removed }, tone: "amber" });
  if (trace.result.handoff) out.push({ key: "handedOver", values: { reason: String(trace.result.handoff.reason ?? "") }, tone: "sky" });
  else if (trace.result.interrupt) out.push({ key: "waiting", values: { kind: String(trace.result.interrupt.kind ?? "") }, tone: "sky" });
  else if (trace.result.answer?.abstained && !route?.blocked) out.push({ key: "abstained", tone: "amber" });
  else if (trace.result.answer?.citations?.length) out.push({ key: "grounded", values: { count: trace.result.answer.citations.length }, tone: "teal" });
  if (trace.error) out.push({ key: "failed", values: { error: trace.error }, tone: "rose" });
  return out;
}

export function totalMs(trace: RunTrace): number {
  return Math.round(trace.steps.reduce((sum, s) => sum + (Number(s.ms) || 0), 0));
}

/** Nodes and edges a run went through, for highlighting on the graph (ST-11). */
export function activePath(steps: RunStep[]): { nodes: Set<string>; edges: Set<string> } {
  const nodes = new Set(steps.map((s) => s.node));
  const edges = new Set<string>();
  for (let i = 1; i < steps.length; i++) {
    if (steps[i - 1].node !== steps[i].node) edges.add(`${steps[i - 1].node}->${steps[i].node}`);
  }
  return { nodes, edges };
}

// ------------------------------------------------------------------ graph layout (ST-11)

export interface PlacedNode extends GraphNode {
  layer: number;
  row: number;
}

/** Layered layout: breadth-first from the entry; back edges (loops) do not push nodes down. */
export function layoutGraph(graph: Graph): { nodes: PlacedNode[]; layers: number; rows: number } {
  const depth = new Map<string, number>([[graph.entry, 0]]);
  const queue = [graph.entry];
  while (queue.length) {
    const id = queue.shift()!;
    for (const e of graph.edges.filter((x) => x.from === id)) {
      if (!depth.has(e.to)) {
        depth.set(e.to, (depth.get(id) ?? 0) + 1);
        queue.push(e.to);
      }
    }
  }
  let unreachable = Math.max(0, ...depth.values()) + 1;
  for (const n of graph.nodes) if (!depth.has(n.id)) depth.set(n.id, unreachable++);
  const rows = new Map<number, number>();
  const nodes = graph.nodes.map((n) => {
    const layer = depth.get(n.id) ?? 0;
    const row = rows.get(layer) ?? 0;
    rows.set(layer, row + 1);
    return { ...n, layer, row };
  });
  return { nodes, layers: Math.max(0, ...nodes.map((n) => n.layer)) + 1, rows: Math.max(1, ...rows.values()) };
}

// ------------------------------------------------------------------ tools (ST-09)

export interface ToolSpec {
  description?: string;
  kind?: string;
  risk_level?: "read" | "write" | "high";
  confirmation?: string;
  input_schema?: Record<string, unknown>;
  request?: { method?: string; url_template?: string; host_allowlist?: string[]; auth?: { scheme?: string } };
  credential_ref?: string;
  result_classification?: string;
  [k: string]: unknown;
}

export function riskTone(risk: string | undefined): Tone {
  return risk === "read" ? "teal" : risk === "write" ? "amber" : "rose";
}

export function credentialName(ref: string | undefined): string | null {
  return ref?.startsWith("secret://") ? ref.slice("secret://".length) : null;
}

export interface Approval {
  id: string;
  tool: string;
  agent: string;
  kind: string;
  actor_id: string;
  summary: string;
  status: string;
  decided_by: string | null;
  decided_at: string | null;
  expires_at: string;
  created_at: string;
}

export interface ToolCallLog {
  id: string;
  tool: string;
  tool_version: number;
  agent: string;
  actor_id: string;
  risk: string;
  status: string;
  error_code: string | null;
  http_status: number | null;
  latency_ms: number;
  approval_id: string | null;
  created_at: string;
}

// ------------------------------------------------------------------ models and data policy (ST-12)

export interface ModelProfile {
  chat?: { provider?: string; model?: string; base_url?: string };
  embedding?: { provider?: string; model?: string };
  reranker?: { enabled?: boolean; model?: string };
  capabilities?: { tool_calling?: boolean; json_schema_output?: boolean; context_tokens?: number };
  budgets?: { monthly_usd?: number; per_conversation_tokens?: number };
  data_policy?: { location?: "cloud" | "on_prem"; allow_training?: boolean };
  routing?: { classification: string; use_profile: string }[];
  fallback_profile?: string;
  redact_pii?: boolean;
}

export interface ProfileEntry {
  name: string;
  source: string | null;
  allowed: boolean;
  reason: string | null;
  profile: ModelProfile | null;
}

export const LEVELS = ["public", "internal", "confidential", "restricted"] as const;

/** Where data of each classification goes for a profile: its routing rules, else itself. */
export function dataFlow(name: string, profiles: ProfileEntry[]): { level: string; profile: string; location: string; provider: string; allowed: boolean }[] {
  const byName = new Map(profiles.map((p) => [p.name, p]));
  const own = byName.get(name);
  return LEVELS.map((level) => {
    const rule = own?.profile?.routing?.find((r) => r.classification === level);
    const target = rule ? byName.get(rule.use_profile) : own;
    return {
      level,
      profile: rule?.use_profile ?? name,
      location: target?.profile?.data_policy?.location ?? "unknown",
      provider: target?.profile?.chat?.provider ?? "—",
      allowed: target?.allowed ?? false,
    };
  });
}

/** Plain-language trade-offs: data location, typical quality and relative cost (heuristic). */
export function tradeoffs(p: ModelProfile | null): { location: string; quality: "high" | "good" | "basic"; cost: "higher" | "moderate" | "low" } {
  const provider = p?.chat?.provider ?? "";
  const location = p?.data_policy?.location ?? "unknown";
  if (provider === "offline") return { location, quality: "basic", cost: "low" };
  if (location === "on_prem" || provider === "openai_compatible") return { location, quality: "good", cost: "low" };
  return { location, quality: "high", cost: (p?.capabilities?.context_tokens ?? 0) >= 200_000 ? "higher" : "moderate" };
}

// ------------------------------------------------------------------ streaming (Studio test chat)

export interface StreamEvent {
  event: string;
  data: Record<string, unknown>;
}

/** Server-sent events from a fetch body. */
export async function* readSSE(body: ReadableStream<Uint8Array>): AsyncGenerator<StreamEvent> {
  const reader = body.getReader();
  const decoder = new TextDecoder();
  let buffer = "";
  for (;;) {
    const { done, value } = await reader.read();
    buffer += decoder.decode(value ?? new Uint8Array(), { stream: !done });
    let cut: number;
    while ((cut = buffer.indexOf("\n\n")) >= 0) {
      const parsed = sseBlock(buffer.slice(0, cut));
      buffer = buffer.slice(cut + 2);
      if (parsed) yield parsed;
    }
    if (done) {
      const last = sseBlock(buffer);
      if (last) yield last;
      return;
    }
  }
}

export function sseBlock(block: string): StreamEvent | null {
  let event = "message";
  const data: string[] = [];
  for (const line of block.split("\n")) {
    if (line.startsWith("event:")) event = line.slice(6).trim();
    else if (line.startsWith("data:")) data.push(line.slice(5).trimStart());
  }
  if (!data.length) return null;
  try {
    return { event, data: JSON.parse(data.join("\n")) as Record<string, unknown> };
  } catch {
    return null;
  }
}
