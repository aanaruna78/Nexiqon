"use client";

import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { Bot, BookOpenText, Check, Code2, Globe, Package, Rocket, Sparkles } from "lucide-react";
import { useRouter, useSearchParams } from "next/navigation";
import { useTranslations } from "next-intl";
import { type FormEvent, type ReactNode, useState } from "react";
import { toast } from "sonner";

import { TestChat } from "@/components/assistants/test-chat";
import { WidgetKeys } from "@/components/assistants/widget-settings";
import { ProfileSelect } from "@/components/knowledge/profile-select";
import { UploadZone } from "@/components/knowledge/upload-zone";
import { PageHeader } from "@/components/page-header";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import { Skeleton } from "@/components/ui/skeleton";
import { IconTile } from "@/components/visual/icon-tile";
import { StatusBadge } from "@/components/visual/status-badge";
import { api } from "@/lib/api";
import { useErrorToast } from "@/lib/hooks";
import type { Collection } from "@/lib/knowledge";
import { useCollections, useDocuments } from "@/lib/knowledge-hooks";
import { type AgentSpec, slugify } from "@/lib/studio";
import { useObject, useObjects } from "@/lib/studio-hooks";
import { cn } from "@/lib/utils";

interface GalleryPack {
  name: string;
  title: string;
  description: string;
  version: string;
  intents: number;
  tools: string[];
  starter_questions: string[];
  installed_version: number | null;
}

type StepKey = "pack" | "knowledge" | "assistant" | "embed";
const ORDER: StepKey[] = ["pack", "knowledge", "assistant", "embed"];

/** Steps done, from what exists: a live pack, a collection with ready documents, a live assistant. */
export function guideProgress(s: { pack?: string | null; ready: number; live: number | null }): Record<StepKey, boolean> {
  return { pack: !!s.pack, knowledge: !!s.pack && s.ready > 0, assistant: s.ready > 0 && s.live !== null, embed: false };
}

/** Setup guide (ST-13): from nothing to a cited answer and an embeddable widget in minutes. */
export function SetupGuide() {
  const t = useTranslations("guide");
  const params = useSearchParams();
  const router = useRouter();
  const pack = params.get("pack");
  const collectionId = params.get("collection");
  const assistant = params.get("assistant");
  const go = (patch: Record<string, string>) => {
    const next = new URLSearchParams(params.toString());
    for (const [k, v] of Object.entries(patch)) next.set(k, v);
    router.replace(`/get-started?${next.toString()}`);
  };

  const collections = useCollections();
  const documents = useDocuments(collectionId ?? "");
  const ready = collectionId ? (documents.data ?? []).filter((d) => d.status === "ready").length : 0;
  const agent = useObject("agent", assistant ?? "", !!assistant);
  const live = agent.data?.deployments.dev ?? null;
  const done = guideProgress({ pack, ready, live });
  const current = ORDER.find((k) => !done[k]) ?? "embed";

  return (
    <div className="space-y-8">
      <PageHeader title={t("title")} description={t("subtitle")} icon={Rocket} tone="teal" />
      <ol className="space-y-4" data-testid="setup-guide">
        <Step n={1} k="pack" icon={Package} current={current} done={done.pack} summary={pack ?? undefined}>
          <PickPack chosen={pack} onChosen={(name) => go({ pack: name })} />
        </Step>
        <Step n={2} k="knowledge" icon={BookOpenText} current={current} done={done.knowledge} summary={done.knowledge ? t("readyDocs", { count: ready }) : undefined}>
          <AddKnowledge collections={collections.data ?? []} chosen={collectionId} ready={ready} onChosen={(id) => go({ collection: id })} />
        </Step>
        <Step n={3} k="assistant" icon={Bot} current={current} done={done.assistant} summary={assistant ?? undefined}>
          {pack && collectionId ? (
            <CreateAndTest pack={pack} collection={(collections.data ?? []).find((c) => c.id === collectionId)} assistant={assistant} live={live} onCreated={(name) => go({ assistant: name })} />
          ) : null}
        </Step>
        <Step n={4} k="embed" icon={Code2} current={current} done={false}>
          {assistant && live !== null ? <WidgetKeys agent={assistant} /> : null}
        </Step>
      </ol>
    </div>
  );
}

