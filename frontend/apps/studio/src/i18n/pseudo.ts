const MAP: Record<string, string> = {
  a: "ȧ", b: "ƀ", c: "ƈ", d: "ḓ", e: "ḗ", f: "ƒ", g: "ɠ", h: "ħ", i: "ī", j: "ĵ", k: "ķ", l: "ŀ",
  m: "ḿ", n: "ƞ", o: "ǿ", p: "ƥ", q: "ɋ", r: "ř", s: "ş", t: "ŧ", u: "ŭ", v: "ṽ", w: "ẇ", x: "ẋ",
  y: "ẏ", z: "ẑ", A: "Ȧ", E: "Ḗ", O: "Ǿ", S: "Ş", T: "Ŧ",
};

/** Accent letters and pad to ~140% length, leaving ICU placeholders like {name} untouched. */
export function pseudo(text: string): string {
  let out = "";
  let depth = 0;
  for (const ch of text) {
    if (ch === "{") depth++;
    if (ch === "}") depth--;
    out += depth > 0 || ch === "}" ? ch : (MAP[ch] ?? ch);
  }
  const pad = "~".repeat(Math.ceil(text.length * 0.4));
  return `[${out}${pad}]`;
}

export type Messages = { [key: string]: string | Messages };

export function pseudoMessages(messages: Messages): Messages {
  const out: Messages = {};
  for (const [k, v] of Object.entries(messages)) out[k] = typeof v === "string" ? pseudo(v) : pseudoMessages(v);
  return out;
}
