"use client";

import { useQueries, useQuery } from "@tanstack/react-query";

import { api } from "./api";
import {
  type Collection,
  isBusy,
  type KnowledgeDocument,
  type PluginManifest,
  type ProfileOption,
  type Run,
  runIsActive,
  type Source,
} from "./knowledge";

const LIVE_MS = 2000;

export function useCollections() {
  return useQuery({ queryKey: ["collections"], queryFn: () => api<Collection[]>("ingestion/v1/collections") });
}

export function useCollection(id: string) {
  return useQuery({ queryKey: ["collection", id], queryFn: () => api<Collection>(`ingestion/v1/collections/${id}`) });
}

/** Polls while any document is still being processed, so progress is live without a socket. */
export function useDocuments(collectionId: string) {
  return useQuery({
    queryKey: ["documents", collectionId],
    queryFn: () => api<KnowledgeDocument[]>(`ingestion/v1/collections/${collectionId}/documents?limit=500`),
    enabled: Boolean(collectionId), // the setup guide asks before any collection exists
    refetchInterval: (q) => (q.state.data?.some((d) => isBusy(d.status)) ? LIVE_MS : false),
  });
}

export function useRuns(collectionId: string) {
  return useQuery({
    queryKey: ["runs", collectionId],
    queryFn: () => api<Run[]>(`ingestion/v1/collections/${collectionId}/runs?limit=20`),
    refetchInterval: (q) => (q.state.data?.some(runIsActive) ? LIVE_MS : false),
  });
}

export function useSources(collectionId: string) {
  return useQuery({
    queryKey: ["sources", collectionId],
    queryFn: () => api<Source[]>(`ingestion/v1/collections/${collectionId}/sources`),
    refetchInterval: (q) => (q.state.data?.some((s) => s.status === "syncing") ? LIVE_MS : false),
  });
}

export function usePlugins(kind: PluginManifest["kind"]) {
  return useQuery({
    queryKey: ["plugins", kind],
    queryFn: () => api<PluginManifest[]>(`ingestion/v1/plugins?kind=${kind}`),
    staleTime: 10 * 60_000,
  });
}

export function useProfiles(kind: "model_profile" | "retrieval_profile") {
  return useQuery({
    queryKey: ["profiles", kind],
    queryFn: () => api<ProfileOption[]>(`config/v1/profiles/${kind}?environment=dev`),
    staleTime: 5 * 60_000,
  });
}

export interface ProfileCheck {
  profile: string;
  ok: boolean;
  code: string | null;
  detail: string | null;
}

/** Codes that mean the profile can never work as configured (not a passing outage). */
export const UNUSABLE = new Set(["model_not_configured", "embedding_failed"]);

function checkProfile(profile: string, classification: string): Promise<ProfileCheck> {
  return api<ProfileCheck>(`ingestion/v1/model-profiles/${profile}/check`, { method: "POST", json: { classification } });
}

/** Can documents of this classification be indexed with this model profile right now? */
export function useProfileCheck(profile: string, classification: string) {
  return useQuery({
    queryKey: ["profile-check", profile, classification],
    queryFn: () => checkProfile(profile, classification),
    enabled: Boolean(profile),
    staleTime: 60_000,
    retry: false,
  });
}

/** The first allowed model profile that works, to suggest when the chosen one does not. */
export function useWorkingProfile(classification: string, enabled: boolean): string | null {
  const profiles = useProfiles("model_profile");
  const candidates = (profiles.data ?? []).filter((p) => p.allowed).map((p) => p.name);
  const checks = useQueries({
    queries: candidates.map((name) => ({
      queryKey: ["profile-check", name, classification],
      queryFn: () => checkProfile(name, classification),
      enabled,
      staleTime: 60_000,
      retry: false,
    })),
  });
  return candidates.find((_, i) => checks[i]?.data?.ok) ?? null;
}
