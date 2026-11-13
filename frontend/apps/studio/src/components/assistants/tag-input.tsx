"use client";

import { X } from "lucide-react";
import { useTranslations } from "next-intl";
import { type KeyboardEvent, useState } from "react";

import { Input } from "@/components/ui/input";

/** A list of short texts: type and press Enter to add; each chip has its own remove button. */
export function TagInput({ id, values, onChange, placeholder }: { id: string; values: string[]; onChange: (values: string[]) => void; placeholder?: string }) {
  const t = useTranslations("common");
  const [draft, setDraft] = useState("");

  function add() {
    const v = draft.trim();
    if (v && !values.includes(v)) onChange([...values, v]);
    setDraft("");
  }

  function onKey(e: KeyboardEvent<HTMLInputElement>) {
    if (e.key === "Enter" || e.key === ",") {
      e.preventDefault();
      add();
    } else if (e.key === "Backspace" && !draft && values.length) {
      onChange(values.slice(0, -1));
    }
  }

  return (
    <div className="space-y-2">
      {values.length ? (
        <ul className="flex flex-wrap gap-1.5">
          {values.map((v) => (
            <li key={v} className="inline-flex items-center gap-1 rounded-full bg-muted py-0.5 ps-2.5 pe-1 text-sm">
              {v}
              <button type="button" onClick={() => onChange(values.filter((x) => x !== v))} className="rounded-full p-0.5 hover:bg-background focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring" aria-label={t("removeItem", { item: v })}>
                <X className="size-3" aria-hidden="true" />
              </button>
            </li>
          ))}
        </ul>
      ) : null}
      <Input id={id} value={draft} onChange={(e) => setDraft(e.target.value)} onKeyDown={onKey} onBlur={add} placeholder={placeholder} />
    </div>
  );
}
