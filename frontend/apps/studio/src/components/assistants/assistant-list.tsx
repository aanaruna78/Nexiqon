"use client";

import { useMutation, useQueries, useQueryClient } from "@tanstack/react-query";
import { Bot, Package, Plus } from "lucide-react";
import Link from "next/link";
import { useRouter } from "next/navigation";
import { useTranslations } from "next-intl";
import { type FormEvent, useState } from "react";
import { toast } from "sonner";

import { EmptyState } from "@/components/empty-state";
import { ProfileSelect } from "@/components/knowledge/profile-select";
import { PageHeader } from "@/components/page-header";
import { Button } from "@/components/ui/button";
import { Checkbox } from "@/components/ui/checkbox";
import { Dialog, DialogContent, DialogDescription, DialogFooter, DialogHeader, DialogTitle, DialogTrigger } from "@/components/ui/dialog";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import { Select, SelectContent, SelectItem, SelectTrigger, SelectValue } from "@/components/ui/select";
import { Skeleton } from "@/components/ui/skeleton";
import { IconTile } from "@/components/visual/icon-tile";
import { StatusBadge } from "@/components/visual/status-badge";
import { api } from "@/lib/api";
import { useErrorToast } from "@/lib/hooks";
import { useCollections } from "@/lib/knowledge-hooks";
import { type AgentSpec, type ConfigObject, NAME_PATTERN, releaseState, slugify, type VersionDetail } from "@/lib/studio";
import { useObjects } from "@/lib/studio-hooks";

/** Assistants (ST-06): every assistant with what is live; create one from a Domain Pack. */
export function AssistantList() {
  const t = useTranslations("assistants");
  const agents = useObjects("agent");
  const packs = useObjects("domain_pack");
  const specs = useQueries({
    queries: (agents.data ?? []).map((a) => {
      const v = a.deployments.dev ?? a.versions.at(-1)?.version;
      return {
        queryKey: ["version", "agent", a.name, v],
        queryFn: () => api<VersionDetail>(`config/v1/objects/agent/${a.name}/versions/${v}`),
        staleTime: Infinity,
      };
    }),
  });
  const deployedPacks = (packs.data ?? []).filter((p) => p.deployments.dev);

  if (agents.isLoading || packs.isLoading) return <Skeleton className="h-96" />;
  const list = agents.data ?? [];
  return (
    <div className="space-y-8">
      <PageHeader
        title={t("title")}
        description={t("subtitle")}
        icon={Bot}
        tone="violet"
        actions={deployedPacks.length && list.length ? <CreateAssistant packs={deployedPacks} /> : null}
      />
      {!deployedPacks.length && !list.length ? (
        <EmptyState
          icon={Package}
          tone="violet"
          title={t("needPack")}
          body={t("needPackBody")}
          action={<Button asChild><Link href="/domain-packs">{t("goToPacks")}</Link></Button>}
        />
      ) : !list.length ? (
        <EmptyState icon={Bot} tone="violet" title={t("empty")} body={t("emptyBody")} action={<CreateAssistant packs={deployedPacks} />} />
      ) : (
        <ul className="nx-stagger grid gap-4 sm:grid-cols-2 xl:grid-cols-3" data-testid="assistant-list">
          {list.map((a, i) => (
            <li key={a.name}>
              <AssistantCard object={a} spec={specs[i]?.data?.spec as AgentSpec | undefined} />
            </li>
          ))}
        </ul>
      )}
    </div>
  );
}

function AssistantCard({ object, spec }: { object: ConfigObject; spec?: AgentSpec }) {
  const t = useTranslations("assistants");
  const state = releaseState(object);
  return (
    <Link href={`/assistants/${object.name}`} className="nx-card nx-lift flex h-full flex-col gap-3 p-4 focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring">
      <div className="flex items-start gap-3">
        <IconTile icon={Bot} tone="violet" />
        <div className="min-w-0 flex-1">
          <h2 className="truncate font-semibold">{spec?.display_name ?? object.name}</h2>
          <p className="truncate text-xs text-muted-foreground">{object.name}</p>
        </div>
        {state.live ? <StatusBadge tone="teal" live>{t("liveVersion", { version: state.live })}</StatusBadge> : <StatusBadge tone="amber">{t("notLive")}</StatusBadge>}
      </div>
      {spec?.description ? <p className="line-clamp-2 text-sm text-muted-foreground">{spec.description}</p> : null}
      <dl className="mt-auto flex flex-wrap gap-x-4 gap-y-1 text-xs text-muted-foreground">
        <div><dt className="inline">{t("pack")}: </dt><dd className="inline text-foreground">{spec?.pack.name ?? "—"}</dd></div>
        <div><dt className="inline">{t("knowledge")}: </dt><dd className="inline text-foreground">{spec?.knowledge?.collections?.length ?? 0}</dd></div>
        <div><dt className="inline">{t("model")}: </dt><dd className="inline text-foreground">{spec?.model_profile ?? t("default")}</dd></div>
        {state.draft ? <div><dd className="inline text-amber-700 dark:text-amber-300">{t("draftWaiting", { version: state.draft.version })}</dd></div> : null}
      </dl>
    </Link>
  );
}

