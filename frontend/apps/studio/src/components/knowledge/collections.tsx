"use client";

import { useMutation, useQueryClient } from "@tanstack/react-query";
import { BookOpenText, FileText, Lock, Plus, ShieldCheck, Users } from "lucide-react";
import Link from "next/link";
import { useRouter } from "next/navigation";
import { useTranslations } from "next-intl";
import { type FormEvent, useState } from "react";
import { toast } from "sonner";

import { EmptyState } from "@/components/empty-state";
import { PageHeader } from "@/components/page-header";
import { Button } from "@/components/ui/button";
import { Dialog, DialogContent, DialogDescription, DialogFooter, DialogHeader, DialogTitle } from "@/components/ui/dialog";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import { Select, SelectContent, SelectItem, SelectTrigger, SelectValue } from "@/components/ui/select";
import { Skeleton } from "@/components/ui/skeleton";
import { Textarea } from "@/components/ui/textarea";
import { IconTile } from "@/components/visual/icon-tile";
import { StatusBadge } from "@/components/visual/status-badge";
import { api, ApiError } from "@/lib/api";
import { useErrorToast } from "@/lib/hooks";
import { type Classification, CLASSIFICATIONS, type Collection } from "@/lib/knowledge";
import { useCollections } from "@/lib/knowledge-hooks";

import { ProfileSelect } from "./profile-select";

export const CLASSIFICATION_TONE = { public: "teal", internal: "sky", confidential: "amber", restricted: "rose" } as const;

export function CollectionsPage() {
  const t = useTranslations("knowledge");
  const collections = useCollections();
  const [open, setOpen] = useState(false);

  return (
    <div className="space-y-8">
      <PageHeader
        title={t("title")}
        description={t("subtitle")}
        icon={BookOpenText}
        tone="sky"
        actions={
          <Button onClick={() => setOpen(true)} data-testid="create-collection" className="shadow-sm">
            <Plus className="size-4" aria-hidden="true" />
            {t("newCollection")}
          </Button>
        }
      />
      <CreateCollectionDialog open={open} onOpenChange={setOpen} />
      {collections.isLoading ? (
        <div className="grid gap-4 sm:grid-cols-2 xl:grid-cols-3">
          {[0, 1, 2].map((i) => <Skeleton key={i} className="h-40" />)}
        </div>
      ) : !collections.data?.length ? (
        <EmptyState
          icon={BookOpenText}
          tone="sky"
          title={t("emptyTitle")}
          body={t("emptyBody")}
          action={
            <Button onClick={() => setOpen(true)}>
              <Plus className="size-4" aria-hidden="true" />
              {t("newCollection")}
            </Button>
          }
        />
      ) : (
        <ul className="nx-stagger grid gap-4 sm:grid-cols-2 xl:grid-cols-3" aria-label={t("collections")}>
          {collections.data.map((c) => (
            <li key={c.id}>
              <CollectionCard collection={c} />
            </li>
          ))}
        </ul>
      )}
    </div>
  );
}

function CollectionCard({ collection: c }: { collection: Collection }) {
  const t = useTranslations("knowledge");
  return (
    <Link
      href={`/knowledge/${c.id}`}
      data-testid={`collection-${c.name}`}
      className="nx-card nx-lift group flex h-full flex-col gap-4 p-5 outline-none focus-visible:ring-2 focus-visible:ring-ring"
    >
      <div className="flex items-start justify-between gap-3">
        <div className="flex min-w-0 items-center gap-3">
          <IconTile icon={BookOpenText} tone="sky" />
          <div className="min-w-0">
            <div className="truncate font-semibold group-hover:text-primary">{c.name}</div>
            <div className="truncate text-xs text-muted-foreground">{c.model_profile}</div>
          </div>
        </div>
        <StatusBadge tone={CLASSIFICATION_TONE[c.classification]}>{t(`classifications.${c.classification}`)}</StatusBadge>
      </div>
      {c.description ? <p className="line-clamp-2 text-sm text-muted-foreground">{c.description}</p> : null}
      <div className="mt-auto flex flex-wrap items-center gap-x-4 gap-y-1 text-xs text-muted-foreground">
        <span className="inline-flex items-center gap-1.5">
          <FileText className="size-3.5" aria-hidden="true" />
          {t("documentCount", { count: c.documents })}
        </span>
        <span className="inline-flex items-center gap-1.5">
          {c.acl_groups.length ? <Lock className="size-3.5" aria-hidden="true" /> : <Users className="size-3.5" aria-hidden="true" />}
          {c.acl_groups.length ? t("restrictedTo", { groups: c.acl_groups.join(", ") }) : t("everyone")}
        </span>
      </div>
    </Link>
  );
}

const NAME = /^[a-z0-9][a-z0-9-]{1,62}$/;

export function slugify(value: string): string {
  return value
    .toLowerCase()
    .normalize("NFKD")
    .replace(/\p{M}/gu, "") // drop accents: "Ü" -> "u"
    .replace(/[^a-z0-9]+/g, "-")
    .replace(/^-+|-+$/g, "")
    .slice(0, 63);
}

