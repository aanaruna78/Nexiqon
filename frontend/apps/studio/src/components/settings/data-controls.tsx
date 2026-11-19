"use client";

import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { Archive, Download, Eraser, ShieldAlert, Trash2 } from "lucide-react";
import { useFormatter, useTranslations } from "next-intl";
import { type FormEvent, useState } from "react";
import { toast } from "sonner";

import { useStudio } from "@/components/shell/studio-context";
import { Alert, AlertDescription, AlertTitle } from "@/components/ui/alert";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import { StatusBadge } from "@/components/visual/status-badge";
import { api } from "@/lib/api";
import { useErrorToast } from "@/lib/hooks";

interface Step {
  service: string;
  status: "pending" | "running" | "done" | "failed";
  attempts: number;
  detail: { deleted?: Record<string, number>; residue_check_passed?: boolean; rows?: number; error?: string };
}

interface LifecycleRequest {
  id: string;
  kind: "delete" | "export";
  status: "scheduled" | "running" | "completed" | "failed" | "cancelled";
  run_after: string;
  created_at: string;
  finished_at: string | null;
  downloadable: boolean;
  error: string | null;
  steps: Step[];
}

interface RetentionRun {
  id: string;
  status: string;
  started_by: string;
  purged: Record<string, Record<string, number>>;
  errors: Record<string, string>;
  created_at: string;
}

const ACTIVE = new Set(["scheduled", "running"]);
const TONE = { scheduled: "amber", running: "sky", completed: "teal", failed: "rose", cancelled: "slate" } as const;

function useRequests() {
  return useQuery({
    queryKey: ["lifecycle"],
    queryFn: () => api<LifecycleRequest[]>("governance/v1/lifecycle/requests"),
    refetchInterval: (q) => (q.state.data?.some((r) => ACTIVE.has(r.status)) ? 2000 : false),
  });
}

/** Export, deletion and retention for the whole organization (G-01, G-02). */
export function DataControls() {
  const { isAdmin, isOwner } = useStudio();
  const requests = useRequests();
  const latest = (kind: "delete" | "export") => requests.data?.find((r) => r.kind === kind);
  return (
    <div className="max-w-3xl space-y-6">
      {isOwner ? <ExportCard request={latest("export")} /> : null}
      {isAdmin ? <RetentionCard /> : null}
      {isOwner ? <DeleteCard request={latest("delete")} /> : null}
    </div>
  );
}

function Steps({ steps }: { steps: Step[] }) {
  const t = useTranslations("data");
  if (!steps.length) return null;
  return (
    <ol className="grid gap-1.5 sm:grid-cols-2" data-testid="lifecycle-steps" aria-label={t("steps")}>
      {steps.map((s) => (
        <li key={s.service} className="flex items-center justify-between gap-2 rounded-lg border px-3 py-1.5 text-sm">
          <span className="font-mono text-xs">{s.service}</span>
          <StatusBadge tone={s.status === "done" ? "teal" : s.status === "failed" ? "rose" : s.status === "running" ? "sky" : "slate"} live={s.status === "running"}>
            {t(`step.${s.status}`)}
          </StatusBadge>
        </li>
      ))}
    </ol>
  );
}

function ExportCard({ request }: { request?: LifecycleRequest }) {
  const t = useTranslations("data");
  const client = useQueryClient();
  const onError = useErrorToast();
  const start = useMutation({
    mutationFn: () => api<LifecycleRequest>("governance/v1/lifecycle/export", { method: "POST" }),
    onSuccess: () => client.invalidateQueries({ queryKey: ["lifecycle"] }),
    onError,
  });
  const busy = !!request && ACTIVE.has(request.status);
  return (
    <section aria-labelledby="export-title" className="nx-card space-y-4 p-5" data-testid="export-card">
      <div className="flex flex-wrap items-start justify-between gap-3">
        <div className="space-y-1">
          <h2 id="export-title" className="flex items-center gap-2 font-semibold">
            <Archive className="size-4" aria-hidden="true" />
            {t("exportTitle")}
          </h2>
          <p className="max-w-prose text-sm text-muted-foreground">{t("exportHelp")}</p>
        </div>
        <Button onClick={() => start.mutate()} disabled={busy || start.isPending} data-testid="start-export">{t("exportStart")}</Button>
      </div>
      {request ? (
        <div className="space-y-3">
          <p className="flex items-center gap-2 text-sm">
            <StatusBadge tone={TONE[request.status]} live={busy}>{t(`status.${request.status}`)}</StatusBadge>
          </p>
          {busy ? <Steps steps={request.steps} /> : null}
          {request.downloadable ? (
            <Button asChild variant="outline">
              <a href={`/api/nx/governance/v1/lifecycle/requests/${request.id}/download`} data-testid="download-export">
                <Download className="size-4" aria-hidden="true" />
                {t("download")}
              </a>
            </Button>
          ) : null}
          {request.error ? <p className="text-sm text-destructive">{request.error}</p> : null}
        </div>
      ) : null}
    </section>
  );
}

