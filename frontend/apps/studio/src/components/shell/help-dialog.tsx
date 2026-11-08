"use client";

import { Keyboard } from "lucide-react";
import { useTranslations } from "next-intl";

import { Dialog, DialogContent, DialogDescription, DialogHeader, DialogTitle } from "@/components/ui/dialog";
import { IconTile } from "@/components/visual/icon-tile";

const SHORTCUTS = [
  { keys: ["Ctrl", "K"], label: "shortcutPalette" },
  { keys: ["Ctrl", "B"], label: "shortcutSidebar" },
  { keys: ["Esc"], label: "shortcutClose" },
  { keys: ["Tab"], label: "shortcutSkip" },
] as const;

export function HelpDialog({ open, onOpenChange }: { open: boolean; onOpenChange: (o: boolean) => void }) {
  const t = useTranslations("shell");
  return (
    <Dialog open={open} onOpenChange={onOpenChange}>
      <DialogContent className="sm:max-w-md">
        <DialogHeader className="flex-row items-center gap-3 space-y-0">
          <IconTile icon={Keyboard} tone="teal" />
          <div>
            <DialogTitle>{t("helpTitle")}</DialogTitle>
            <DialogDescription>{t("helpBody")}</DialogDescription>
          </div>
        </DialogHeader>
        <dl className="divide-y rounded-lg border">
          {SHORTCUTS.map((s) => (
            <div key={s.label} className="flex items-center justify-between gap-4 px-4 py-3">
              <dt className="text-sm">{t(s.label)}</dt>
              <dd className="flex shrink-0 gap-1" dir="ltr">
                {s.keys.map((k) => (
                  <kbd key={k} className="min-w-7 rounded-md border bg-muted px-1.5 py-0.5 text-center font-mono text-xs shadow-[0_1px_0_var(--border)]">
                    {k}
                  </kbd>
                ))}
              </dd>
            </div>
          ))}
        </dl>
      </DialogContent>
    </Dialog>
  );
}
