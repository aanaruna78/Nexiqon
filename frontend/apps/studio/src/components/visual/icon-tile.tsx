import type { LucideIcon } from "lucide-react";

import { cn } from "@/lib/utils";

export type Tone = "teal" | "navy" | "amber" | "violet" | "rose" | "sky" | "slate";

/** Foreground/background pairs chosen for >= 4.5:1 contrast in light and dark themes. */
const TONES: Record<Tone, string> = {
  teal: "bg-teal-100 text-teal-800 dark:bg-teal-400/15 dark:text-teal-200",
  navy: "bg-slate-200 text-slate-800 dark:bg-slate-400/15 dark:text-slate-200",
  amber: "bg-amber-100 text-amber-900 dark:bg-amber-400/15 dark:text-amber-200",
  violet: "bg-violet-100 text-violet-800 dark:bg-violet-400/15 dark:text-violet-200",
  rose: "bg-rose-100 text-rose-800 dark:bg-rose-400/15 dark:text-rose-200",
  sky: "bg-sky-100 text-sky-800 dark:bg-sky-400/15 dark:text-sky-200",
  slate: "bg-muted text-muted-foreground",
};

export function toneClasses(tone: Tone): string {
  return TONES[tone];
}

export function IconTile({ icon: Icon, tone = "teal", size = "md", className }: { icon: LucideIcon; tone?: Tone; size?: "sm" | "md" | "lg"; className?: string }) {
  const box = { sm: "size-8 rounded-lg", md: "size-10 rounded-xl", lg: "size-12 rounded-2xl" }[size];
  const glyph = { sm: "size-4", md: "size-5", lg: "size-6" }[size];
  return (
    <span className={cn("inline-flex shrink-0 items-center justify-center ring-1 ring-inset ring-black/5 dark:ring-white/10", box, TONES[tone], className)} aria-hidden="true">
      <Icon className={glyph} />
    </span>
  );
}
