"use client";

import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";

import { api } from "./api";
import type { Approval, Change, ConfigObject, DeploymentEvent, ProfileEntry, RunTrace, ToolCallLog, VersionDetail } from "./studio";

export function useObjects(kind: string) {
  return useQuery({ queryKey: ["objects", kind], queryFn: () => api<ConfigObject[]>(`config/v1/objects?kind=${kind}`) });
}

export function useObject(kind: string, name: string, enabled = true) {
  return useQuery({
    queryKey: ["object", kind, name],
    queryFn: () => api<ConfigObject>(`config/v1/objects/${kind}/${name}`),
    enabled,
  });
}

export function useVersion(kind: string, name: string, version: number | undefined) {
  return useQuery({
    queryKey: ["version", kind, name, version],
    queryFn: () => api<VersionDetail>(`config/v1/objects/${kind}/${name}/versions/${version}`),
    enabled: version !== undefined,
    staleTime: Infinity, // versions are immutable once published; drafts are refetched on save
  });
}

export function useDiff(kind: string, name: string, from?: number, to?: number) {
  return useQuery({
    queryKey: ["diff", kind, name, from, to],
    queryFn: () => api<{ changes: Change[] }>(`config/v1/objects/${kind}/${name}/diff?from=${from}&to=${to}`),
    enabled: from !== undefined && to !== undefined && from !== to,
  });
}

export function useHistory(kind: string, name: string) {
  return useQuery({
    queryKey: ["history", kind, name],
    queryFn: () => api<DeploymentEvent[]>(`config/v1/objects/${kind}/${name}/deployments/history`),
  });
}

export function useModelProfiles() {
  return useQuery({
    queryKey: ["profiles", "model_profile", "full"],
    queryFn: () => api<ProfileEntry[]>("config/v1/profiles/model_profile?environment=dev"),
    staleTime: 60_000,
  });
}

export function useRun(id: string | null) {
  return useQuery({
    queryKey: ["run", id],
    queryFn: () => api<RunTrace>(`agent-runtime/v1/runs/${id}`),
    enabled: !!id,
    staleTime: Infinity,
  });
}

export function useResolvedAgent(name: string) {
  return useQuery({
    queryKey: ["resolved", name],
    queryFn: () => api<{ config: Record<string, unknown>; pack: Record<string, unknown>; graph: unknown; versions: Record<string, number>; provenance: Record<string, string> }>(`config/v1/resolve/agents/${name}?environment=dev`),
    retry: false,
  });
}

export function useApprovals() {
  return useQuery({ queryKey: ["approvals"], queryFn: () => api<Approval[]>("tool-gateway/v1/approvals?limit=100") });
}

export function useCalls() {
  return useQuery({ queryKey: ["calls"], queryFn: () => api<ToolCallLog[]>("tool-gateway/v1/calls?limit=100") });
}

export function useCredentials() {
  return useQuery({
    queryKey: ["credentials"],
    queryFn: () => api<{ name: string; updated_at: string | null }[]>("tool-gateway/v1/credentials"),
    retry: false,
  });
}

/** Save a draft (or create), publish it and deploy it to dev: the "safe publish" steps in one place. */
export function useRelease(kind: string, name: string) {
  const client = useQueryClient();
  const refresh = () =>
    Promise.all([
      client.invalidateQueries({ queryKey: ["object", kind, name] }),
      client.invalidateQueries({ queryKey: ["objects", kind] }),
      client.invalidateQueries({ queryKey: ["history", kind, name] }),
      client.invalidateQueries({ queryKey: ["resolved", name] }),
    ]);
  const saveDraft = useMutation({
    mutationFn: (spec: Record<string, unknown>) => api<VersionDetail>(`config/v1/objects/${kind}/${name}/draft`, { method: "PUT", json: { spec } }),
    onSuccess: async (v) => {
      client.setQueryData(["version", kind, name, v.version], v);
      await refresh();
    },
  });
  const publish = useMutation({
    mutationFn: (version: number) => api(`config/v1/objects/${kind}/${name}/versions/${version}/publish`, { method: "POST" }),
    onSuccess: refresh,
  });
  const deploy = useMutation({
    mutationFn: ({ version, environment = "dev", reason = "" }: { version: number; environment?: string; reason?: string }) =>
      api(`config/v1/objects/${kind}/${name}/deployments/${environment}`, { method: "PUT", json: { version, reason } }),
    onSuccess: refresh,
  });
  return { saveDraft, publish, deploy, refresh };
}
