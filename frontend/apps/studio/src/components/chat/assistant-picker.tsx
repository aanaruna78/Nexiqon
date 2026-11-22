"use client";

import { Bot, Check, ChevronDown } from "lucide-react";
import { useTranslations } from "next-intl";

import { Button } from "@/components/ui/button";
import { DropdownMenu, DropdownMenuContent, DropdownMenuItem, DropdownMenuLabel, DropdownMenuTrigger } from "@/components/ui/dropdown-menu";
import { Hint } from "@/components/visual/hint";
import { type AssistantFace, assistantLabel } from "@/lib/chat";

/** Which assistant answers. Chosen before the first message; fixed for the rest of a conversation. */
export function AssistantPicker({
  assistants,
  value,
  onChange,
  locked,
}: {
  assistants: AssistantFace[];
  value: string | null;
  onChange: (agent: string) => void;
  locked: boolean;
}) {
  const t = useTranslations("chat");
  const current = assistants.find((a) => a.agent === value);
  const label = value ? assistantLabel(current, value) : t("chooseAssistant");
  const trigger = (
    <Button variant="ghost" className="h-10 gap-2 rounded-xl px-3 text-base font-semibold" disabled={locked} data-testid="assistant-picker">
      <Bot className="size-4 text-primary" aria-hidden="true" />
      <span className="sr-only">{t("assistant")}: </span>
      {label}
      {locked ? null : <ChevronDown className="size-4 opacity-60" aria-hidden="true" />}
    </Button>
  );
  if (locked) {
    return (
      <Hint label={t("lockedHint")}>
        <span tabIndex={0} className="rounded-xl outline-none focus-visible:ring-2 focus-visible:ring-ring">{trigger}</span>
      </Hint>
    );
  }
  return (
    <DropdownMenu>
      <Hint label={t("chooseHint")}>
        <DropdownMenuTrigger asChild>{trigger}</DropdownMenuTrigger>
      </Hint>
      <DropdownMenuContent align="start" className="w-72">
        <DropdownMenuLabel className="text-xs font-medium text-muted-foreground">{t("assistants")}</DropdownMenuLabel>
        {assistants.map((a) => (
          <DropdownMenuItem key={a.agent} onSelect={() => onChange(a.agent)} className="items-start gap-3 py-2">
            <Bot className="mt-0.5 size-4 text-primary" aria-hidden="true" />
            <span className="grid flex-1 gap-0.5">
              <span className="font-medium">{assistantLabel(a, a.agent)}</span>
              {a.greeting ? <span className="line-clamp-2 text-xs text-muted-foreground">{a.greeting}</span> : null}
            </span>
            {a.agent === value ? <Check className="mt-0.5 size-4" aria-hidden="true" /> : null}
          </DropdownMenuItem>
        ))}
      </DropdownMenuContent>
    </DropdownMenu>
  );
}