function CreateAssistant({ packs }: { packs: ConfigObject[] }) {
  const t = useTranslations("assistants");
  const router = useRouter();
  const client = useQueryClient();
  const onError = useErrorToast();
  const collections = useCollections();
  const [open, setOpen] = useState(false);
  const [display, setDisplay] = useState("");
  const [name, setName] = useState("");
  const [touched, setTouched] = useState(false);
  const [pack, setPack] = useState(packs[0]?.name ?? "");
  const [chosen, setChosen] = useState<string[]>([]);
  const [model, setModel] = useState("cloud-frontier");
  const [retrieval, setRetrieval] = useState("standard");
  const slug = touched ? name : slugify(display);

  const create = useMutation({
    mutationFn: async () => {
      const spec: AgentSpec = {
        pack: { name: pack },
        display_name: display.trim(),
        model_profile: model,
        retrieval_profile: retrieval,
        knowledge: { collections: chosen },
      };
      await api("config/v1/objects", { method: "POST", json: { kind: "agent", name: slug, spec } });
      await api(`config/v1/objects/agent/${slug}/versions/1/publish`, { method: "POST" });
      await api(`config/v1/objects/agent/${slug}/deployments/dev`, { method: "PUT", json: { version: 1, reason: "created in Studio" } });
    },
    onSuccess: async () => {
      toast.success(t("created", { name: display }));
      await client.invalidateQueries({ queryKey: ["objects", "agent"] });
      setOpen(false);
      router.push(`/assistants/${slug}?tab=test`);
    },
    onError,
  });

  function submit(e: FormEvent) {
    e.preventDefault();
    if (display.trim().length >= 2 && NAME_PATTERN.test(slug) && pack) create.mutate();
  }

  return (
    <Dialog open={open} onOpenChange={setOpen}>
      <DialogTrigger asChild>
        <Button data-testid="new-assistant">
          <Plus className="size-4" aria-hidden="true" />
          {t("new")}
        </Button>
      </DialogTrigger>
      <DialogContent className="sm:max-w-lg">
        <form onSubmit={submit} className="space-y-5">
          <DialogHeader>
            <DialogTitle>{t("newTitle")}</DialogTitle>
            <DialogDescription>{t("newBody")}</DialogDescription>
          </DialogHeader>
          <div className="space-y-2">
            <Label htmlFor="as-display">{t("displayName")}</Label>
            <Input id="as-display" value={display} onChange={(e) => setDisplay(e.target.value)} placeholder={t("displayNamePlaceholder")} autoFocus required minLength={2} maxLength={80} />
          </div>
          <div className="space-y-2">
            <Label htmlFor="as-name">{t("id")}</Label>
            <Input
              id="as-name"
              value={slug}
              onChange={(e) => {
                setTouched(true);
                setName(e.target.value);
              }}
              aria-invalid={!!slug && !NAME_PATTERN.test(slug)}
              aria-describedby="as-name-help"
              dir="ltr"
            />
            <p id="as-name-help" className="text-xs text-muted-foreground">{t("idHelp")}</p>
          </div>
          <div className="space-y-2">
            <Label htmlFor="as-pack">{t("pack")}</Label>
            <Select value={pack} onValueChange={setPack}>
              <SelectTrigger id="as-pack" className="w-full"><SelectValue /></SelectTrigger>
              <SelectContent>
                {packs.map((p) => (
                  <SelectItem key={p.name} value={p.name}>{p.description || p.name}</SelectItem>
                ))}
              </SelectContent>
            </Select>
          </div>
          <fieldset className="space-y-2">
            <legend className="text-sm font-medium">{t("knowledge")}</legend>
            {collections.data?.length ? (
              collections.data.map((c) => (
                <div key={c.id} className="flex items-center gap-2">
                  <Checkbox id={`as-c-${c.id}`} checked={chosen.includes(c.name)} onCheckedChange={(on) => setChosen(on ? [...chosen, c.name] : chosen.filter((x) => x !== c.name))} />
                  <Label htmlFor={`as-c-${c.id}`} className="font-normal">{c.name}</Label>
                </div>
              ))
            ) : (
              <p className="text-sm text-muted-foreground">{t("noCollections")}</p>
            )}
          </fieldset>
          <div className="grid gap-4 sm:grid-cols-2">
            <div className="space-y-2">
              <Label htmlFor="as-model">{t("modelProfile")}</Label>
              <ProfileSelect kind="model_profile" id="as-model" value={model} onChange={setModel} />
            </div>
            <div className="space-y-2">
              <Label htmlFor="as-retrieval">{t("retrievalProfile")}</Label>
              <ProfileSelect kind="retrieval_profile" id="as-retrieval" value={retrieval} onChange={setRetrieval} />
            </div>
          </div>
          <DialogFooter>
            <Button type="submit" disabled={create.isPending || display.trim().length < 2 || !NAME_PATTERN.test(slug)} data-testid="create-assistant">
              {create.isPending ? t("creating") : t("create")}
            </Button>
          </DialogFooter>
        </form>
      </DialogContent>
    </Dialog>
  );
}
