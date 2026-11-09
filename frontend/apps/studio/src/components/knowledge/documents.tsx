"use client";

import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { FileText, Globe, Lightbulb, ListTree, RefreshCw, Trash2 } from "lucide-react";
import { useFormatter, useLocale, useNow, useTranslations } from "next-intl";
import { useRef, useState } from "react";
import { toast } from "sonner";

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
import { Select, SelectContent, SelectItem, SelectTrigger, SelectValue } from "@/components/ui/select";
import { Sheet, SheetContent, SheetDescription, SheetHeader, SheetTitle } from "@/components/ui/sheet";
import { Skeleton } from "@/components/ui/skeleton";
import { Table, TableBody, TableCell, TableHead, TableHeader, TableRow } from "@/components/ui/table";
import { Hint } from "@/components/visual/hint";
import { StatusBadge } from "@/components/visual/status-badge";
import { api } from "@/lib/api";
import { useErrorToast } from "@/lib/hooks";
import {
  documentLabel,
  documentTone,
  type DocumentStatus,
  errorHintKey,
  formatBytes,
  isBusy,
  isWebUri,
  type KnowledgeDocument,
  type OutlineNode,
} from "@/lib/knowledge";
import { useDocuments } from "@/lib/knowledge-hooks";

const FILTERS: ("all" | DocumentStatus)[] = ["all", "ready", "processing", "pending", "failed", "quarantined"];

