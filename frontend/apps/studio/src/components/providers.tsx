"use client";

import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { ThemeProvider } from "next-themes";
import { Direction } from "radix-ui";
import { useState, type ReactNode } from "react";

import { Toaster } from "@/components/ui/sonner";
import { TooltipProvider } from "@/components/ui/tooltip";

export function Providers({ children, dir }: { children: ReactNode; dir: "ltr" | "rtl" }) {
  const [queryClient] = useState(
    () =>
      new QueryClient({
        defaultOptions: { queries: { staleTime: 15_000, retry: 1, refetchOnWindowFocus: false } },
      }),
  );
  return (
    <QueryClientProvider client={queryClient}>
      <ThemeProvider attribute="class" defaultTheme="system" enableSystem disableTransitionOnChange>
        <Direction.DirectionProvider dir={dir}>
          <TooltipProvider delayDuration={300}>
            {children}
            <Toaster position={dir === "rtl" ? "bottom-left" : "bottom-right"} closeButton />
          </TooltipProvider>
        </Direction.DirectionProvider>
      </ThemeProvider>
    </QueryClientProvider>
  );
}
