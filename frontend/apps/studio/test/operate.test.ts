import { describe, expect, it } from "vitest";

import { bars, budgetTone, type Conversation, type ConversationMessage, pctOrDash, questionBefore, queueOrder, RATES, rateTone, usd } from "@/lib/operate";

import ar from "../messages/ar.json";
import en from "../messages/en.json";

const conv = (id: string, queue: Conversation["queue_status"], at: string): Conversation => ({
  id,
  agent: "a",
  channel: "widget",
  locale: "en",
  actor_id: "v",
  status: "escalated",
  title: null,
  handoff_summary: null,
  created_at: at,
  last_message_at: at,
  retain_until: null,
  queue_status: queue,
  assignee: null,
  resolved_at: null,
});

describe("operate helpers", () => {
  it("puts open handovers first, longest waiting first", () => {
    const order = queueOrder([conv("c", "claimed", "2026-11-19T08:00:00Z"), conv("b", "open", "2026-11-19T10:00:00Z"), conv("a", "open", "2026-11-19T09:00:00Z")]);
    expect(order.map((c) => c.id)).toEqual(["a", "b", "c"]);
  });

  it("knows which way is better for each rate", () => {
    expect(rateTone("answer_rate", 0.9, 0.8)).toBe("teal");
    expect(rateTone("escalation_rate", 0.2, 0.1)).toBe("rose");
    expect(rateTone("escalation_rate", 0.05, 0.1)).toBe("teal");
    expect(rateTone("satisfaction", 0.8, null)).toBe("slate");
    expect(rateTone("answer_rate", 0.801, 0.8)).toBe("slate");
  });

  it("formats money, rates and budget states", () => {
    expect(usd("1234.5")).toBe("$1,234.50");
    expect(usd(0.001234, 4)).toBe("$0.0012");
    expect(pctOrDash(0.756)).toBe("75.6%");
    expect(pctOrDash(null)).toBe("—");
    expect(budgetTone(0.5)).toBe("teal");
    expect(budgetTone(0.85)).toBe("amber");
    expect(budgetTone(1.2)).toBe("rose");
    expect(bars([0, 5, 10])).toEqual([0, 0.5, 1]);
    expect(bars([0, 0])).toEqual([0, 0]);
  });

  it("finds the question behind an answer", () => {
    const m = (role: ConversationMessage["role"], content: string): ConversationMessage => ({ id: content, role, content, contract: {}, run_id: null, created_at: "" });
    const messages = [m("user", "q1"), m("assistant", "a1"), m("user", "q2"), m("staff", "s"), m("assistant", "a2")];
    expect(questionBefore(messages, 1)).toBe("q1");
    expect(questionBefore(messages, 4)).toBe("q2");
    expect(questionBefore(messages, 0)).toBeNull();
  });

  it("names every rate in both languages", () => {
    for (const messages of [en, ar]) for (const r of RATES) expect(messages.insights.rates[r]).toBeTruthy();
  });
});
