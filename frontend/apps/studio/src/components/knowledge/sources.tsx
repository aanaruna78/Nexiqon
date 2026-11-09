"use client";

import { useMutation, useQueryClient } from "@tanstack/react-query";
import { ArrowLeft, CalendarClock, Database, GitBranch, Globe, type LucideIcon, Plug, Play, Plus, Trash2, Upload } from "lucide-react";
import { useFormatter, useNow, useTranslations } from "next-intl";
import { type FormEvent, useState } from "react";
import { toast } from "sonner";

import { problemErrors, type FieldErrors, type JsonSchema, validate } from "@/components/schema-form/schema";
import { SchemaForm } from "@/components/schema-form/schema-form";
import {
  AlertDialog,
  AlertDialogAction,
  AlertDialogCancel,
  AlertDialogContent,
  AlertDialogDescription,
  AlertDialogFooter,
  AlertDialogHeader,
  AlertDialogTitle,
} from "@/components/ui/alert-dialog";
import { Button } from "@/components/ui/button";
import { Dialog, DialogContent, DialogDescription, DialogFooter, DialogHeader, DialogTitle } from "@/components/ui/dialog";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import { Skeleton } from "@/components/ui/skeleton";
import { Switch } from "@/components/ui/switch";
import { Hint } from "@/components/visual/hint";
import { IconTile, type Tone } from "@/components/visual/icon-tile";
import { StatusBadge } from "@/components/visual/status-badge";
import { api, ApiError } from "@/lib/api";
import { useErrorToast } from "@/lib/hooks";
import type { KnowledgeDocument, PluginManifest, Run, Source } from "@/lib/knowledge";
import { usePlugins, useSources } from "@/lib/knowledge-hooks";

import { slugify } from "./collections";

const ICONS: Record<string, [LucideIcon, Tone]> = {
  globe: [Globe, "sky"],
  bucket: [Database, "amber"],
  git: [GitBranch, "violet"],
  upload: [Upload, "teal"],
};

export function connectorVisual(icon: string | null): [LucideIcon, Tone] {
  return ICONS[icon ?? ""] ?? [Plug, "slate"];
}

