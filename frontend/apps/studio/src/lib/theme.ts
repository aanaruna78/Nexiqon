/**
 * Tenant theming (UX-04). A tenant may brand Studio and the widget with an accent colour; we only
 * accept it when white text on it meets WCAG AA (4.5:1), otherwise we darken it until it does.
 */

function channel(c: number): number {
  const s = c / 255;
  return s <= 0.03928 ? s / 12.92 : ((s + 0.055) / 1.055) ** 2.4;
}

export function parseHex(hex: string): [number, number, number] | null {
  const m = /^#([0-9a-f]{6})$/i.exec(hex.trim());
  if (!m) return null;
  const n = parseInt(m[1], 16);
  return [(n >> 16) & 255, (n >> 8) & 255, n & 255];
}

export function luminance([r, g, b]: [number, number, number]): number {
  return 0.2126 * channel(r) + 0.7152 * channel(g) + 0.0722 * channel(b);
}

export function contrast(a: string, b: string): number {
  const ca = parseHex(a);
  const cb = parseHex(b);
  if (!ca || !cb) return 0;
  const [l1, l2] = [luminance(ca), luminance(cb)].sort((x, y) => y - x);
  return (l1 + 0.05) / (l2 + 0.05);
}

function toHex([r, g, b]: [number, number, number]): string {
  return `#${[r, g, b].map((v) => Math.round(v).toString(16).padStart(2, "0")).join("")}`;
}

/** Darken ``hex`` until white text reaches ``target`` contrast. Returns null for invalid input. */
export function accessibleAccent(hex: string, target = 4.5): string | null {
  let rgb = parseHex(hex);
  if (!rgb) return null;
  for (let i = 0; i < 40 && contrast(toHex(rgb), "#ffffff") < target; i++) {
    rgb = [rgb[0] * 0.92, rgb[1] * 0.92, rgb[2] * 0.92];
  }
  return toHex(rgb);
}

/** CSS variables applying a tenant accent to primary actions and focus rings. */
export function accentVars(hex: string | null | undefined): Record<string, string> {
  const accent = hex ? accessibleAccent(hex) : null;
  return accent ? { "--primary": accent, "--ring": accent, "--primary-foreground": "#ffffff" } : {};
}
