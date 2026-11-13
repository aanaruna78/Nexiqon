"use client";

import { useMutation, useQueries, useQueryClient } from "@tanstack/react-query";
import { Copy, FileUp, Package, Plus } from "lucide-react";
import Link from "next/link";
import { useRouter } from "next/navigation";
import { useTranslations } from "next-intl";
import { type ChangeEvent, type FormEvent, useState } from "react";
import { toast } from "sonner";

import { EmptyState } from "@/components/empty-state";
import { PageHeader } from "@/components/page-header";
import { Button } from "@/components/ui/button";
import { Dialog, DialogContent, DialogDescription, DialogFooter, DialogHeader, DialogTitle, DialogTrigger } from "@/components/ui/dialog";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import { Select, SelectContent, SelectItem, SelectTrigger, SelectValue } from "@/components/ui/select";
import { Skeleton } from "@/components/ui/skeleton";
import { IconTile } from "@/components/visual/icon-tile";
import { StatusBadge } from "@/components/visual/status-badge";
import { api } from "@/lib/api";
import { useErrorToast } from "@/lib/hooks";
import { type ConfigObject, NAME_PATTERN, type PackSpec, releaseState, slugify, type VersionDetail } from "@/lib/studio";
import { useObjects } from "@/lib/studio-hooks";

import { blankPack } from "./templates";

/** Domain Packs (ST-10): what each pack defines, what is live; create, duplicate or import one. */
export function PackList() {
  const t = useTranslations("packs");
  const packs = useObjects("domain_pack");
  const specs = useQueries({
    queries: (packs.data ?? []).map((p) => {
      const v = p.versions.at(-1)?.version;
      return {
        queryKey: ["version", "domain_pack", p.name, v],
        queryFn: () => api<VersionDetail>(`config/v1/objects/domain_pack/${p.name}/versions/${v}`),
        staleTime: Infinity,
      };
    }),
  });
  if (packs.isLoading) return <Skeleton className="h-96" />;
  const list = packs.data ?? [];
  const actions = (
    <div className="flex flex-wrap gap-2">
      <ImportPack />
      <NewPack packs={list} />
    </div>
  );
  return (
    <div className="space-y-8">
      <PageHeader title={t("title")} description={t("subtitle")} icon={Package} tone="teal" actions={list.length ? actions : null} />
      {!list.length ? (
        <EmptyState icon={Package} title={t("empty")} body={t("emptyBody")} action={actions} />
      ) : (
        <ul className="nx-stagger grid gap-4 sm:grid-cols-2 xl:grid-cols-3" data-testid="pack-list">
          {list.map((p, i) => {
            const spec = specs[i]?.data?.spec as PackSpec | undefined;
            const state = releaseState(p);
            return (
              <li key={p.name}>
                <Link href={`/domain-packs/${p.name}`} className="nx-card nx-lift flex h-full flex-col gap-3 p-4 focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring">
                  <div className="flex items-start gap-3">
                    <IconTile icon={Package} tone="teal" />
                    <div className="min-w-0 flex-1">
                      <h2 className="truncate font-semibold">{spec?.metadata.title ?? p.name}</h2>
                      <p className="truncate text-xs text-muted-foreground">{p.name} · {spec?.metadata.pack_version}</p>
                    </div>
                    {state.live ? <StatusBadge tone="teal" live>{t("live", { version: state.live })}</StatusBadge> : <StatusBadge tone="amber">{t("notLive")}</StatusBadge>}
                  </div>
                  {spec?.metadata.description ? <p className="line-clamp-2 text-sm text-muted-foreground">{spec.metadata.description}</p> : null}
                  <p className="mt-auto text-xs text-muted-foreground">
                    {t("counts", { intents: spec?.intents.length ?? 0, tools: spec?.tools?.length ?? 0, terms: Object.keys(spec?.vocabulary ?? {}).length })}
                  </p>
                </Link>
              </li>
            );
          })}
        </ul>
      )}
    </div>
  );
}