export function DocumentsTable({ collectionId }: { collectionId: string }) {
  const t = useTranslations("knowledge");
  const tc = useTranslations("common");
  const format = useFormatter();
  const now = useNow({ updateInterval: 30_000 });
  const docs = useDocuments(collectionId);
  const [filter, setFilter] = useState<(typeof FILTERS)[number]>("all");
  const [open, setOpen] = useState<KnowledgeDocument | null>(null);
  const [remove, setRemove] = useState<KnowledgeDocument | null>(null);
  const replaceInput = useRef<HTMLInputElement>(null);
  const [replacing, setReplacing] = useState<KnowledgeDocument | null>(null);
  const queryClient = useQueryClient();
  const onError = useErrorToast();

  const refresh = () => {
    void queryClient.invalidateQueries({ queryKey: ["documents", collectionId] });
    void queryClient.invalidateQueries({ queryKey: ["runs", collectionId] });
    void queryClient.invalidateQueries({ queryKey: ["collection", collectionId] });
  };
  const del = useMutation({
    mutationFn: (id: string) => api(`ingestion/v1/documents/${id}`, { method: "DELETE" }),
    onSuccess: () => {
      toast.success(t("documentDeleted"));
      refresh();
    },
    onError,
  });
  const replace = useMutation({
    mutationFn: async ({ doc, file }: { doc: KnowledgeDocument; file: File }) => {
      const filename = doc.uri.replace(/^upload:\/\//, "");
      return api(`ingestion/v1/collections/${collectionId}/documents?filename=${encodeURIComponent(filename)}`, {
        method: "POST",
        body: file,
        headers: { "content-type": file.type || "application/octet-stream" },
      });
    },
    onSuccess: () => {
      toast.success(t("replaced"));
      refresh();
    },
    onError,
  });

  if (docs.isLoading) return <Skeleton className="h-40" />;
  const all = docs.data ?? [];
  const rows = filter === "all" ? all : all.filter((d) => d.status === filter);
  const counts = Object.fromEntries(FILTERS.map((f) => [f, f === "all" ? all.length : all.filter((d) => d.status === f).length]));

  return (
    <div className="space-y-3">
      <div className="flex flex-wrap items-center justify-between gap-2">
        <p className="text-sm text-muted-foreground" aria-live="polite">
          {all.some((d) => isBusy(d.status)) ? t("processingLive") : t("documentCount", { count: all.length })}
        </p>
        <div className="flex items-center gap-2">
          <label htmlFor="doc-filter" className="text-sm text-muted-foreground">{t("show")}</label>
          <Select value={filter} onValueChange={(v) => setFilter(v as typeof filter)}>
            <SelectTrigger id="doc-filter" className="w-44" size="sm">
              <SelectValue />
            </SelectTrigger>
            <SelectContent>
              {FILTERS.map((f) => (
                <SelectItem key={f} value={f}>{`${t(`statuses.${f}`)} (${counts[f]})`}</SelectItem>
              ))}
            </SelectContent>
          </Select>
        </div>
      </div>
      <input
        ref={replaceInput}
        type="file"
        className="sr-only"
        tabIndex={-1}
        aria-label={t("replace")}
        onChange={(e) => {
          const file = e.target.files?.[0];
          if (file && replacing) replace.mutate({ doc: replacing, file });
          e.target.value = "";
        }}
      />
      {!rows.length ? (
        <p className="rounded-xl border border-dashed p-8 text-center text-sm text-muted-foreground">{t("noDocuments")}</p>
      ) : (
        <div className="nx-card overflow-x-auto">
          <Table>
            <TableHeader>
              <TableRow>
                <TableHead>{t("document")}</TableHead>
                <TableHead>{tc("status")}</TableHead>
                <TableHead className="hidden md:table-cell">{t("chunks")}</TableHead>
                <TableHead className="hidden lg:table-cell">{t("updated")}</TableHead>
                <TableHead className="w-28"><span className="sr-only">{tc("actions")}</span></TableHead>
              </TableRow>
            </TableHeader>
            <TableBody>
              {rows.map((d) => (
                <TableRow key={d.id} data-testid={`doc-${documentLabel(d)}`}>
                  <TableCell className="max-w-0 w-full">
                    <button type="button" onClick={() => setOpen(d)} className="flex min-w-0 items-center gap-3 text-start hover:text-primary focus-visible:outline-none focus-visible:underline">
                      {isWebUri(d.uri) ? <Globe className="size-4 shrink-0 text-muted-foreground" aria-hidden="true" /> : <FileText className="size-4 shrink-0 text-muted-foreground" aria-hidden="true" />}
                      <span className="min-w-0">
                        <span className="block truncate font-medium">{documentLabel(d)}</span>
                        <span className="block truncate text-xs text-muted-foreground" dir="ltr">{d.uri}</span>
                      </span>
                    </button>
                    {d.error_code ? <FixHint doc={d} /> : null}
                  </TableCell>
                  <TableCell>
                    <StatusBadge tone={documentTone(d.status)} live={isBusy(d.status)}>{t(`statuses.${d.status}`)}</StatusBadge>
                  </TableCell>
                  <TableCell className="hidden tabular-nums md:table-cell">{d.status === "ready" ? d.chunk_count : "—"}</TableCell>
                  <TableCell className="hidden text-muted-foreground lg:table-cell">{format.relativeTime(new Date(d.updated_at), now)}</TableCell>
                  <TableCell>
                    <div className="flex justify-end gap-1">
                      {d.uri.startsWith("upload://") ? (
                        <Hint label={t("replaceHint")}>
                          <Button
                            variant="ghost"
                            size="icon"
                            aria-label={`${t("replace")}: ${documentLabel(d)}`}
                            onClick={() => {
                              setReplacing(d);
                              replaceInput.current?.click();
                            }}
                          >
                            <RefreshCw className="size-4" aria-hidden="true" />
                          </Button>
                        </Hint>
                      ) : null}
                      <Hint label={t("deleteHint")}>
                        <Button variant="ghost" size="icon" className="hover:text-destructive" aria-label={`${tc("delete")}: ${documentLabel(d)}`} onClick={() => setRemove(d)}>
                          <Trash2 className="size-4" aria-hidden="true" />
                        </Button>
                      </Hint>
                    </div>
                  </TableCell>
                </TableRow>
              ))}
            </TableBody>
          </Table>
        </div>
      )}
      <AlertDialog open={!!remove} onOpenChange={(o) => !o && setRemove(null)}>
        <AlertDialogContent>
          <AlertDialogHeader>
            <AlertDialogTitle>{t("deleteDocumentTitle", { name: remove ? documentLabel(remove) : "" })}</AlertDialogTitle>
            <AlertDialogDescription>
              {t("deleteDocumentBody", { chunks: remove?.chunk_count ?? 0 })}
            </AlertDialogDescription>
          </AlertDialogHeader>
          <AlertDialogFooter>
            <AlertDialogCancel>{tc("cancel")}</AlertDialogCancel>
            <AlertDialogAction onClick={() => remove && del.mutate(remove.id)}>{tc("delete")}</AlertDialogAction>
          </AlertDialogFooter>
        </AlertDialogContent>
      </AlertDialog>
      <DocumentSheet doc={open} onClose={() => setOpen(null)} />
    </div>
  );
}

function FixHint({ doc }: { doc: KnowledgeDocument }) {
  const t = useTranslations("knowledge");
  return (
    <div className="mt-2 flex gap-2 rounded-lg bg-amber-50 px-3 py-2 text-xs text-amber-950 dark:bg-amber-400/10 dark:text-amber-100" role="note">
      <Lightbulb className="mt-0.5 size-3.5 shrink-0" aria-hidden="true" />
      <div className="min-w-0 space-y-0.5">
        <p className="font-medium">{t(`errorHints.${errorHintKey(doc.error_code)}`)}</p>
        {doc.error_detail ? <p className="break-words opacity-80">{doc.error_detail}</p> : null}
      </div>
    </div>
  );
}

function DocumentSheet({ doc, onClose }: { doc: KnowledgeDocument | null; onClose: () => void }) {
  const t = useTranslations("knowledge");
  const locale = useLocale();
  const outline = useQuery({
    queryKey: ["outline", doc?.id, doc?.indexed_version],
    queryFn: () => api<{ nodes: OutlineNode[] }>(`retrieval/v1/index/documents/${doc?.id}/outline`),
    enabled: !!doc && doc.status === "ready",
  });
  const sections = (outline.data?.nodes ?? []).filter((n) => n.kind !== "chunk");
  const chunks = (outline.data?.nodes ?? []).filter((n) => n.kind === "chunk");
  return (
    <Sheet open={!!doc} onOpenChange={(o) => !o && onClose()}>
      <SheetContent className="w-full overflow-y-auto sm:max-w-lg">
        {doc ? (
          <>
            <SheetHeader>
              <SheetTitle>{documentLabel(doc)}</SheetTitle>
              <SheetDescription className="break-all" dir="ltr">{doc.uri}</SheetDescription>
            </SheetHeader>
            <div className="space-y-6 px-4 pb-6">
              <dl className="grid grid-cols-2 gap-3 text-sm">
                {(
                  [
                    ["status", <StatusBadge key="s" tone={documentTone(doc.status)}>{t(`statuses.${doc.status}`)}</StatusBadge>],
                    ["version", doc.version],
                    ["size", formatBytes(doc.size, locale)],
                    ["type", doc.media_type ?? "—"],
                    ["sections", doc.section_count],
                    ["chunks", doc.chunk_count],
                    ["tokens", doc.token_count.toLocaleString(locale)],
                    ["scanner", doc.scanner ?? "—"],
                  ] as const
                ).map(([k, v]) => (
                  <div key={k} className="rounded-lg bg-muted/40 p-3">
                    <dt className="text-xs text-muted-foreground">{t(`meta.${k}`)}</dt>
                    <dd className="mt-1 font-medium break-words">{v}</dd>
                  </div>
                ))}
              </dl>
              {doc.error_code ? <FixHint doc={doc} /> : null}
              {doc.status === "ready" ? (
                <section aria-labelledby="outline-heading" className="space-y-2">
                  <h3 id="outline-heading" className="flex items-center gap-2 text-sm font-semibold">
                    <ListTree className="size-4" aria-hidden="true" />
                    {t("outline")}
                  </h3>
                  {outline.isLoading ? (
                    <Skeleton className="h-24" />
                  ) : (
                    <ul className="space-y-1 text-sm" data-testid="outline">
                      {sections.map((n) => {
                        const depth = n.path.split(".").length - 1;
                        const own = chunks.filter((c) => c.parent_id === n.id).length;
                        return (
                          <li key={n.id} className="flex items-baseline justify-between gap-3 rounded-md px-2 py-1 hover:bg-muted/50" style={{ paddingInlineStart: `${0.5 + depth * 1}rem` }}>
                            <span className="min-w-0 truncate">{n.kind === "document" ? <strong>{n.title}</strong> : n.title}</span>
                            <span className="shrink-0 text-xs text-muted-foreground tabular-nums">
                              {n.page_start ? `p.${n.page_start}${n.page_end && n.page_end !== n.page_start ? `–${n.page_end}` : ""} · ` : ""}
                              {t("chunkCount", { count: own })}
                            </span>
                          </li>
                        );
                      })}
                    </ul>
                  )}
                </section>
              ) : null}
            </div>
          </>
        ) : null}
      </SheetContent>
    </Sheet>
  );
}
