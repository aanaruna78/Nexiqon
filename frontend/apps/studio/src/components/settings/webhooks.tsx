"use client";

import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { Send, Trash2, Webhook } from "lucide-react";
import { useFormatter, useTranslations } from "next-intl";
import { type FormEvent, useState } from "react";
import { toast } from "sonner";

import { EmptyState } from "@/components/empty-state";
import { PageHeader } from "@/components/page-header";
import { Alert, AlertDescription, AlertTitle } from "@/components/ui/alert";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import { Switch } from "@/components/ui/switch";
import { StatusBadge } from "@/components/visual/status-badge";
import { api } from "@/lib/api";
import { useErrorToast } from "@/lib/hooks";

import { TagInput } from "../assistants/tag-input";

interface Hook {
  id: string;
  url: string;
  description: string;
  events: string[];
  enabled: boolean;
  failures: number;
  created_at: string;
}

interface DeliveryRow {
  id: string;
  event_type: string;
  status: "pending" | "delivered" | "failed";
  attempts: number;
  response_status: number | null;
  error: string | null;
  created_at: string;
}

export const SUGGESTED_EVENTS = ["conversation.escalated", "evaluation.*", "metering.budget.*", "governance.*", "config.version.published"];

/** Webhooks (NT-01): platform events sent to your systems, signed. */
export function WebhooksPage() {
  const t = useTranslations("webhooks");
  const client = useQueryClient();
  const onError = useErrorToast();
  const hooks = useQuery({ queryKey: ["webhooks"], queryFn: () => api<Hook[]>("notification/v1/webhooks") });
  const [url, setUrl] = useState("");
  const [events, setEvents] = useState<string[]>([]);
  const [secret, setSecret] = useState<string | null>(null);
  const create = useMutation({
    mutationFn: () => api<Hook & { secret: string }>("notification/v1/webhooks", { method: "POST", json: { url, events } }),
    onSuccess: async (h) => {
      setSecret(h.secret);
      setUrl("");
      setEvents([]);
      await client.invalidateQueries({ queryKey: ["webhooks"] });
    },
    onError,
  });

  function submit(e: FormEvent) {
    e.preventDefault();
    if (url.startsWith("https://")) create.mutate();
  }

  return (
    <div className="space-y-8">
      <PageHeader title={t("title")} description={t("subtitle")} icon={Webhook} tone="rose" />
      <form onSubmit={submit} className="nx-card max-w-3xl space-y-4 p-5" aria-labelledby="new-hook">
        <h2 id="new-hook" className="font-semibold">{t("add")}</h2>
        <div className="space-y-1.5">
          <Label htmlFor="hook-url">{t("url")}</Label>
          <Input id="hook-url" value={url} onChange={(e) => setUrl(e.target.value)} placeholder="https://example.com/hooks/nexiqon" dir="ltr" data-testid="hook-url" />
          <p className="text-xs text-muted-foreground">{t("urlHelp")}</p>
        </div>
        <div className="space-y-1.5">
          <Label htmlFor="hook-events">{t("events")}</Label>
          <TagInput id="hook-events" values={events} onChange={setEvents} placeholder={SUGGESTED_EVENTS.join(" · ")} />
          <p className="text-xs text-muted-foreground">{t("eventsHelp")}</p>
        </div>
        <Button type="submit" disabled={!url.startsWith("https://") || create.isPending} data-testid="create-hook">{t("create")}</Button>
      </form>
      {secret ? (
        <Alert data-testid="hook-secret">
          <AlertTitle>{t("secretTitle")}</AlertTitle>
          <AlertDescription className="space-y-2">
            <p>{t("secretHelp")}</p>
            <code className="block rounded-md bg-muted px-2 py-1 font-mono text-xs break-all" dir="ltr">{secret}</code>
          </AlertDescription>
        </Alert>
      ) : null}
      {hooks.data && !hooks.data.length ? (
        <EmptyState icon={Webhook} tone="rose" title={t("emptyTitle")} body={t("emptyBody")} />
      ) : (
        <ul className="max-w-3xl space-y-3" data-testid="hooks">
          {(hooks.data ?? []).map((h) => <HookRow key={h.id} hook={h} />)}
        </ul>
      )}
    </div>
  );
}

function HookRow({ hook: h }: { hook: Hook }) {
  const t = useTranslations("webhooks");
  const format = useFormatter();
  const client = useQueryClient();
  const onError = useErrorToast();
  const refresh = () => Promise.all([client.invalidateQueries({ queryKey: ["webhooks"] }), client.invalidateQueries({ queryKey: ["deliveries", h.id] })]);
  const deliveries = useQuery({ queryKey: ["deliveries", h.id], queryFn: () => api<DeliveryRow[]>(`notification/v1/webhooks/${h.id}/deliveries`) });
  const toggle = useMutation({ mutationFn: (enabled: boolean) => api(`notification/v1/webhooks/${h.id}`, { method: "PATCH", json: { enabled } }), onSuccess: refresh, onError });
  const remove = useMutation({ mutationFn: () => api(`notification/v1/webhooks/${h.id}`, { method: "DELETE" }), onSuccess: refresh, onError });
  const test = useMutation({
    mutationFn: () => api<DeliveryRow>(`notification/v1/webhooks/${h.id}/test`, { method: "POST" }),
    onSuccess: async (d) => {
      if (d.status === "delivered") toast.success(t("testOk"));
      else toast.error(t("testFailed", { detail: d.error ?? String(d.response_status ?? "") }));
      await refresh();
    },
    onError,
  });
  return (
    <li className="nx-card space-y-3 p-4">
      <div className="flex flex-wrap items-center justify-between gap-2">
        <span className="flex min-w-0 flex-col">
          <span className="truncate font-mono text-sm" dir="ltr">{h.url}</span>
          <span className="text-xs text-muted-foreground">{h.events.length ? h.events.join(", ") : t("allEvents")}</span>
        </span>
        <span className="flex items-center gap-2">
          {!h.enabled && h.failures ? <StatusBadge tone="rose">{t("switchedOff")}</StatusBadge> : null}
          <Switch checked={h.enabled} onCheckedChange={(v) => toggle.mutate(v)} aria-label={t("enabled", { url: h.url })} />
          <Button variant="outline" size="sm" onClick={() => test.mutate()} disabled={test.isPending} data-testid="test-hook">
            <Send className="size-4" aria-hidden="true" />
            {t("test")}
          </Button>
          <Button variant="ghost" size="icon" aria-label={t("remove", { url: h.url })} onClick={() => remove.mutate()}>
            <Trash2 className="size-4" aria-hidden="true" />
          </Button>
        </span>
      </div>
      {deliveries.data?.length ? (
        <ul className="divide-y text-sm" aria-label={t("recent")}>
          {deliveries.data.slice(0, 5).map((d) => (
            <li key={d.id} className="flex flex-wrap items-center justify-between gap-2 py-1.5">
              <span className="font-mono text-xs">{d.event_type.replace(/^nexiqon\./, "")}</span>
              <span className="flex items-center gap-2 text-xs text-muted-foreground">
                {format.relativeTime(new Date(d.created_at))}
                <StatusBadge tone={d.status === "delivered" ? "teal" : d.status === "failed" ? "rose" : "amber"}>
                  {t(`delivery.${d.status}`, { attempts: d.attempts })}
                </StatusBadge>
              </span>
            </li>
          ))}
        </ul>
      ) : null}
    </li>
  );
}
