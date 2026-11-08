"use client";

import { useInfiniteQuery, useMutation, useQuery } from "@tanstack/react-query";
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
import { Avatar } from "@/components/visual/avatar";
import { Hint } from "@/components/visual/hint";
import { toneClasses, type Tone } from "@/components/visual/icon-tile";
import { cn } from "@/lib/utils";

const SERVICE_TONE: Record<string, Tone> = { identity: "violet", config: "teal", audit: "sky", governance: "rose" };

function EventChip({ type }: { type: string }) {
  const [service, ...rest] = type.replace(/^nexiqon\./, "").split(".");
  return (
    <span className="inline-flex items-center gap-1.5 font-mono text-xs" dir="ltr">
      <span className={cn("rounded px-1.5 py-0.5 font-sans font-medium", toneClasses(SERVICE_TONE[service] ?? "slate"))}>{service}</span>
      {rest.join(".")}
    </span>
  );
}

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
  const th = useTranslations("hints");
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
  // Show people, not ids: map actor ids to member names (keys and services get a label).
  const members = useQuery({
    queryKey: ["members"],
    queryFn: () => api<{ user_id: string | null; display_name: string | null; email: string | null }[]>("identity/v1/members"),
    staleTime: 60_000,
  });
  const people = new Map((members.data ?? []).filter((m) => m.user_id).map((m) => [m.user_id as string, m.display_name ?? m.email ?? ""]));
  const actorName = (id: string): string =>
    people.get(id) ?? (id.startsWith("key:") ? t("actorKey") : id.startsWith("service:") || id.startsWith("workflow:") || id === "clerk-webhook" ? t("actorSystem") : id);

  if (events.error instanceof ApiError && events.error.status === 403) {
    return (
      <div className="space-y-8">
        <PageHeader title={t("title")} description={t("subtitle")} icon={ScrollText} tone="sky" />
        <EmptyState icon={ShieldAlert} tone="rose" title={t("forbidden")} />
      </div>
    );
  }
  const rows = events.data?.pages.flatMap((p) => p.items) ?? [];

  return (
    <div className="space-y-6">
      <PageHeader
        title={t("title")}
        description={t("subtitle")}
        icon={ScrollText}
        tone="sky"
        actions={
          <Hint label={th("verifyChain")} side="bottom">
            <Button variant="outline" className="bg-card shadow-sm" onClick={() => verify.mutate()} disabled={verify.isPending} data-testid="verify-chain">
              <ShieldCheck className="size-4" aria-hidden="true" />
              {verify.isPending ? t("verifying") : t("verify")}
            </Button>
          </Hint>
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
        <EmptyState icon={ScrollText} tone="sky" title={t("empty")} />
      ) : (
        <>
          <div className="nx-card overflow-x-auto">
          <Table>
            <TableHeader>
              <TableRow>
                <TableHead className="w-16">#</TableHead>
                <TableHead>{t("time")}</TableHead>
                <TableHead>{t("event")}</TableHead>
                <TableHead className="hidden md:table-cell">{t("actor")}</TableHead>
                <TableHead className="hidden lg:table-cell">{t("trace")}</TableHead>
              </TableRow>
            </TableHeader>
            <TableBody className="nx-stagger">
              {rows.map((e) => (
                <TableRow key={e.seq}>
                  <TableCell className="text-muted-foreground">{e.seq}</TableCell>
                  <TableCell className="whitespace-nowrap">{format.dateTime(new Date(e.occurred_at), { dateStyle: "medium", timeStyle: "short" })}</TableCell>
                  <TableCell><EventChip type={e.type} /></TableCell>
                  <TableCell className="hidden md:table-cell" title={e.actor_id}>
                    <span className="flex max-w-56 items-center gap-2">
                      <Avatar name={actorName(e.actor_id)} className="size-6 text-[10px] ring-0" />
                      <span className="truncate">{actorName(e.actor_id)}</span>
                    </span>
                  </TableCell>
                  <TableCell className="hidden lg:table-cell">
                    {e.trace_id ? (
                      <Hint label={<span className="grid gap-1"><span>{th("traceId")}</span><code className="break-all font-mono text-[11px]" dir="ltr">{e.trace_id}</code></span>}>
                        <code dir="ltr" tabIndex={0} className="cursor-help rounded text-xs text-muted-foreground outline-none focus-visible:ring-2 focus-visible:ring-ring">{e.trace_id.slice(0, 12)}…</code>
                      </Hint>
                    ) : "—"}
                  </TableCell>
                </TableRow>
              ))}
            </TableBody>
          </Table>
          </div>
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
