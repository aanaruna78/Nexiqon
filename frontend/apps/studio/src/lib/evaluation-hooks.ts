"use client";

import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";

import { api } from "./api";
import { type CaseInput, type EvalResult, type EvalRun, type GateCheck, type ReportRow, runIsActive, type TestCase, type TestSet } from "./evaluation";

const LIVE_MS = 2000;

export function useTestSets(agent?: string) {
  return useQuery({
    queryKey: ["test-sets", agent ?? null],
    queryFn: () => api<TestSet[]>(`evaluation/v1/test-sets${agent ? `?agent=${agent}` : ""}`),
  });
}

export function useTestSet(id: string) {
  return useQuery({ queryKey: ["test-set", id], queryFn: () => api<TestSet>(`evaluation/v1/test-sets/${id}`) });
}

export function useCases(setId: string) {
  return useQuery({ queryKey: ["cases", setId], queryFn: () => api<TestCase[]>(`evaluation/v1/test-sets/${setId}/cases`) });
}

/** Runs, polled while any is still asking questions. */
export function useEvalRuns(filter: { agent?: string; testSetId?: string } = {}) {
  const params = new URLSearchParams({ limit: "50" });
  if (filter.agent) params.set("agent", filter.agent);
  if (filter.testSetId) params.set("test_set_id", filter.testSetId);
  return useQuery({
    queryKey: ["eval-runs", filter.agent ?? null, filter.testSetId ?? null],
    queryFn: () => api<EvalRun[]>(`evaluation/v1/runs?${params}`),
    refetchInterval: (q) => (q.state.data?.some(runIsActive) ? LIVE_MS : false),
  });
}

export function useEvalRun(id: string | null) {
  return useQuery({
    queryKey: ["eval-run", id],
    queryFn: () => api<EvalRun>(`evaluation/v1/runs/${id}`),
    enabled: !!id,
    refetchInterval: (q) => (q.state.data && runIsActive(q.state.data) ? LIVE_MS : false),
  });
}

export function useEvalResults(id: string | null, enabled = true) {
  return useQuery({
    queryKey: ["eval-results", id],
    queryFn: () => api<EvalResult[]>(`evaluation/v1/runs/${id}/results`),
    enabled: !!id && enabled,
  });
}

export function useReports(agent: string) {
  return useQuery({
    queryKey: ["eval-reports", agent],
    queryFn: () => api<ReportRow[]>(`evaluation/v1/evaluations/reports?agent=${agent}`),
  });
}

/** May ``version`` be published? Asked before publishing so Studio can show why not. */
export function useGateCheck(
  agent: string,
  body: { version?: number; spec_hash?: string; baseline_version?: number | null; test_set?: string; min_pass_rate?: number; max_drop?: number } | null,
  latestRun?: string | null, // the newest finished run: a new one means a new answer
) {
  return useQuery({
    queryKey: ["gate", agent, body, latestRun ?? null],
    queryFn: () => api<GateCheck>(`evaluation/v1/gates/agents/${agent}/check`, { method: "POST", json: body }),
    enabled: !!body?.version && !!body.test_set,
    retry: false,
  });
}

export function useEvaluationActions() {
  const client = useQueryClient();
  const refresh = () =>
    Promise.all(
      [["test-sets"], ["test-set"], ["cases"], ["eval-runs"], ["eval-reports"], ["gate"]].map((queryKey) => client.invalidateQueries({ queryKey })),
    );
  const startRun = useMutation({
    mutationFn: (body: { agent: string; version: number; test_set_id: string }) => api<EvalRun>("evaluation/v1/runs", { method: "POST", json: body }),
    onSuccess: refresh,
  });
  const createSet = useMutation({
    mutationFn: (body: { name: string; agent?: string | null; description?: string; cases?: CaseInput[] }) =>
      api<TestSet>("evaluation/v1/test-sets", { method: "POST", json: body }),
    onSuccess: refresh,
  });
  const fromPack = useMutation({
    mutationFn: (body: { pack: string; name?: string; agent?: string | null }) => api<TestSet>("evaluation/v1/test-sets/from-pack", { method: "POST", json: body }),
    onSuccess: refresh,
  });
  const addCases = useMutation({
    mutationFn: ({ setId, cases }: { setId: string; cases: CaseInput[] }) =>
      api<TestCase[]>(`evaluation/v1/test-sets/${setId}/cases`, { method: "POST", json: cases }),
    onSuccess: refresh,
  });
  const replaceCase = useMutation({
    mutationFn: ({ setId, caseId, body }: { setId: string; caseId: string; body: CaseInput }) =>
      api<TestCase>(`evaluation/v1/test-sets/${setId}/cases/${caseId}`, { method: "PUT", json: body }),
    onSuccess: refresh,
  });
  const deleteCase = useMutation({
    mutationFn: ({ setId, caseId }: { setId: string; caseId: string }) => api(`evaluation/v1/test-sets/${setId}/cases/${caseId}`, { method: "DELETE" }),
    onSuccess: refresh,
  });
  const deleteSet = useMutation({
    mutationFn: (setId: string) => api(`evaluation/v1/test-sets/${setId}`, { method: "DELETE" }),
    onSuccess: refresh,
  });
  const cancelRun = useMutation({
    mutationFn: (runId: string) => api<EvalRun>(`evaluation/v1/runs/${runId}/cancel`, { method: "POST" }),
    onSuccess: refresh,
  });
  return { startRun, createSet, fromPack, addCases, replaceCase, deleteCase, deleteSet, cancelRun, refresh };
}