function Step({ n, k, icon: Icon, current, done, summary, children }: { n: number; k: StepKey; icon: typeof Package; current: StepKey; done: boolean; summary?: string; children: ReactNode }) {
  const t = useTranslations("guide");
  const open = k === current || (k === "assistant" && current === "embed") || (k === "embed" && current === "embed");
  const reachable = ORDER.indexOf(k) <= ORDER.indexOf(current);
  return (
    // Later steps keep full contrast (WCAG): a dashed border and a note say they come next.
    <li className={cn("nx-card p-4", !reachable && "border-dashed bg-transparent shadow-none")} data-testid={`guide-step-${k}`} aria-current={k === current ? "step" : undefined}>
      <div className="flex items-center gap-3">
        <span className={cn("inline-flex size-8 shrink-0 items-center justify-center rounded-full border text-sm font-semibold", done && "border-primary bg-primary text-primary-foreground")}>
          {done ? <Check className="size-4" aria-hidden="true" /> : n}
        </span>
        <IconTile icon={Icon} tone="teal" size="sm" />
        <div className="min-w-0 flex-1">
          <h2 className="font-semibold">{t(`steps.${k}.title`)}</h2>
          <p className="text-sm text-muted-foreground">{done && summary ? summary : t(`steps.${k}.body`)}</p>
        </div>
        {done ? <StatusBadge tone="teal">{t("done")}</StatusBadge> : !reachable ? <StatusBadge tone="slate">{t("next", { step: n - 1 })}</StatusBadge> : null}
      </div>
      {open && reachable ? <div className="mt-4 border-t pt-4">{children}</div> : null}
    </li>
  );
}

function PickPack({ chosen, onChosen }: { chosen: string | null; onChosen: (name: string) => void }) {
  const t = useTranslations("guide");
  const client = useQueryClient();
  const onError = useErrorToast();
  const gallery = useQuery({ queryKey: ["pack-gallery"], queryFn: () => api<GalleryPack[]>("config/v1/packs/gallery") });
  const install = useMutation({
    mutationFn: (name: string) => api(`config/v1/packs/gallery/${name}/install`, { method: "POST" }),
    onSuccess: async (_, name) => {
      toast.success(t("packReady"));
      await client.invalidateQueries({ queryKey: ["objects", "domain_pack"] });
      onChosen(name);
    },
    onError,
  });
  if (gallery.isLoading) return <Skeleton className="h-32" />;
  return (
    <ul className="grid gap-3 md:grid-cols-2">
      {(gallery.data ?? []).map((p) => (
        <li key={p.name} className={cn("rounded-xl border p-4", chosen === p.name && "border-primary")}>
          <h3 className="font-semibold">{p.title}</h3>
          <p className="mt-1 line-clamp-3 text-sm text-muted-foreground">{p.description}</p>
          <p className="mt-2 text-xs text-muted-foreground">{t("packFacts", { intents: p.intents, tools: p.tools.length })}</p>
          <Button className="mt-3" size="sm" onClick={() => install.mutate(p.name)} disabled={install.isPending} data-testid={`use-pack-${p.name}`}>
            <Sparkles className="size-4" aria-hidden="true" />
            {p.installed_version ? t("usePack") : t("installPack")}
          </Button>
        </li>
      ))}
    </ul>
  );
}

