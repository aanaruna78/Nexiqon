"use client";

import type { ReactElement, ReactNode } from "react";

import { Tooltip, TooltipContent, TooltipTrigger } from "@/components/ui/tooltip";

/**
 * Tooltip for extra context. The trigger must already have an accessible name: a tooltip
 * supplements, it never replaces, a label (WCAG 1.3.1 / 4.1.2).
 */
export function Hint({ label, side = "top", children }: { label: ReactNode; side?: "top" | "bottom" | "left" | "right"; children: ReactElement }) {
  return (
    <Tooltip>
      <TooltipTrigger asChild>{children}</TooltipTrigger>
      <TooltipContent side={side} className="max-w-64 text-balance">
        {label}
      </TooltipContent>
    </Tooltip>
  );
}
