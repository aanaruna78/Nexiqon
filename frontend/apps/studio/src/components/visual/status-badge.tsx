import type { ReactNode } from "react";

import { cn } from "@/lib/utils";

import { toneClasses, type Tone } from "./icon-tile";

/** Pill with a coloured dot: colour is never the only signal (the label carries meaning). */
export function StatusBadge({ tone, children, live }: { tone: Tone; children: ReactNode; live?: boolean }) {
  return (
    <span className={cn("inline-flex items-center gap-1.5 rounded-full px-2.5 py-0.5 text-xs font-medium", toneClasses(tone))}>
      <span className={cn("size-1.5 rounded-full bg-current", live && "nx-live-dot")} aria-hidden="true" />
      {children}
    </span>
  );
}
