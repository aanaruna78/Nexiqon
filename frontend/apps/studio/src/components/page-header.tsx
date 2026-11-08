import type { LucideIcon } from "lucide-react";
import type { ReactNode } from "react";

import { IconTile, type Tone } from "@/components/visual/icon-tile";

export function PageHeader({
  title,
  description,
  actions,
  icon,
  tone = "teal",
}: {
  title: string;
  description?: string;
  actions?: ReactNode;
  icon?: LucideIcon;
  tone?: Tone;
}) {
  return (
    <div className="nx-page flex flex-col gap-4 sm:flex-row sm:items-center sm:justify-between">
      <div className="flex items-start gap-4">
        {icon ? <IconTile icon={icon} tone={tone} size="lg" className="hidden sm:inline-flex" /> : null}
        <div className="space-y-1">
          <h1 className="text-2xl font-semibold tracking-tight sm:text-3xl">{title}</h1>
          {description ? <p className="max-w-2xl text-muted-foreground">{description}</p> : null}
        </div>
      </div>
      {actions ? <div className="flex shrink-0 flex-wrap gap-2">{actions}</div> : null}
    </div>
  );
}
