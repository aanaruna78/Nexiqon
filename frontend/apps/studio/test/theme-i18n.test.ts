import { describe, expect, it } from "vitest";

import { pseudo, pseudoMessages, type Messages } from "@/i18n/pseudo";
import { accessibleAccent, accentVars, contrast } from "@/lib/theme";
import ar from "../messages/ar.json";
import en from "../messages/en.json";

function keys(m: Messages, prefix = ""): string[] {
  return Object.entries(m).flatMap(([k, v]) => (typeof v === "string" ? [prefix + k] : keys(v, `${prefix}${k}.`)));
}

describe("theme", () => {
  it("brand primary meets WCAG AA with white text", () => {
    expect(contrast("#0b6f66", "#ffffff")).toBeGreaterThanOrEqual(4.5);
    expect(contrast("#0e8a7e", "#ffffff")).toBeLessThan(4.5); // why primary is darker than the brand teal
  });

  it("clamps tenant accents to an accessible shade", () => {
    const light = accessibleAccent("#7ee8fa")!;
    expect(contrast(light, "#ffffff")).toBeGreaterThanOrEqual(4.5);
    expect(accessibleAccent("not-a-colour")).toBeNull();
    expect(accentVars("#123456")["--primary"]).toBe("#123456");
    expect(accentVars(undefined)).toEqual({});
  });
});

describe("i18n", () => {
  it("every locale has exactly the English keys", () => {
    expect(keys(ar as Messages).sort()).toEqual(keys(en as Messages).sort());
  });

  it("pseudo-locale accents text but keeps ICU placeholders", () => {
    expect(pseudo("Switched to {name}")).toMatch(/^\[Şẇīŧƈħḗḓ ŧǿ \{name\}~+\]$/);
    const pseudoEn = pseudoMessages(en as Messages);
    expect(keys(pseudoEn)).toEqual(keys(en as Messages));
  });
});
