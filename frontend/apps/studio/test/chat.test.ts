import { describe, expect, it } from "vitest";

import { activeItem } from "@/components/shell/nav";
import { assistantLabel, type ConversationSummary, groupByAge } from "@/lib/chat";

const conv = (id: string, at: string): ConversationSummary => ({
  id,
  agent: "support",
  channel: "studio",
  status: "active",
  title: null,
  created_at: at,
  last_message_at: at,
});

describe("chat history", () => {
  it("groups conversations into today, the previous 7 days and older, keeping order", () => {
    const now = new Date("2026-11-22T15:00:00");
    const groups = groupByAge(
      [conv("a", "2026-11-22T09:00:00"), conv("b", "2026-11-20T10:00:00"), conv("c", "2026-11-01T10:00:00"), conv("d", "2026-11-22T08:00:00")],
      now,
    );
    expect(groups.map((g) => [g.key, g.items.map((c) => c.id)])).toEqual([
      ["today", ["a", "d"]],
      ["week", ["b"]],
      ["older", ["c"]],
    ]);
  });

  it("leaves out empty groups", () => {
    expect(groupByAge([], new Date())).toEqual([]);
  });
});

describe("assistant names", () => {
  it("prefers the published name, then the title, then a readable identifier", () => {
    expect(assistantLabel({ agent: "x", assistant_name: "Acme Help", title: "Help" }, "x")).toBe("Acme Help");
    expect(assistantLabel({ agent: "x", title: "Help" }, "x")).toBe("Help");
    expect(assistantLabel(undefined, "ops-helper")).toBe("Ops helper");
  });
});

describe("admin navigation", () => {
  it("the overview is /admin, and sections match their own paths only", () => {
    expect(activeItem("/admin")?.key).toBe("overview");
    expect(activeItem("/admin/knowledge/123")?.key).toBe("knowledge");
    expect(activeItem("/admin/members")?.key).toBe("members");
    expect(activeItem("/")).toBeUndefined();
  });
});
