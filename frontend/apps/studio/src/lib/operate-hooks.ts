"use client";

import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";

import { api } from "./api";
import type { Budget, BudgetAlert, Conversation, ConversationDetail, GapReport, Kpi, Quality, UsageSummary } from "./operate";

export function useConversations(filter: { queue?: string; agent?: string; status?: string }) {
  const params = new URLSearchParams({ limit: "100" });
  for (const [k, v] of Object.entries(filter)) if (v) params.set(k, v);
  return useQuery({
    queryKey: ["conversations", filter],
    queryFn: () => api<Conversation[]>(`conversation/v1/conversations?${params}`),
    refetchInterval: filter.queue === "waiting" ? 15_000 : false, // the queue stays fresh
  });
}

export function useConversation(id: string | null) {
  return useQuery({
    queryKey: ["conversation", id],
    queryFn: () => api<ConversationDetail>(`conversation/v1/conversations/${id}`),
    enabled: !!id,
  });
}

export function useQueueActions(id: string) {
  const client = useQueryClient();
  const refresh = () =>
    Promise.all([client.invalidateQueries({ queryKey: ["conversations"] }), client.invalidateQueries({ queryKey: ["conversation", id] })]);
  const act = useMutation({
    mutationFn: (action: "claim" | "release" | "resolve" | "reopen") =>
      api<Conversation>(`conversation/v1/conversations/${id}/queue`, { method: "POST", json: { action } }),
    onSuccess: refresh,
  });
  const reply = useMutation({
    mutationFn: (content: string) => api(`conversation/v1/conversations/${id}/staff-messages`, { method: "POST", json: { content } }),
    onSuccess: refresh,
  });
  return { act, reply };
}

export function useQuality(agent: string | null, days: number) {
  return useQuery({
    queryKey: ["quality", agent, days],
    queryFn: () => api<Quality>(`metering/v1/insights/quality?days=${days}${agent ? `&agent=${agent}` : ""}`),
  });
}

export function useKpis(agent: string | null, days: number) {
  return useQuery({
    queryKey: ["kpis", agent, days],
    queryFn: () => api<Kpi[]>(`metering/v1/insights/kpis?agent=${agent}&days=${days}`),
    enabled: !!agent,
    retry: false,
  });
}

export function useGaps(agent: string | null, days: number) {
  return useQuery({
    queryKey: ["gaps", agent, days],
    queryFn: () => api<GapReport>(`metering/v1/insights/gaps?days=${days}${agent ? `&agent=${agent}` : ""}`),
    retry: false,
  });
}

export function useUsage(month: string, agent?: string | null) {
  return useQuery({
    queryKey: ["usage", month, agent ?? null],
    queryFn: () => api<UsageSummary>(`metering/v1/usage/summary?month=${month}${agent ? `&agent=${agent}` : ""}`),
  });
}

export function useBudgets() {
  const client = useQueryClient();
  const budgets = useQuery({ queryKey: ["budgets"], queryFn: () => api<Budget[]>("metering/v1/budgets") });
  const alerts = useQuery({ queryKey: ["budget-alerts"], queryFn: () => api<BudgetAlert[]>("metering/v1/alerts") });
  const refresh = () => Promise.all([client.invalidateQueries({ queryKey: ["budgets"] }), client.invalidateQueries({ queryKey: ["budget-alerts"] })]);
  const save = useMutation({
    mutationFn: (body: { agent?: string | null; monthly_usd: string; thresholds?: number[] }) =>
      api<Budget>("metering/v1/budgets", { method: "PUT", json: body }),
    onSuccess: refresh,
  });
  const remove = useMutation({ mutationFn: (id: string) => api(`metering/v1/budgets/${id}`, { method: "DELETE" }), onSuccess: refresh });
  const acknowledge = useMutation({ mutationFn: (id: string) => api(`metering/v1/alerts/${id}/acknowledge`, { method: "POST" }), onSuccess: refresh });
  return { budgets, alerts, save, remove, acknowledge };
}