function AddKnowledge({ collections, chosen, ready, onChosen }: { collections: Collection[]; chosen: string | null; ready: number; onChosen: (id: string) => void }) {
  const t = useTranslations("guide");
  const client = useQueryClient();
  const onError = useErrorToast();
  const [name, setName] = useState("product-docs");
  const [model, setModel] = useState("cloud-frontier");
  const [retrieval, setRetrieval] = useState("standard");
  const [site, setSite] = useState("");
  const create = useMutation({
    mutationFn: () => api<Collection>("ingestion/v1/collections", { method: "POST", json: { name, model_profile: model, retrieval_profile: retrieval } }),
    onSuccess: async (c) => {
      await client.invalidateQueries({ queryKey: ["collections"] });
      onChosen(c.id);
    },
    onError,
  });
  const crawl = useMutation({
    mutationFn: async () => {
      const src = await api<{ id: string }>(`ingestion/v1/collections/${chosen}/sources`, {
        method: "POST",
        json: { name: "website", connector: "web", config: { start_urls: [site] } },
      });
      await api(`ingestion/v1/sources/${src.id}/sync`, { method: "POST" });
    },
    onSuccess: () => toast.success(t("crawlStarted")),
    onError,
  });

  if (!chosen) {
    return (
      <div className="space-y-4">
        {collections.length ? (
          <div className="space-y-2">
            <p className="text-sm font-medium">{t("useExisting")}</p>
            <div className="flex flex-wrap gap-2">
              {collections.map((c) => <Button key={c.id} variant="outline" size="sm" onClick={() => onChosen(c.id)}>{c.name}</Button>)}
            </div>
          </div>
        ) : null}
        <form
          className="grid gap-4 sm:grid-cols-3"
          onSubmit={(e: FormEvent) => {
            e.preventDefault();
            create.mutate();
          }}
        >
          <div className="space-y-2">
            <Label htmlFor="g-coll">{t("collectionName")}</Label>
            <Input id="g-coll" value={name} onChange={(e) => setName(slugify(e.target.value) || e.target.value)} dir="ltr" />
          </div>
          <div className="space-y-2">
            <Label htmlFor="g-model">{t("modelProfile")}</Label>
            <ProfileSelect kind="model_profile" id="g-model" value={model} onChange={setModel} />
          </div>
          <div className="space-y-2">
            <Label htmlFor="g-retrieval">{t("retrievalProfile")}</Label>
            <ProfileSelect kind="retrieval_profile" id="g-retrieval" value={retrieval} onChange={setRetrieval} />
          </div>
          <div className="sm:col-span-3">
            <Button type="submit" disabled={create.isPending || name.length < 2} data-testid="guide-create-collection">{t("createCollection")}</Button>
          </div>
        </form>
      </div>
    );
  }
  return (
    <div className="grid gap-6 lg:grid-cols-2">
      <div className="space-y-2">
        <p className="text-sm font-medium">{t("uploadFiles")}</p>
        <UploadZone collectionId={chosen} compact />
      </div>
      <form
        className="space-y-2"
        onSubmit={(e: FormEvent) => {
          e.preventDefault();
          crawl.mutate();
        }}
      >
        <Label htmlFor="g-site" className="flex items-center gap-2"><Globe className="size-4" aria-hidden="true" />{t("orWebsite")}</Label>
        <Input id="g-site" type="url" value={site} onChange={(e) => setSite(e.target.value)} placeholder="https://docs.example.com/" dir="ltr" />
        <Button type="submit" variant="outline" disabled={!/^https?:\/\//.test(site) || crawl.isPending}>{t("crawl")}</Button>
      </form>
      <p className="text-sm text-muted-foreground lg:col-span-2" aria-live="polite">{ready ? t("readyDocs", { count: ready }) : t("waitingDocs")}</p>
    </div>
  );
}

function CreateAndTest({ pack, collection, assistant, live, onCreated }: { pack: string; collection?: Collection; assistant: string | null; live: number | null; onCreated: (name: string) => void }) {
  const t = useTranslations("guide");
  const client = useQueryClient();
  const onError = useErrorToast();
  const packs = useObjects("domain_pack");
  const agent = useObject("agent", assistant ?? "", !!assistant);
  const [display, setDisplay] = useState("");
  const title = packs.data?.find((p) => p.name === pack)?.description || "Assistant";
  const name = slugify(display || title);
  const create = useMutation({
    mutationFn: async () => {
      const spec: AgentSpec = {
        pack: { name: pack },
        display_name: (display || title).trim(),
        model_profile: collection?.model_profile,
        retrieval_profile: collection?.retrieval_profile,
        knowledge: { collections: collection ? [collection.name] : [] },
      };
      await api("config/v1/objects", { method: "POST", json: { kind: "agent", name, spec } });
      await api(`config/v1/objects/agent/${name}/versions/1/publish`, { method: "POST" });
      await api(`config/v1/objects/agent/${name}/deployments/dev`, { method: "PUT", json: { version: 1, reason: "setup guide" } });
    },
    onSuccess: async () => {
      await client.invalidateQueries({ queryKey: ["object", "agent", name] });
      onCreated(name);
    },
    onError,
  });
  if (!assistant || live === null) {
    return (
      <form
        className="flex flex-wrap items-end gap-3"
        onSubmit={(e: FormEvent) => {
          e.preventDefault();
          create.mutate();
        }}
      >
        <div className="space-y-2">
          <Label htmlFor="g-name">{t("assistantName")}</Label>
          <Input id="g-name" value={display} placeholder={title} onChange={(e) => setDisplay(e.target.value)} className="w-72" />
        </div>
        <Button type="submit" disabled={create.isPending || name.length < 2} data-testid="guide-create-assistant">{t("createAssistant")}</Button>
      </form>
    );
  }
  return <TestChat agent={assistant} liveVersion={live} versions={agent.data?.versions ?? []} />;
}