function CreateCollectionDialog({ open, onOpenChange }: { open: boolean; onOpenChange: (open: boolean) => void }) {
  const t = useTranslations("knowledge");
  const tc = useTranslations("common");
  const router = useRouter();
  const queryClient = useQueryClient();
  const onError = useErrorToast();
  const [name, setName] = useState("");
  const [description, setDescription] = useState("");
  const [classification, setClassification] = useState<Classification>("internal");
  const [modelProfile, setModelProfile] = useState("cloud-frontier");
  const [retrievalProfile, setRetrievalProfile] = useState("standard");
  const [groups, setGroups] = useState("");
  const [nameError, setNameError] = useState<string | null>(null);

  const create = useMutation({
    mutationFn: () =>
      api<Collection>("ingestion/v1/collections", {
        method: "POST",
        json: {
          name,
          description,
          classification,
          model_profile: modelProfile,
          retrieval_profile: retrievalProfile,
          acl_groups: groups.split(",").map((g) => g.trim()).filter(Boolean),
        },
      }),
    onSuccess: (c) => {
      toast.success(t("created", { name: c.name }));
      void queryClient.invalidateQueries({ queryKey: ["collections"] });
      onOpenChange(false);
      router.push(`/knowledge/${c.id}`);
    },
    onError: (err) => {
      if (err instanceof ApiError && err.status === 409) setNameError(t("nameTaken"));
      else onError(err);
    },
  });

  function submit(event: FormEvent) {
    event.preventDefault();
    if (!NAME.test(name)) return setNameError(t("nameRule"));
    setNameError(null);
    create.mutate();
  }

  return (
    <Dialog open={open} onOpenChange={onOpenChange}>
      <DialogContent className="sm:max-w-lg">
        <form onSubmit={submit} className="space-y-5" noValidate>
          <DialogHeader>
            <DialogTitle>{t("newCollection")}</DialogTitle>
            <DialogDescription>{t("newCollectionBody")}</DialogDescription>
          </DialogHeader>
          <div className="space-y-2">
            <Label htmlFor="collection-name">{tc("name")}</Label>
            <Input
              id="collection-name"
              value={name}
              onChange={(e) => setName(slugify(e.target.value))}
              placeholder="product-docs"
              aria-invalid={!!nameError}
              aria-describedby="collection-name-help"
              dir="ltr"
              autoFocus
            />
            <p id="collection-name-help" className={nameError ? "text-sm text-destructive" : "text-xs text-muted-foreground"}>
              {nameError ?? t("nameRule")}
            </p>
          </div>
          <div className="space-y-2">
            <Label htmlFor="collection-description">
              {tc("description")} <span className="text-muted-foreground">({tc("optional")})</span>
            </Label>
            <Textarea id="collection-description" value={description} onChange={(e) => setDescription(e.target.value)} rows={2} maxLength={500} />
          </div>
          <div className="grid gap-4 sm:grid-cols-2">
            <div className="space-y-2">
              <Label htmlFor="collection-classification">{t("classification")}</Label>
              <Select value={classification} onValueChange={(v) => setClassification(v as Classification)}>
                <SelectTrigger id="collection-classification" className="w-full">
                  <SelectValue />
                </SelectTrigger>
                <SelectContent>
                  {CLASSIFICATIONS.map((c) => (
                    <SelectItem key={c} value={c}>{t(`classifications.${c}`)}</SelectItem>
                  ))}
                </SelectContent>
              </Select>
            </div>
            <div className="space-y-2">
              <Label htmlFor="collection-model">{t("modelProfile")}</Label>
              <ProfileSelect kind="model_profile" id="collection-model" value={modelProfile} onChange={setModelProfile} />
            </div>
          </div>
          <div className="space-y-2">
            <Label htmlFor="collection-retrieval">{t("retrievalProfile")}</Label>
            <ProfileSelect kind="retrieval_profile" id="collection-retrieval" value={retrievalProfile} onChange={setRetrievalProfile} />
          </div>
          <div className="space-y-2">
            <Label htmlFor="collection-groups">
              <ShieldCheck className="size-4" aria-hidden="true" />
              {t("accessGroups")} <span className="text-muted-foreground">({tc("optional")})</span>
            </Label>
            <Input id="collection-groups" value={groups} onChange={(e) => setGroups(e.target.value)} placeholder="support, engineering" aria-describedby="collection-groups-help" />
            <p id="collection-groups-help" className="text-xs text-muted-foreground">{t("accessGroupsHelp")}</p>
          </div>
          <DialogFooter>
            <Button type="button" variant="outline" onClick={() => onOpenChange(false)}>{tc("cancel")}</Button>
            <Button type="submit" disabled={create.isPending || !name}>{t("createCollection")}</Button>
          </DialogFooter>
        </form>
      </DialogContent>
    </Dialog>
  );
}
