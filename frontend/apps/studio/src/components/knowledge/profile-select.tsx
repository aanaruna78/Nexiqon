"use client";

import { CircleAlert, CircleCheck, LoaderCircle } from "lucide-react";
import { useTranslations } from "next-intl";

import { Button } from "@/components/ui/button";

import { Select, SelectContent, SelectItem, SelectTrigger, SelectValue } from "@/components/ui/select";
import { UNUSABLE, useProfileCheck, useProfiles, useWorkingProfile } from "@/lib/knowledge-hooks";

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

/**
 * Whether the chosen model profile can index this collection's documents right now, checked with
 * one short embedding. When it cannot (for example, its provider has no API key), says why and
 * offers a profile that works.
 */
export function ProfileCheckNote({
  profile,
  classification,
  onUse,
}: {
  profile: string;
  classification: string;
  onUse: (profile: string) => void;
}) {
  const t = useTranslations("knowledge.profileCheck");
  const check = useProfileCheck(profile, classification);
  const unusable = Boolean(check.data && !check.data.ok && UNUSABLE.has(check.data.code ?? ""));
  const suggestion = useWorkingProfile(classification, unusable);
  if (check.isLoading) {
    return (
      <p className="flex items-center gap-1.5 text-xs text-muted-foreground" role="status">
        <LoaderCircle className="size-3.5 animate-spin motion-reduce:animate-none" aria-hidden="true" />
        {t("checking")}
      </p>
    );
  }
  if (!check.data) return null;
  if (check.data.ok) {
    return (
      <p className="flex items-center gap-1.5 text-xs text-teal-700 dark:text-teal-300" role="status" data-testid="profile-ok">
        <CircleCheck className="size-3.5" aria-hidden="true" />
        {t("ok")}
      </p>
    );
  }
  return (
    <div className="space-y-2 rounded-lg border border-destructive/30 bg-destructive/5 px-3 py-2 text-xs" role="alert" data-testid="profile-problem">
      <p className="flex items-start gap-1.5 font-medium text-destructive">
        <CircleAlert className="mt-px size-3.5 shrink-0" aria-hidden="true" />
        {check.data.code === "model_not_configured" ? t("noKey") : unusable ? t("refused") : t("unavailable")}
      </p>
      {check.data.detail ? <p className="break-words text-muted-foreground">{check.data.detail}</p> : null}
      {suggestion && suggestion !== profile ? (
        <Button type="button" size="sm" variant="outline" className="h-7" onClick={() => onUse(suggestion)}>
          {t("use", { profile: suggestion })}
        </Button>
      ) : null}
    </div>
  );
}

/** True while the chosen profile is known not to work: forms hold back their submit. */
export function useProfileBlocked(profile: string, classification: string): boolean {
  const check = useProfileCheck(profile, classification);
  return Boolean(check.data && !check.data.ok && UNUSABLE.has(check.data.code ?? ""));
}
