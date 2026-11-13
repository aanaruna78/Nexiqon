import fs from "node:fs";
import path from "node:path";

import Ajv2020 from "ajv/dist/2020";
import addFormats from "ajv-formats";
import { describe, expect, it } from "vitest";

import { blankPack } from "@/components/packs/templates";
import {
  activePath,
  type ConfigObject,
  dataFlow,
  explainRun,
  layoutGraph,
  pathWords,
  type ProfileEntry,
  releaseState,
  type RunTrace,
  slugify,
  sseBlock,
  tradeoffs,
} from "@/lib/studio";

const trace = (over: Partial<RunTrace> = {}): RunTrace => ({
  id: "r1",
  thread_id: "t",
  agent: "support",
  agent_versions: { agent: 2, pack: 1 },
  kind: "turn",
  status: "completed",
  steps: [
    { node: "route", type: "route", outcome: "knowledge", ms: 1, intent: "product_question", method: "examples" },
    { node: "retrieve", type: "retrieve", outcome: null, ms: 40, passages: 2, evidence: 0.81 },
    { node: "validate", type: "validate_evidence", outcome: "sufficient", ms: 0 },
    { node: "respond", type: "respond", outcome: "done", ms: 300, neutralised: 1 },
  ],
  result: { answer: { text: "Open Settings [1].", citations: [{ marker: "1", citation: "Guide › Teammates" }], abstained: false, removed: [] } },
  error: null,
  created_at: "2026-11-13T10:00:00Z",
  finished_at: null,
  ...over,
});

describe("Answer Inspector explanations", () => {
  it("explains a grounded answer step by step", () => {
    expect(explainRun(trace()).map((w) => w.key)).toEqual(["routedByExamples", "foundSources", "neutralised", "grounded"]);
    expect(explainRun(trace())[1].values).toEqual({ count: 2, evidence: 81 });
  });

  it("explains refusals, weak evidence and handovers", () => {
    const blocked = trace({ steps: [{ node: "route", type: "route", outcome: "smalltalk", ms: 0, blocked: "legal advice", method: "guard" }], result: { answer: { text: "no", abstained: true, kind: "blocked" } } });
    expect(explainRun(blocked).map((w) => w.key)).toEqual(["blocked"]);
    const weak = trace({
      steps: [
        { node: "route", type: "route", outcome: "knowledge", ms: 0, method: "model", intent: "q" },
        { node: "retrieve", type: "retrieve", outcome: null, ms: 1, passages: 0 },
        { node: "validate", type: "validate_evidence", outcome: "insufficient", ms: 0 },
        { node: "escalate", type: "escalate", outcome: "done", ms: 5 },
      ],
      result: { handoff: { reason: "unresolved" } },
    });
    expect(explainRun(weak).map((w) => w.key)).toEqual(["routedByModel", "noSources", "weakEvidence", "handedOver"]);
  });

  it("marks the path a run took", () => {
    const path = activePath(trace().steps);
    expect([...path.nodes]).toEqual(["route", "retrieve", "validate", "respond"]);
    expect(path.edges.has("retrieve->validate")).toBe(true);
    expect(path.edges.has("route->respond")).toBe(false);
  });
});

describe("graph layout", () => {
  it("layers nodes from the entry and keeps loops from pushing nodes down", () => {
    const pack = blankPack("Test");
    const { nodes, layers } = layoutGraph(pack.graph);
    const layer = Object.fromEntries(nodes.map((n) => [n.id, n.layer]));
    expect(layer.route).toBe(0);
    expect(layer.retrieve).toBe(1);
    expect(layer.validate).toBe(2);
    expect(layers).toBe(3);
  });
});

describe("blank pack template", () => {
  it("passes the platform's Domain Pack schema", () => {
    const file = path.resolve(__dirname, "../../../../services/config/src/nexiqon_config/schemas/domain_pack.schema.json");
    const schema = JSON.parse(fs.readFileSync(file, "utf8"));
    const ajv = new Ajv2020({ strict: false, allErrors: true });
    addFormats(ajv);
    const validate = ajv.compile(schema);
    expect(validate(blankPack("Clinic front desk")), JSON.stringify(validate.errors)).toBe(true);
  });
});

describe("releases", () => {
  const obj: ConfigObject = {
    kind: "agent",
    name: "a",
    description: "",
    versions: [
      { version: 1, status: "published" },
      { version: 2, status: "published" },
      { version: 3, status: "draft" },
    ],
    deployments: { dev: 2 },
  };

  it("knows what is live, what is waiting and what to roll back to", () => {
    const s = releaseState(obj);
    expect(s.live).toBe(2);
    expect(s.draft?.version).toBe(3);
    expect(s.previousPublished?.version).toBe(1);
  });

  it("reads diff paths and names", () => {
    expect(pathWords("guardrails.blocked_topics.0")).toEqual(["guardrails", "blocked topics", "#1"]);
    expect(slugify("Acme Help Desk!")).toBe("acme-help-desk");
  });
});

describe("models and data flow", () => {
  const entry = (name: string, profile: ProfileEntry["profile"], allowed = true): ProfileEntry => ({ name, source: "builtin", allowed, reason: null, profile });
  const profiles = [
    entry("cloud", { chat: { provider: "openai" }, data_policy: { location: "cloud" }, routing: [{ classification: "restricted", use_profile: "local" }] }),
    entry("local", { chat: { provider: "openai_compatible" }, data_policy: { location: "on_prem" } }),
  ];

  it("shows where each classification goes", () => {
    const flow = dataFlow("cloud", profiles);
    expect(flow.find((r) => r.level === "internal")).toMatchObject({ profile: "cloud", location: "cloud" });
    expect(flow.find((r) => r.level === "restricted")).toMatchObject({ profile: "local", location: "on_prem" });
  });

  it("describes trade-offs in plain terms", () => {
    expect(tradeoffs(profiles[1].profile)).toEqual({ location: "on_prem", quality: "good", cost: "low" });
    expect(tradeoffs({ chat: { provider: "offline" } }).quality).toBe("basic");
  });

  it("parses server-sent events", () => {
    expect(sseBlock('event: delta\ndata: {"text":"Hi"}')).toEqual({ event: "delta", data: { text: "Hi" } });
    expect(sseBlock(": keep-alive")).toBeNull();
  });
});