function RetentionCard() {
  const t = useTranslations("data");
  const format = useFormatter();
  const client = useQueryClient();
  const onError = useErrorToast();
  const runs = useQuery({
    queryKey: ["retention"],
    queryFn: () => api<RetentionRun[]>("governance/v1/retention/runs"),
    refetchInterval: (q) => (q.state.data?.some((r) => r.status === "running") ? 2000 : false),
  });
  const run = useMutation({
    mutationFn: () => api("governance/v1/retention/runs", { method: "POST" }),
    onSuccess: () => client.invalidateQueries({ queryKey: ["retention"] }),
    onError,
  });
  const last = runs.data?.[0];
  const total = last ? Object.values(last.purged).reduce((n, kinds) => n + Object.values(kinds).reduce((a, b) => a + b, 0), 0) : 0;
  return (
    <section aria-labelledby="retention-title" className="nx-card space-y-4 p-5" data-testid="retention-card">
      <div className="flex flex-wrap items-start justify-between gap-3">
        <div className="space-y-1">
          <h2 id="retention-title" className="flex items-center gap-2 font-semibold">
            <Eraser className="size-4" aria-hidden="true" />
            {t("retentionTitle")}
          </h2>
          <p className="max-w-prose text-sm text-muted-foreground">{t("retentionHelp")}</p>
        </div>
        <Button variant="outline" onClick={() => run.mutate()} disabled={run.isPending || last?.status === "running"} data-testid="run-retention">{t("retentionRun")}</Button>
      </div>
      {last ? (
        <p className="flex flex-wrap items-center gap-2 text-sm" data-testid="retention-last">
          <StatusBadge tone={last.status === "completed" ? "teal" : last.status === "running" ? "sky" : "rose"} live={last.status === "running"}>{t(`status.${last.status}`)}</StatusBadge>
          <span>{t("retentionLast", { when: format.relativeTime(new Date(last.created_at)), count: total })}</span>
          {Object.keys(last.errors).length ? <span className="text-destructive">{t("retentionErrors", { services: Object.keys(last.errors).join(", ") })}</span> : null}
        </p>
      ) : (
        <p className="text-sm text-muted-foreground">{t("retentionNever")}</p>
      )}
    </section>
  );
}

function DeleteCard({ request }: { request?: LifecycleRequest }) {
  const t = useTranslations("data");
  const format = useFormatter();
  const { active } = useStudio();
  const client = useQueryClient();
  const onError = useErrorToast();
  const [typed, setTyped] = useState("");
  const refresh = () => client.invalidateQueries({ queryKey: ["lifecycle"] });
  const start = useMutation({
    mutationFn: () => api<LifecycleRequest>("governance/v1/lifecycle/delete", { method: "POST", json: { confirm: active.tenant_id } }),
    onSuccess: async () => {
      setTyped("");
      toast.warning(t("deleteScheduled"));
      await refresh();
    },
    onError,
  });
  const cancel = useMutation({
    mutationFn: (id: string) => api(`governance/v1/lifecycle/requests/${id}/cancel`, { method: "POST" }),
    onSuccess: async () => {
      toast.success(t("deleteCancelled"));
      await refresh();
    },
    onError,
  });
  const pending = request && ACTIVE.has(request.status) ? request : null;
  const matches = typed.trim() === active.tenant_slug;

  function submit(e: FormEvent) {
    e.preventDefault();
    if (matches) start.mutate();
  }

  return (
    <section aria-labelledby="delete-title" className="space-y-4 rounded-2xl border-2 border-destructive/40 p-5" data-testid="delete-card">
      <div className="space-y-1">
        <h2 id="delete-title" className="flex items-center gap-2 font-semibold text-destructive">
          <ShieldAlert className="size-4" aria-hidden="true" />
          {t("deleteTitle")}
        </h2>
        <p className="max-w-prose text-sm text-muted-foreground">{t("deleteHelp")}</p>
      </div>
      {pending ? (
        <Alert variant="destructive" data-testid="delete-pending">
          <AlertTitle>{pending.status === "scheduled" ? t("deleteWhen", { when: format.dateTime(new Date(pending.run_after), { dateStyle: "medium", timeStyle: "short" }) }) : t("deleteRunning")}</AlertTitle>
          <AlertDescription className="space-y-3">
            <Steps steps={pending.steps} />
            {pending.status === "scheduled" ? (
              <Button variant="outline" onClick={() => cancel.mutate(pending.id)} disabled={cancel.isPending} data-testid="cancel-delete">{t("deleteCancel")}</Button>
            ) : null}
          </AlertDescription>
        </Alert>
      ) : (
        <form onSubmit={submit} className="space-y-3">
          <div className="space-y-1.5">
            <Label htmlFor="delete-confirm">{t("deleteType", { slug: active.tenant_slug })}</Label>
            <Input id="delete-confirm" value={typed} onChange={(e) => setTyped(e.target.value)} autoComplete="off" dir="ltr" className="max-w-sm" data-testid="delete-confirm" />
          </div>
          <Button type="submit" variant="destructive" disabled={!matches || start.isPending} data-testid="delete-organization">
            <Trash2 className="size-4" aria-hidden="true" />
            {t("deleteButton")}
          </Button>
        </form>
      )}
      {request?.status === "cancelled" ? <p className="text-sm text-muted-foreground">{t("deleteWasCancelled")}</p> : null}
    </section>
  );
}
