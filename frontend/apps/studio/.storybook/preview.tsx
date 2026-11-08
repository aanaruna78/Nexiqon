import type { Preview } from "@storybook/nextjs-vite";
import { NextIntlClientProvider } from "next-intl";
import { Direction } from "radix-ui";

import { TooltipProvider } from "../src/components/ui/tooltip";
import ar from "../messages/ar.json";
import en from "../messages/en.json";

import "../src/app/globals.css";

const preview: Preview = {
  globalTypes: {
    theme: { description: "Theme", toolbar: { icon: "mirror", items: ["light", "dark"], dynamicTitle: true } },
    direction: { description: "Direction", toolbar: { icon: "transfer", items: ["ltr", "rtl"], dynamicTitle: true } },
  },
  initialGlobals: { theme: "light", direction: "ltr" },
  parameters: {
    a11y: { test: "error" }, // accessibility violations fail the story check (WCAG 2.2 AA)
    layout: "padded",
  },
  decorators: [
    (Story, { globals }) => {
      const dir = globals.direction === "rtl" ? "rtl" : "ltr";
      document.documentElement.classList.toggle("dark", globals.theme === "dark");
      document.documentElement.dir = dir;
      return (
        <NextIntlClientProvider locale={dir === "rtl" ? "ar" : "en"} messages={dir === "rtl" ? ar : en}>
          <Direction.DirectionProvider dir={dir}>
            <TooltipProvider>
              <div className="bg-background p-4 text-foreground">
                <Story />
              </div>
            </TooltipProvider>
          </Direction.DirectionProvider>
        </NextIntlClientProvider>
      );
    },
  ],
};

export default preview;