export function SourcesPanel({ collectionId, documents }: { collectionId: string; documents: KnowledgeDocument[] }) {
  const t = useTranslations("knowledge");
  const tc = useTranslations("common");
  const format = useFormatter();
  const now = useNow({ updateInterval: 30_000 });
  const sources = useSources(collectionId);
  const connectors = usePlugins("connector");
  const queryClient = useQueryClient();
  const onError = useErrorToast();
  const [adding, setAdding] = useState(false);
  const [removing, setRemoving] = useState<Source | null>(null);
  const refresh = () => {
    for (const key of ["sources", "runs", "documents", "collection"]) void queryClient.invalidateQueries({ queryKey: [key, collectionId] });
  };
  const sync = useMutation({
    mutationFn: (id: string) => api<Run>(`ingestion/v1/sources/${id}/sync`, { method: "POST" }),
    onSuccess: () => {
      toast.success(t("syncStarted"));
      refresh();
    },
    onError,
  });
  const del = useMutation({
    mutationFn: (id: string) => api(`ingestion/v1/sources/${id}`, { method: "DELETE" }),
    onSuccess: () => {
      toast.success(t("sourceDeleted"));
      refresh();
    },
    onError,
  });

  const list = (sources.data ?? []).filter((s) => s.connector !== "upload");
  const manifest = (name: string) => connectors.data?.find((c) => c.name === name);

  return (
    <div className="space-y-4">
      <div className="flex items-center justify-between gap-3">
        <p className="text-sm text-muted-foreground">{t("sourcesIntro")}</p>
        <Button onClick={() => setAdding(true)} data-testid="add-source" size="sm">
          <Plus className="size-4" aria-hidden="true" />
          {t("addSource")}
        </Button>
      </div>
      {sources.isLoading ? (
        <Skeleton className="h-24" />
      ) : !list.length ? (
        <p className="rounded-xl border border-dashed p-8 text-center text-sm text-muted-foreground">{t("noSources")}</p>
      ) : (
        <ul className="grid gap-3 md:grid-cols-2">
          {list.map((s) => {
            const [Icon, tone] = connectorVisual(manifest(s.connector)?.icon ?? null);
            const count = documents.filter((d) => d.source_id === s.id).length;
            return (
              <li key={s.id} className="nx-card flex flex-col gap-3 p-4" data-testid={`source-${s.name}`}>
                <div className="flex items-start justify-between gap-3">
                  <div className="flex min-w-0 items-center gap-3">
                    <IconTile icon={Icon} tone={tone} size="sm" />
                    <div className="min-w-0">
                      <div className="truncate font-medium">{s.name}</div>
                      <div className="truncate text-xs text-muted-foreground">{manifest(s.connector)?.title ?? s.connector}</div>
                    </div>
                  </div>
                  <StatusBadge tone={s.status === "syncing" ? "sky" : "slate"} live={s.status === "syncing"}>
                    {t(`sourceStatus.${s.status}`)}
                  </StatusBadge>
                </div>
                <div className="flex flex-wrap gap-x-4 gap-y-1 text-xs text-muted-foreground">
                  <span>{t("documentCount", { count })}</span>
                  <span>{s.last_synced_at ? t("lastSynced", { when: format.relativeTime(new Date(s.last_synced_at), now) }) : t("neverSynced")}</span>
                  {s.schedule_hours ? (
                    <span className="inline-flex items-center gap-1">
                      <CalendarClock className="size-3.5" aria-hidden="true" />
                      {t("every", { hours: s.schedule_hours })}
                    </span>
                  ) : null}
                </div>
                <div className="flex gap-2">
                  <Hint label={t("syncHint")}>
                    <Button size="sm" variant="outline" disabled={s.status === "syncing" || sync.isPending} onClick={() => sync.mutate(s.id)} aria-label={`${t("syncNow")}: ${s.name}`}>
                      <Play className="size-3.5" aria-hidden="true" />
                      {t("syncNow")}
                    </Button>
                  </Hint>
                  <Button size="sm" variant="ghost" className="hover:text-destructive" onClick={() => setRemoving(s)} aria-label={`${tc("delete")}: ${s.name}`}>
                    <Trash2 className="size-3.5" aria-hidden="true" />
                    {tc("delete")}
                  </Button>
                </div>
              </li>
            );
          })}
        </ul>
      )}
      <AddSourceDialog collectionId={collectionId} open={adding} onOpenChange={setAdding} connectors={connectors.data ?? []} onAdded={refresh} />
      <AlertDialog open={!!removing} onOpenChange={(o) => !o && setRemoving(null)}>
        <AlertDialogContent>
          <AlertDialogHeader>
            <AlertDialogTitle>{t("deleteSourceTitle", { name: removing?.name ?? "" })}</AlertDialogTitle>
            <AlertDialogDescription>
              {t("deleteSourceBody", { count: documents.filter((d) => d.source_id === removing?.id).length })}
            </AlertDialogDescription>
          </AlertDialogHeader>
          <AlertDialogFooter>
            <AlertDialogCancel>{tc("cancel")}</AlertDialogCancel>
            <AlertDialogAction onClick={() => removing && del.mutate(removing.id)}>{tc("delete")}</AlertDialogAction>
          </AlertDialogFooter>
        </AlertDialogContent>
      </AlertDialog>
    </div>
  );
}

