import { describe, expect, it } from "vitest";

import { fieldKind, problemErrors, setAt, validate, type JsonSchema } from "@/components/schema-form/schema";

const agent: JsonSchema = {
  type: "object",
  required: ["display_name", "pack"],
  additionalProperties: false,
  properties: {
    display_name: { type: "string", minLength: 2 },
    pack: { type: "object", required: ["name"], properties: { name: { type: "string" } } },
    tone: { enum: ["friendly", "formal"] },
    max_turns: { type: "integer", minimum: 1 },
    pii: { type: "boolean" },
    tools: { type: "array", items: { type: "string" } },
    greeting: { type: "object", additionalProperties: { type: "string" } },
    accent: { type: "string", "x-ui": { widget: "color" } },
    dims: { const: 1024 },
    rules: { type: "array", items: { type: "object", properties: { path: { type: "string" } } } },
    free: { type: "object" },
  },
};

describe("fieldKind", () => {
  it("maps schema shapes to controls", () => {
    const p = agent.properties!;
    expect([
      fieldKind(p.display_name), fieldKind(p.pack), fieldKind(p.tone), fieldKind(p.max_turns),
      fieldKind(p.pii), fieldKind(p.tools), fieldKind(p.greeting), fieldKind(p.accent),
      fieldKind(p.dims), fieldKind(p.rules), fieldKind(p.free),
    ]).toEqual(["text", "object", "enum", "number", "boolean", "string-list", "string-map", "color", "const", "object-list", "json"]);
  });
});

describe("setAt", () => {
  it("sets nested values immutably and removes undefined keys", () => {
    const base = { a: { b: 1, c: 2 } };
    const next = setAt(base, "a.b", 5);
    expect(next).toEqual({ a: { b: 5, c: 2 } });
    expect(base.a.b).toBe(1);
    expect(setAt(next, "a.c", undefined)).toEqual({ a: { b: 5 } });
    expect(setAt({}, "list.0.path", "x")).toEqual({ list: [{ path: "x" }] });
  });
});

describe("validate", () => {
  it("keys errors by dotted path like the config service", () => {
    const errors = validate(agent, { display_name: "x", pack: {}, surprise: 1 });
    expect(errors["display_name"]).toMatch(/2/);
    expect(errors["pack.name"]).toBe("required");
    expect(errors["surprise"]).toBeDefined();
    expect(validate(agent, { display_name: "Help", pack: { name: "saas" } })).toEqual({});
  });

  it("maps problem+json errors", () => {
    expect(problemErrors([{ path: "guardrails.min_evidence_score", message: "too high" }])).toEqual({
      "guardrails.min_evidence_score": "too high",
    });
  });
});
