import type { ReactNode } from "react";

import { BrandMark } from "@/components/visual/brand-mark";

/** Full-page frame for sign-in adjacent pages: brand, soft gradient backdrop, raised card. */
export function AuthFrame({ children }: { children: ReactNode }) {
  return (
    <main id="main" className="nx-mesh relative flex min-h-dvh items-center justify-center overflow-hidden bg-surface p-4 sm:p-6">
      <div className="nx-grid-pattern pointer-events-none absolute inset-0 opacity-50 [mask-image:radial-gradient(70%_60%_at_50%_30%,black,transparent)]" aria-hidden="true" />
      <div className="nx-page relative w-full max-w-md space-y-6">
        <div className="flex items-center justify-center gap-2.5">
          <BrandMark className="size-9" />
          <span className="text-lg font-semibold tracking-tight">
            Nexiqon <span className="font-normal text-muted-foreground">Studio</span>
          </span>
        </div>
        <div className="nx-card p-6 sm:p-8">{children}</div>
      </div>
    </main>
  );
}