function AddSourceDialog({
  collectionId,
  open,
  onOpenChange,
  connectors,
  onAdded,
}: {
  collectionId: string;
  open: boolean;
  onOpenChange: (open: boolean) => void;
  connectors: PluginManifest[];
  onAdded: () => void;
}) {
  const t = useTranslations("knowledge");
  const tc = useTranslations("common");
  const onError = useErrorToast();
  const [picked, setPicked] = useState<PluginManifest | null>(null);
  const [name, setName] = useState("");
  const [config, setConfig] = useState<Record<string, unknown>>({});
  const [schedule, setSchedule] = useState(false);
  const [hours, setHours] = useState(24);
  const [syncNow, setSyncNow] = useState(true);
  const [errors, setErrors] = useState<FieldErrors>({});
  const gallery = connectors.filter((c) => !c.capabilities.includes("push"));

  function reset(next: boolean) {
    if (!next) {
      setPicked(null);
      setConfig({});
      setErrors({});
      setName("");
    }
    onOpenChange(next);
  }

  const create = useMutation({
    mutationFn: async () => {
      const source = await api<Source>(`ingestion/v1/collections/${collectionId}/sources`, {
        method: "POST",
        json: { name, connector: picked?.name, config, schedule_hours: schedule ? hours : null },
      });
      if (syncNow) await api(`ingestion/v1/sources/${source.id}/sync`, { method: "POST" });
      return source;
    },
    onSuccess: (s) => {
      toast.success(syncNow ? t("sourceAddedSyncing", { name: s.name }) : t("sourceAdded", { name: s.name }));
      onAdded();
      reset(false);
    },
    onError: (err) => {
      if (err instanceof ApiError && err.problem.errors?.length) {
        setErrors(problemErrors(err.problem.errors.map((e) => ({ path: e.message?.split(":")[0], message: e.message?.split(": ").slice(1).join(": ") }))));
      } else onError(err);
    },
  });

  function submit(event: FormEvent) {
    event.preventDefault();
    if (!picked) return;
    const found = validate(picked.config_schema as JsonSchema, config);
    if (!/^[a-z0-9][a-z0-9-]{1,62}$/.test(name)) found.name = t("nameRule");
    setErrors(found);
    if (Object.keys(found).length === 0) create.mutate();
  }

  return (
    <Dialog open={open} onOpenChange={reset}>
      <DialogContent className="max-h-[90vh] overflow-y-auto sm:max-w-2xl">
        {!picked ? (
          <>
            <DialogHeader>
              <DialogTitle>{t("addSource")}</DialogTitle>
              <DialogDescription>{t("addSourceBody")}</DialogDescription>
            </DialogHeader>
            <ul className="grid gap-3 sm:grid-cols-2" aria-label={t("connectorGallery")}>
              {gallery.map((c) => {
                const [Icon, tone] = connectorVisual(c.icon);
                return (
                  <li key={c.name}>
                    <button
                      type="button"
                      onClick={() => {
                        setPicked(c);
                        setName(slugify(c.title));
                      }}
                      className="nx-card nx-lift flex h-full w-full items-start gap-3 p-4 text-start outline-none focus-visible:ring-2 focus-visible:ring-ring"
                      data-testid={`connector-${c.name}`}
                    >
                      <IconTile icon={Icon} tone={tone} size="sm" />
                      <span className="min-w-0">
                        <span className="block font-medium">{c.title}</span>
                        <span className="block text-xs text-muted-foreground">{c.description}</span>
                      </span>
                    </button>
                  </li>
                );
              })}
            </ul>
          </>
        ) : (
          <form onSubmit={submit} className="space-y-5" noValidate>
            <DialogHeader>
              <DialogTitle className="flex items-center gap-2">
                <Button type="button" variant="ghost" size="icon" className="-ms-2 size-8" onClick={() => setPicked(null)} aria-label={tc("back")}>
                  <ArrowLeft className="size-4 rtl:rotate-180" aria-hidden="true" />
                </Button>
                {picked.title}
              </DialogTitle>
              <DialogDescription>{picked.description}</DialogDescription>
            </DialogHeader>
            <div className="space-y-2">
              <Label htmlFor="source-name">{tc("name")}</Label>
              <Input id="source-name" value={name} onChange={(e) => setName(slugify(e.target.value))} aria-invalid={!!errors.name} dir="ltr" />
              {errors.name ? <p className="text-sm text-destructive">{errors.name}</p> : null}
            </div>
            <SchemaForm schema={picked.config_schema as JsonSchema} value={config} onChange={setConfig} errors={errors} />
            <div className="space-y-3 rounded-xl bg-muted/40 p-4">
              <div className="flex items-center justify-between gap-3">
                <Label htmlFor="source-schedule">{t("scheduleLabel")}</Label>
                <Switch id="source-schedule" checked={schedule} onCheckedChange={setSchedule} />
              </div>
              {schedule ? (
                <div className="flex items-center gap-2">
                  <Label htmlFor="source-hours" className="text-sm font-normal text-muted-foreground">{t("everyHours")}</Label>
                  <Input id="source-hours" type="number" min={1} max={720} value={hours} onChange={(e) => setHours(Number(e.target.value) || 24)} className="w-24" />
                </div>
              ) : null}
              <div className="flex items-center justify-between gap-3">
                <Label htmlFor="source-sync">{t("syncAfterAdding")}</Label>
                <Switch id="source-sync" checked={syncNow} onCheckedChange={setSyncNow} />
              </div>
            </div>
            <DialogFooter>
              <Button type="button" variant="outline" onClick={() => reset(false)}>{tc("cancel")}</Button>
              <Button type="submit" disabled={create.isPending} data-testid="save-source">{t("addSource")}</Button>
            </DialogFooter>
          </form>
        )}
      </DialogContent>
    </Dialog>
  );
}
