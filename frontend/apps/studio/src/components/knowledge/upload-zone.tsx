"use client";

import { useQueryClient } from "@tanstack/react-query";
import { CheckCircle2, CircleAlert, LoaderCircle, UploadCloud } from "lucide-react";
import { useLocale, useTranslations } from "next-intl";
import { type DragEvent, useId, useRef, useState } from "react";

import { api, ApiError } from "@/lib/api";
import { checkFile, formatBytes, type PluginManifest, uploadRules } from "@/lib/knowledge";
import { usePlugins } from "@/lib/knowledge-hooks";
import { cn } from "@/lib/utils";

interface Item {
  key: string;
  name: string;
  size: number;
  state: "queued" | "uploading" | "done" | "unchanged" | "error";
  message?: string;
}

/** Drag-and-drop or browse; files upload one at a time with per-file state. */
export function UploadZone({ collectionId, compact = false }: { collectionId: string; compact?: boolean }) {
  const t = useTranslations("knowledge.upload");
  const locale = useLocale();
  const queryClient = useQueryClient();
  const parsers = usePlugins("parser");
  const rules = uploadRules(parsers.data ?? []);
  const input = useRef<HTMLInputElement>(null);
  const helpId = useId();
  const [dragging, setDragging] = useState(false);
  const [items, setItems] = useState<Item[]>([]);

  const update = (key: string, patch: Partial<Item>) => setItems((all) => all.map((i) => (i.key === key ? { ...i, ...patch } : i)));

  async function upload(files: File[]) {
    // Files dropped before the parser list loaded must still be checked: wait for it.
    const manifests = await queryClient.ensureQueryData({
      queryKey: ["plugins", "parser"],
      queryFn: () => api<PluginManifest[]>("ingestion/v1/plugins?kind=parser"),
    });
    const checks = uploadRules(manifests);
    const queued = files.map((f, n) => ({ file: f, key: `${Date.now()}-${n}-${f.name}` }));
    setItems((all) => [...queued.map(({ file, key }) => ({ key, name: file.name, size: file.size, state: "queued" as const })), ...all].slice(0, 20));
    for (const { file, key } of queued) {
      const problem = checkFile(file, checks);
      if (problem) {
        update(key, { state: "error", message: t(`problems.${problem}`, { max: formatBytes(checks.maxBytes, locale) }) });
        continue;
      }
      update(key, { state: "uploading" });
      try {
        const result = await api<{ unchanged: boolean }>(
          `ingestion/v1/collections/${collectionId}/documents?filename=${encodeURIComponent(file.name)}`,
          { method: "POST", body: file, headers: { "content-type": file.type || "application/octet-stream" } },
        );
        update(key, { state: result.unchanged ? "unchanged" : "done" });
      } catch (err) {
        update(key, { state: "error", message: err instanceof ApiError ? err.message : t("failed") });
      }
      void queryClient.invalidateQueries({ queryKey: ["documents", collectionId] });
      void queryClient.invalidateQueries({ queryKey: ["runs", collectionId] });
    }
    void queryClient.invalidateQueries({ queryKey: ["collection", collectionId] });
  }

  function onDrop(event: DragEvent) {
    event.preventDefault();
    setDragging(false);
    void upload([...event.dataTransfer.files]);
  }

  return (
    <div className="space-y-3">
      <button
        type="button"
        onClick={() => input.current?.click()}
        onDragOver={(e) => {
          e.preventDefault();
          setDragging(true);
        }}
        onDragLeave={() => setDragging(false)}
        onDrop={onDrop}
        aria-describedby={helpId}
        data-testid="upload-zone"
        className={cn(
          "group flex w-full flex-col items-center justify-center gap-2 rounded-2xl border-2 border-dashed px-6 text-center transition-colors outline-none focus-visible:ring-2 focus-visible:ring-ring",
          compact ? "py-6" : "py-10",
          dragging ? "border-primary bg-primary/5" : "border-border hover:border-primary/50 hover:bg-muted/40",
        )}
      >
        <UploadCloud className={cn("size-8 text-muted-foreground transition-transform group-hover:-translate-y-0.5", dragging && "text-primary")} aria-hidden="true" />
        <span className="font-medium">{t("title")}</span>
        <span id={helpId} className="text-xs text-muted-foreground">
          {t("help", { types: rules.extensions.map((e) => e.replace(".", "").toUpperCase()).slice(0, 8).join(", "), max: formatBytes(rules.maxBytes, locale) })}
        </span>
      </button>
      <input
        ref={input}
        type="file"
        multiple
        accept={rules.accept}
        className="sr-only"
        tabIndex={-1}
        aria-label={t("title")}
        data-testid="upload-input"
        onChange={(e) => {
          void upload([...(e.target.files ?? [])]);
          e.target.value = "";
        }}
      />
      {items.length ? (
        <ul className="space-y-1.5" aria-live="polite" aria-label={t("queue")}>
          {items.map((i) => (
            <li key={i.key} className="flex items-center gap-3 rounded-lg bg-muted/40 px-3 py-2 text-sm" data-testid={`upload-${i.name}`}>
              {i.state === "done" || i.state === "unchanged" ? (
                <CheckCircle2 className="size-4 shrink-0 text-teal-600 dark:text-teal-300" aria-hidden="true" />
              ) : i.state === "error" ? (
                <CircleAlert className="size-4 shrink-0 text-destructive" aria-hidden="true" />
              ) : (
                <LoaderCircle className="size-4 shrink-0 animate-spin text-muted-foreground motion-reduce:animate-none" aria-hidden="true" />
              )}
              <span className="min-w-0 flex-1 truncate">{i.name}</span>
              <span className="shrink-0 text-xs text-muted-foreground">
                {i.state === "error" ? i.message : t(`states.${i.state}`)}
              </span>
            </li>
          ))}
        </ul>
      ) : null}
    </div>
  );
}