function NewPack({ packs }: { packs: ConfigObject[] }) {
  const t = useTranslations("packs");
  const router = useRouter();
  const client = useQueryClient();
  const onError = useErrorToast();
  const [open, setOpen] = useState(false);
  const [title, setTitle] = useState("");
  const [from, setFrom] = useState("__blank");
  const name = slugify(title);

  const create = useMutation({
    mutationFn: async () => {
      let spec: Record<string, unknown> = blankPack(title.trim());
      if (from !== "__blank") {
        const source = packs.find((p) => p.name === from)!;
        const v = await api<VersionDetail>(`config/v1/objects/domain_pack/${from}/versions/${source.versions.at(-1)!.version}`);
        const copy = structuredClone(v.spec) as PackSpec;
        copy.metadata = { ...copy.metadata, title: title.trim(), pack_version: "0.1.0" };
        spec = copy;
      }
      await api("config/v1/objects", { method: "POST", json: { kind: "domain_pack", name, description: title.trim(), spec } });
    },
    onSuccess: async () => {
      toast.success(t("created", { title }));
      await client.invalidateQueries({ queryKey: ["objects", "domain_pack"] });
      setOpen(false);
      router.push(`/domain-packs/${name}`);
    },
    onError,
  });

  function submit(e: FormEvent) {
    e.preventDefault();
    if (title.trim().length >= 2 && NAME_PATTERN.test(name)) create.mutate();
  }

  return (
    <Dialog open={open} onOpenChange={setOpen}>
      <DialogTrigger asChild>
        <Button data-testid="new-pack"><Plus className="size-4" aria-hidden="true" />{t("new")}</Button>
      </DialogTrigger>
      <DialogContent>
        <form onSubmit={submit} className="space-y-5">
          <DialogHeader>
            <DialogTitle>{t("newTitle")}</DialogTitle>
            <DialogDescription>{t("newBody")}</DialogDescription>
          </DialogHeader>
          <div className="space-y-2">
            <Label htmlFor="p-title">{t("packTitle")}</Label>
            <Input id="p-title" value={title} onChange={(e) => setTitle(e.target.value)} placeholder={t("titlePlaceholder")} autoFocus required minLength={2} />
            <p className="text-xs text-muted-foreground" dir="ltr">{name || "—"}</p>
          </div>
          <div className="space-y-2">
            <Label htmlFor="p-from">{t("startFrom")}</Label>
            <Select value={from} onValueChange={setFrom}>
              <SelectTrigger id="p-from" className="w-full"><SelectValue /></SelectTrigger>
              <SelectContent>
                <SelectItem value="__blank">{t("blank")}</SelectItem>
                {packs.map((p) => (
                  <SelectItem key={p.name} value={p.name}>
                    <Copy className="size-3.5" aria-hidden="true" /> {t("copyOf", { name: p.description || p.name })}
                  </SelectItem>
                ))}
              </SelectContent>
            </Select>
          </div>
          <DialogFooter>
            <Button type="submit" disabled={create.isPending || title.trim().length < 2 || !NAME_PATTERN.test(name)} data-testid="create-pack">{t("create")}</Button>
          </DialogFooter>
        </form>
      </DialogContent>
    </Dialog>
  );
}

function ImportPack() {
  const t = useTranslations("packs");
  const router = useRouter();
  const client = useQueryClient();
  const onError = useErrorToast();
  const importYaml = useMutation({
    mutationFn: async (text: string) => {
      const v = await api<VersionDetail>("config/v1/packs/import", { method: "POST", body: text, headers: { "content-type": "application/yaml" } });
      const name = /^\s*name:\s*([a-z0-9-]+)/m.exec(text)?.[1];
      return { v, name };
    },
    onSuccess: async ({ v, name }) => {
      toast.success(t("imported", { version: v.version }));
      await client.invalidateQueries({ queryKey: ["objects", "domain_pack"] });
      if (name) router.push(`/domain-packs/${name}`);
    },
    onError,
  });

  async function pick(e: ChangeEvent<HTMLInputElement>) {
    const file = e.target.files?.[0];
    e.target.value = "";
    if (file) importYaml.mutate(await file.text());
  }

  return (
    <Button asChild variant="outline">
      <label className="cursor-pointer" data-testid="import-pack">
        <FileUp className="size-4" aria-hidden="true" />
        {importYaml.isPending ? t("importing") : t("import")}
        <input type="file" accept=".yaml,.yml,application/yaml" className="sr-only" onChange={pick} />
      </label>
    </Button>
  );
}
