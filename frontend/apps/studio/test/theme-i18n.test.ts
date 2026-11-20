import { describe, expect, it } from "vitest";

import { pseudo, pseudoMessages, type Messages } from "@/i18n/pseudo";
import { accessibleAccent, accentVars, contrast } from "@/lib/theme";
import { createTranslator } from "next-intl";

import ar from "../messages/ar.json";
import en from "../messages/en.json";
import es from "../messages/es.json";
import fr from "../messages/fr.json";

function keys(m: Messages, prefix = ""): string[] {
  return Object.entries(m).flatMap(([k, v]) => (typeof v === "string" ? [prefix + k] : keys(v, `${prefix}${k}.`)));
}

function lookup(m: Messages, key: string): string {
  return key.split(".").reduce<unknown>((node, part) => (node as Record<string, unknown>)[part], m) as string;
}

/** ICU argument names in a message, including those inside plural and select branches. */
function argumentsOf(message: string): Set<string> {
  const names = new Set<string>();
  let i = 0;
  const parseText = (stopAtClose: boolean): void => {
    while (i < message.length) {
      const c = message[i];
      if (c === "}" && stopAtClose) return;
      if (c === "{") parseArgument();
      else i++;
    }
  };
  const parseArgument = (): void => {
    i++; // {
    const m = /^\s*([A-Za-z_][\w]*)\s*/.exec(message.slice(i))!;
    names.add(m[1]);
    i += m[0].length;
    if (message[i] === "}") {
      i++;
      return;
    }
    i++; // ,
    const type = /^\s*(\w+)\s*/.exec(message.slice(i))!;
    i += type[0].length;
    if (message[i] === "}") {
      i++;
      return;
    }
    i++; // , before the options
    while (i < message.length && message[i] !== "}") {
      if (message[i] === "{") {
        i++;
        parseText(true);
        i++; // } closing the branch
      } else i++;
    }
    i++; // } closing the argument
  };
  parseText(false);
  return names;
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
  const translations = { ar, fr, es } as Record<string, Messages>;

  it.each(Object.keys(translations))("%s has exactly the English keys", (locale) => {
    expect(keys(translations[locale]).sort()).toEqual(keys(en as Messages).sort());
  });

  it.each(Object.keys(translations))("%s keeps every ICU argument of the English text", (locale) => {
    const mismatches = keys(en as Messages).filter(
      (key) => [...argumentsOf(lookup(en as Messages, key))].sort().join() !== [...argumentsOf(lookup(translations[locale], key))].sort().join(),
    );
    expect(mismatches).toEqual([]);
  });

  it.each(Object.keys(translations))("%s messages all format, with no ICU syntax left over", (locale) => {
    const t = createTranslator({ locale, messages: translations[locale] });
    for (const key of keys(en as Messages)) {
      const values = Object.fromEntries([...argumentsOf(lookup(en as Messages, key))].map((a) => [a, 2]));
      const out = (t as unknown as (k: string, v: Record<string, number>) => string)(key, values);
      expect(out, key).not.toMatch(/[{}]/);
    }
  });

  it("pseudo-locale accents text but keeps ICU placeholders", () => {
    expect(pseudo("Switched to {name}")).toMatch(/^\[Şẇīŧƈħḗḓ ŧǿ \{name\}~+\]$/);
    const pseudoEn = pseudoMessages(en as Messages);
    expect(keys(pseudoEn)).toEqual(keys(en as Messages));
  });
});
