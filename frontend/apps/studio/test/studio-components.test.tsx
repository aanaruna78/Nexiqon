import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { render, screen } from "@testing-library/react";
import axe from "axe-core";
import { NextIntlClientProvider } from "next-intl";
import type { ReactNode } from "react";
import { describe, expect, it, vi } from "vitest";

import { GraphView } from "@/components/graph/graph-view";
import { InspectorBody } from "@/components/inspector/answer-inspector";
import { DiffList } from "@/components/release/versions-panel";
import { blankPack } from "@/components/packs/templates";
import { activePath, type RunTrace } from "@/lib/studio";
import messages from "../messages/en.json";

vi.mock("next/navigation", () => ({ useRouter: () => ({ push: vi.fn(), replace: vi.fn() }), useSearchParams: () => new URLSearchParams() }));

function wrap(node: ReactNode) {
  const client = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  client.setQueryData(["resolved", "support"], { graph: blankPack("x").graph, config: {}, pack: {}, versions: {}, provenance: {} });
  return render(
    <QueryClientProvider client={client}>
      <NextIntlClientProvider locale="en" messages={messages} timeZone="UTC">{node}</NextIntlClientProvider>
    </QueryClientProvider>,
  );
}

const trace: RunTrace = {
  id: "run-1",
  thread_id: "t",
  agent: "support",
  agent_versions: { agent: 3, pack: 1 },
  kind: "turn",
  status: "completed",
  steps: [
    { node: "route", type: "route", outcome: "knowledge", ms: 1, intent: "question", method: "examples" },
    { node: "retrieve", type: "retrieve", outcome: null, ms: 42, passages: 2, evidence: 0.7, sources: [{ citation: "Guide › Teammates", score: 0.91, classification: "internal" }, { citation: "Guide › Billing", score: 0.4, classification: "internal" }] },
    { node: "validate", type: "validate_evidence", outcome: "sufficient", ms: 0 },
    { node: "respond", type: "respond", outcome: "done", ms: 250 },
  ],
  result: {
    answer: { text: "Open Settings [1].", citations: [{ marker: "1", citation: "Guide › Teammates" }], abstained: false },
    usage: { model_calls: 1, input_tokens: 420, output_tokens: 35, cost_usd: 0.0021, model: "gpt-4.1", profile: "cloud-frontier" },
  },
  error: null,
  created_at: "2026-11-13T10:00:00Z",
  finished_at: null,
};

describe("Answer Inspector", () => {
  it("shows why, the sources with scores, cost and the path taken", async () => {
    const { container } = wrap(<InspectorBody trace={trace} />);
    expect(screen.getByTestId("why")).toHaveTextContent("matched the examples of “question”");
    expect(screen.getByTestId("why")).toHaveTextContent("backed by 1 verified citation");
    expect(screen.getByTestId("inspector-facts")).toHaveTextContent("$0.0021");
    expect(screen.getByTestId("inspector-facts")).toHaveTextContent("gpt-4.1");
    expect(screen.getByTestId("inspector-sources")).toHaveTextContent("Cited");
    expect(screen.getByTestId("graph-node-retrieve")).toHaveAttribute("data-active", "true");
    expect(screen.getByTestId("graph-node-escalate")).toHaveAttribute("data-active", "false");
    const results = await axe.run(container, { rules: { "color-contrast": { enabled: false } } });
    expect(results.violations.map((v) => v.id)).toEqual([]);
  });
});

describe("graph view", () => {
  it("draws every node and lists every edge for screen readers", () => {
    const graph = blankPack("x").graph;
    wrap(<GraphView graph={graph} active={activePath(trace.steps)} />);
    expect(screen.getByRole("img")).toHaveAccessibleName("Workflow with 6 steps");
    expect(screen.getByText("retrieve goes to validate when always")).toBeInTheDocument();
  });
});

describe("diff list", () => {
  it("says what changed in words", () => {
    wrap(<DiffList changes={[{ op: "replace", path: "guardrails.max_answer_tokens", old: 700, new: 500 }, { op: "add", path: "tools", new: ["account-lookup"] }]} />);
    expect(screen.getByTestId("diff")).toHaveTextContent("Changed");
    expect(screen.getByTestId("diff")).toHaveTextContent("guardrails › max answer tokens");
    expect(screen.getByText("700")).toBeInTheDocument();
  });
});
