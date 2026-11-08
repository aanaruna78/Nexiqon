import type { LucideIcon } from "lucide-react";
import type { ReactNode } from "react";

import { IconTile, type Tone } from "@/components/visual/icon-tile";

/** Empty state with a layered, CSS-only illustration (no image download). */
export function EmptyState({ icon, title, body, action, tone = "teal" }: { icon: LucideIcon; title: string; body?: string; action?: ReactNode; tone?: Tone }) {
  return (
    <div className="nx-card nx-page relative flex flex-col items-center justify-center gap-4 overflow-hidden px-6 py-14 text-center">
      <div className="nx-grid-pattern pointer-events-none absolute inset-0 opacity-60 [mask-image:radial-gradient(60%_60%_at_50%_40%,black,transparent)]" aria-hidden="true" />
      <div className="relative" aria-hidden="true">
        <span className="absolute -inset-4 rounded-3xl bg-primary/10 blur-xl" />
        <span className="absolute -start-6 top-3 size-8 rotate-[-12deg] rounded-xl border bg-card shadow-sm" />
        <span className="absolute -end-6 top-1 size-6 rotate-12 rounded-lg border bg-card shadow-sm" />
        <IconTile icon={icon} tone={tone} size="lg" className="relative shadow-md" />
      </div>
      <h2 className="relative text-lg font-semibold">{title}</h2>
      {body ? <p className="relative max-w-md text-sm text-muted-foreground">{body}</p> : null}
      {action ? <div className="relative">{action}</div> : null}
    </div>
  );
}
