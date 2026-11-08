import { cn } from "@/lib/utils";

/** Stable hue per person; lightness fixed so white initials always meet AA contrast. */
function hue(seed: string): number {
  let h = 0;
  for (const ch of seed) h = (h * 31 + ch.charCodeAt(0)) % 360;
  return h;
}

export function initials(name: string): string {
  return (
    name
      .split(/[\s@._-]+/)
      .filter(Boolean)
      .slice(0, 2)
      .map((p) => p[0]?.toUpperCase())
      .join("") || "?"
  );
}

export function Avatar({ name, className }: { name: string; className?: string }) {
  return (
    <span
      aria-hidden="true"
      className={cn("inline-flex size-9 shrink-0 items-center justify-center rounded-full text-xs font-semibold text-white shadow-sm ring-2 ring-background", className)}
      style={{ background: `linear-gradient(135deg, hsl(${hue(name)} 55% 36%), hsl(${(hue(name) + 40) % 360} 55% 30%))` }}
    >
      {initials(name)}
    </span>
  );
}
