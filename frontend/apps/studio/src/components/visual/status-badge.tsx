import type { ReactNode } from "react";

import { cn } from "@/lib/utils";

import { Hint } from "./hint";
import { toneClasses, type Tone } from "./icon-tile";

/**
 * Pill with a coloured dot: colour is never the only signal (the label carries meaning).
 * ``hint`` explains the status in a tooltip; the badge then takes keyboard focus so the
 * explanation is reachable without a mouse.
 */
export function StatusBadge({ tone, children, live, hint }: { tone: Tone; children: ReactNode; live?: boolean; hint?: ReactNode }) {
  const badge = (
    <span
      className={cn(
        "inline-flex items-center gap-1.5 rounded-full px-2.5 py-0.5 text-xs font-medium",
        hint && "cursor-help outline-none focus-visible:ring-2 focus-visible:ring-ring focus-visible:ring-offset-1",
        toneClasses(tone),
      )}
      tabIndex={hint ? 0 : undefined}
    >
      <span className={cn("size-1.5 rounded-full bg-current", live && "nx-live-dot")} aria-hidden="true" />
      {children}
    </span>
  );
  return hint ? <Hint label={hint}>{badge}</Hint> : badge;
}
