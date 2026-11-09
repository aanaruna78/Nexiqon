"use client";

import { useTranslations } from "next-intl";

import { Select, SelectContent, SelectItem, SelectTrigger, SelectValue } from "@/components/ui/select";
import { useProfiles } from "@/lib/knowledge-hooks";

/** Model or retrieval profile picker: built-in and deployed profiles; floor-blocked ones disabled. */
export function ProfileSelect({
  kind,
  id,
  value,
  onChange,
  disabled,
}: {
  kind: "model_profile" | "retrieval_profile";
  id: string;
  value: string;
  onChange: (value: string) => void;
  disabled?: boolean;
}) {
  const t = useTranslations("knowledge");
  const profiles = useProfiles(kind);
  const options = profiles.data ?? [{ name: value, allowed: true, reason: null, source: null, profile: null }];
  return (
    <Select value={value} onValueChange={onChange} disabled={disabled}>
      <SelectTrigger id={id} className="w-full">
        <SelectValue />
      </SelectTrigger>
      <SelectContent>
        {options.map((p) => (
          <SelectItem key={p.name} value={p.name} disabled={!p.allowed}>
            <span className="flex flex-col">
              <span>{p.name}</span>
              <span className="text-xs text-muted-foreground">
                {!p.allowed ? t("profileBlocked") : profileSummary(p.profile)}
              </span>
            </span>
          </SelectItem>
        ))}
      </SelectContent>
    </Select>
  );
}

function profileSummary(profile: Record<string, unknown> | null): string {
  if (!profile) return "";
  const policy = profile.data_policy as { location?: string } | undefined;
  const embedding = profile.embedding as { model?: string } | undefined;
  const chunking = profile.chunking as { max_tokens?: number } | undefined;
  if (embedding?.model) return [embedding.model, policy?.location?.replace("_", "-")].filter(Boolean).join(" · ");
  if (chunking?.max_tokens) return `${chunking.max_tokens} tokens`;
  return "";
}
