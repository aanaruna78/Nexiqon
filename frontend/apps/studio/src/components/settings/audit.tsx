"use client";

import { useInfiniteQuery, useMutation } from "@tanstack/react-query";
import { ScrollText, ShieldAlert, ShieldCheck } from "lucide-react";
import { useFormatter, useTranslations } from "next-intl";
import { useDeferredValue, useState } from "react";

import { EmptyState } from "@/components/empty-state";
import { PageHeader } from "@/components/page-header";
import { Alert, AlertDescription } from "@/components/ui/alert";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import { Skeleton } from "@/components/ui/skeleton";
import { Table, TableBody, TableCell, TableHead, TableHeader, TableRow } from "@/components/ui/table";
import { api, ApiError } from "@/lib/api";

interface AuditEvent {
  seq: number;
  type: string;
  actor_id: string;
  subject: string | null;
  occurred_at: string;
  trace_id: string | null;
}

interface Page {
  items: AuditEvent[];
  next_before_seq: number | null;
}

interface Verification {
  ok: boolean;
  length: number;
  first_broken_seq: number | null;
}

export function AuditPage() {
  const t = useTranslations("audit");
  const format = useFormatter();
  const [filter, setFilter] = useState("");
  const type = useDeferredValue(filter.trim());
  const events = useInfiniteQuery({
    queryKey: ["audit", type],
    initialPageParam: null as number | null,
    queryFn: ({ pageParam }) => {
      const params = new URLSearchParams({ limit: "50" });
      if (type) params.set("type", type.endsWith("*") ? type : `${type}*`);
      if (pageParam) params.set("before_seq", String(pageParam));
      return api<Page>(`audit/v1/events?${params}`);
    },
    getNextPageParam: (last) => last.next_before_seq,
    retry: (count, err) => !(err instanceof ApiError && err.status === 403) && count < 1,
  });
  const verify = useMutation({ mutationFn: () => api<Verification>("audit/v1/verify") });

  if (events.error instanceof ApiError && events.error.status === 403) {
    return (
      <div className="space-y-8">
        <PageHeader title={t("title")} description={t("subtitle")} />
        <EmptyState icon={ShieldAlert} title={t("forbidden")} />
      </div>
    );
  }
  const rows = events.data?.pages.flatMap((p) => p.items) ?? [];

  return (
    <div className="space-y-6">
      <PageHeader
        title={t("title")}
        description={t("subtitle")}
        actions={
          <Button variant="outline" onClick={() => verify.mutate()} disabled={verify.isPending} data-testid="verify-chain">
            <ShieldCheck className="size-4" aria-hidden="true" />
            {verify.isPending ? t("verifying") : t("verify")}
          </Button>
        }
      />
      {verify.data ? (
        <Alert variant={verify.data.ok ? "default" : "destructive"} role="status">
          {verify.data.ok ? <ShieldCheck aria-hidden="true" /> : <ShieldAlert aria-hidden="true" />}
          <AlertDescription data-testid="chain-status">
            {verify.data.ok ? t("chainOk", { count: verify.data.length }) : t("chainBroken", { seq: verify.data.first_broken_seq ?? 0 })}
          </AlertDescription>
        </Alert>
      ) : null}
      <div className="max-w-sm space-y-2">
        <Label htmlFor="audit-filter">{t("filterType")}</Label>
        <Input id="audit-filter" dir="ltr" placeholder="nexiqon.identity." value={filter} onChange={(e) => setFilter(e.target.value)} />
      </div>
      {events.isLoading ? (
        <Skeleton className="h-40 w-full" />
      ) : rows.length === 0 ? (
        <EmptyState icon={ScrollText} title={t("empty")} />
      ) : (
        <>
          <Table>
            <TableHeader>
              <TableRow>
                <TableHead className="w-16">#</TableHead>
                <TableHead>{t("time")}</TableHead>
                <TableHead>{t("event")}</TableHead>
                <TableHead>{t("actor")}</TableHead>
                <TableHead>{t("trace")}</TableHead>
              </TableRow>
            </TableHeader>
            <TableBody>
              {rows.map((e) => (
                <TableRow key={e.seq}>
                  <TableCell className="text-muted-foreground">{e.seq}</TableCell>
                  <TableCell className="whitespace-nowrap">{format.dateTime(new Date(e.occurred_at), { dateStyle: "medium", timeStyle: "short" })}</TableCell>
                  <TableCell><code dir="ltr" className="text-xs">{e.type.replace(/^nexiqon\./, "")}</code></TableCell>
                  <TableCell className="max-w-48 truncate" title={e.actor_id}>{e.actor_id}</TableCell>
                  <TableCell><code dir="ltr" className="text-xs text-muted-foreground">{e.trace_id ? e.trace_id.slice(0, 12) : "—"}</code></TableCell>
                </TableRow>
              ))}
            </TableBody>
          </Table>
          {events.hasNextPage ? (
            <Button variant="outline" onClick={() => events.fetchNextPage()} disabled={events.isFetchingNextPage}>
              {t("loadMore")}
            </Button>
          ) : null}
        </>
      )}
    </div>
  );
}
