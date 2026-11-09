"use client";

import { useMutation, useQueryClient } from "@tanstack/react-query";
import { BookOpenText, FlaskConical, Lock, RefreshCcw, Settings2, Trash2, Users } from "lucide-react";
import Link from "next/link";
import { useRouter } from "next/navigation";
import { useTranslations } from "next-intl";
import { type FormEvent, useState } from "react";
import { toast } from "sonner";

import { PageHeader } from "@/components/page-header";
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
import { Alert, AlertDescription, AlertTitle } from "@/components/ui/alert";
import { Button } from "@/components/ui/button";
import { Dialog, DialogContent, DialogDescription, DialogFooter, DialogHeader, DialogTitle } from "@/components/ui/dialog";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import { Select, SelectContent, SelectItem, SelectTrigger, SelectValue } from "@/components/ui/select";
import { Skeleton } from "@/components/ui/skeleton";
import { Tabs, TabsContent, TabsList, TabsTrigger } from "@/components/ui/tabs";
import { Textarea } from "@/components/ui/textarea";
import { Hint } from "@/components/visual/hint";
import { StatusBadge } from "@/components/visual/status-badge";
import { api, ApiError } from "@/lib/api";
import { useErrorToast } from "@/lib/hooks";
import { type Classification, CLASSIFICATIONS, type Collection } from "@/lib/knowledge";
import { useCollection, useDocuments, useRuns, useSources } from "@/lib/knowledge-hooks";

import { CLASSIFICATION_TONE } from "./collections";
import { DocumentsTable } from "./documents";
import { ProfileSelect } from "./profile-select";
import { ActiveRuns, RunHistory } from "./runs";
import { SourcesPanel } from "./sources";
import { UploadZone } from "./upload-zone";

export function CollectionDetail({ id }: { id: string }) {
  const t = useTranslations("knowledge");
  const tc = useTranslations("common");
  const collection = useCollection(id);
  const documents = useDocuments(id);
  const runs = useRuns(id);
  const sources = useSources(id);
  const [settingsOpen, setSettingsOpen] = useState(false);
  const [deleting, setDeleting] = useState(false);
  const queryClient = useQueryClient();
  const onError = useErrorToast();
  const router = useRouter();

  const reindex = useMutation({
    mutationFn: () => api(`ingestion/v1/collections/${id}/reindex`, { method: "POST" }),
    onSuccess: () => {
      toast.success(t("reindexStarted"));
      void queryClient.invalidateQueries({ queryKey: ["runs", id] });
      void queryClient.invalidateQueries({ queryKey: ["documents", id] });
    },
    onError,
  });
  const remove = useMutation({
    mutationFn: () => api(`ingestion/v1/collections/${id}`, { method: "DELETE" }),
    onSuccess: () => {
      toast.success(t("collectionDeleted"));
      void queryClient.invalidateQueries({ queryKey: ["collections"] });
      router.push("/knowledge");
    },
    onError,
  });

  if (collection.isLoading) return <Skeleton className="h-96" />;
  if (collection.error instanceof ApiError && collection.error.status === 404) {
    return (
      <Alert>
        <AlertTitle>{t("notFound")}</AlertTitle>
        <AlertDescription>
          <Link href="/knowledge" className="underline">{t("backToKnowledge")}</Link>
        </AlertDescription>
      </Alert>
    );
  }
  const c = collection.data;
  if (!c) return null;
  const docs = documents.data ?? [];
  const sourceName = (sourceId: string | null) => sources.data?.find((s) => s.id === sourceId)?.name ?? t("uploads");
  const external = (sources.data ?? []).filter((s) => s.connector !== "upload").length;

  return (
    <div className="space-y-6">
      <nav aria-label={t("breadcrumb")} className="text-sm text-muted-foreground">
        <Link href="/knowledge" className="hover:text-foreground hover:underline">{t("title")}</Link>
        <span aria-hidden="true"> / </span>
        <span className="text-foreground">{c.name}</span>
      </nav>
      <PageHeader
        title={c.name}
        description={c.description || t("noDescription")}
        icon={BookOpenText}
        tone="sky"
        actions={
          <>
            <Button asChild variant="outline">
              <Link href={`/playground?collection=${c.id}`}>
                <FlaskConical className="size-4" aria-hidden="true" />
                {t("tryInPlayground")}
              </Link>
            </Button>
            <Hint label={t("reindexHint")}>
              <Button variant="outline" onClick={() => reindex.mutate()} disabled={reindex.isPending || !docs.length}>
                <RefreshCcw className="size-4" aria-hidden="true" />
                {t("reindex")}
              </Button>
            </Hint>
            <Button variant="outline" onClick={() => setSettingsOpen(true)} data-testid="collection-settings">
              <Settings2 className="size-4" aria-hidden="true" />
              {t("settings")}
            </Button>
            <Hint label={t("deleteCollectionHint")}>
              <Button variant="ghost" size="icon" className="hover:text-destructive" onClick={() => setDeleting(true)} aria-label={`${tc("delete")}: ${c.name}`}>
                <Trash2 className="size-4" aria-hidden="true" />
              </Button>
            </Hint>
          </>
        }
      />
      <div className="flex flex-wrap items-center gap-2 text-sm">
        <StatusBadge tone={CLASSIFICATION_TONE[c.classification]}>{t(`classifications.${c.classification}`)}</StatusBadge>
        <span className="inline-flex items-center gap-1.5 rounded-full bg-muted px-2.5 py-0.5 text-xs">
          {c.acl_groups.length ? <Lock className="size-3.5" aria-hidden="true" /> : <Users className="size-3.5" aria-hidden="true" />}
          {c.acl_groups.length ? t("restrictedTo", { groups: c.acl_groups.join(", ") }) : t("everyone")}
        </span>
        <span className="rounded-full bg-muted px-2.5 py-0.5 text-xs">{t("modelChip", { profile: c.model_profile })}</span>
        {c.embedding_model ? <span className="rounded-full bg-muted px-2.5 py-0.5 text-xs" dir="ltr">{c.embedding_model}</span> : null}
      </div>
      <ActiveRuns runs={runs.data ?? []} sourceName={sourceName} />
      <Tabs defaultValue="documents">
        <TabsList>
          <TabsTrigger value="documents">{t("tabs.documents", { count: docs.length })}</TabsTrigger>
          <TabsTrigger value="sources">{t("tabs.sources", { count: external })}</TabsTrigger>
          <TabsTrigger value="activity">{t("tabs.activity")}</TabsTrigger>
        </TabsList>
        <TabsContent value="documents" className="space-y-4 pt-4">
          <UploadZone collectionId={c.id} compact={docs.length > 0} />
          <DocumentsTable collectionId={c.id} />
        </TabsContent>
        <TabsContent value="sources" className="pt-4">
          <SourcesPanel collectionId={c.id} documents={docs} />
        </TabsContent>
        <TabsContent value="activity" className="pt-4">
          <RunHistory runs={runs.data ?? []} sourceName={sourceName} />
        </TabsContent>
      </Tabs>
      <CollectionSettings collection={c} open={settingsOpen} onOpenChange={setSettingsOpen} />
      <AlertDialog open={deleting} onOpenChange={setDeleting}>
        <AlertDialogContent>
          <AlertDialogHeader>
            <AlertDialogTitle>{t("deleteCollectionTitle", { name: c.name })}</AlertDialogTitle>
            <AlertDialogDescription>
              {t("deleteCollectionBody", { documents: docs.length, sources: external })}
            </AlertDialogDescription>
          </AlertDialogHeader>
          <AlertDialogFooter>
            <AlertDialogCancel>{tc("cancel")}</AlertDialogCancel>
            <AlertDialogAction onClick={() => remove.mutate()} data-testid="confirm-delete-collection">{tc("delete")}</AlertDialogAction>
          </AlertDialogFooter>
        </AlertDialogContent>
      </AlertDialog>
    </div>
  );
}

function CollectionSettings({ collection: c, open, onOpenChange }: { collection: Collection; open: boolean; onOpenChange: (o: boolean) => void }) {
  const t = useTranslations("knowledge");
  const tc = useTranslations("common");
  const queryClient = useQueryClient();
  const onError = useErrorToast();
  const [description, setDescription] = useState(c.description);
  const [classification, setClassification] = useState<Classification>(c.classification);
  const [modelProfile, setModelProfile] = useState(c.model_profile);
  const [retrievalProfile, setRetrievalProfile] = useState(c.retrieval_profile);
  const [groups, setGroups] = useState(c.acl_groups.join(", "));
  const groupList = groups.split(",").map((g) => g.trim()).filter(Boolean);
  const reindexes =
    modelProfile !== c.model_profile ||
    retrievalProfile !== c.retrieval_profile ||
    classification !== c.classification ||
    groupList.join(",") !== c.acl_groups.join(",");

  const save = useMutation({
    mutationFn: () =>
      api<Collection>(`ingestion/v1/collections/${c.id}`, {
        method: "PATCH",
        json: { description, classification, model_profile: modelProfile, retrieval_profile: retrievalProfile, acl_groups: groupList },
      }),
    onSuccess: () => {
      toast.success(reindexes ? t("savedReindexing") : t("saved"));
      for (const key of ["collection", "runs", "documents"]) void queryClient.invalidateQueries({ queryKey: [key, c.id] });
      void queryClient.invalidateQueries({ queryKey: ["collections"] });
      onOpenChange(false);
    },
    onError,
  });

  function submit(event: FormEvent) {
    event.preventDefault();
    save.mutate();
  }

  return (
    <Dialog open={open} onOpenChange={onOpenChange}>
      <DialogContent className="sm:max-w-lg">
        <form onSubmit={submit} className="space-y-5">
          <DialogHeader>
            <DialogTitle>{t("settingsTitle", { name: c.name })}</DialogTitle>
            <DialogDescription>{t("settingsBody")}</DialogDescription>
          </DialogHeader>
          <div className="space-y-2">
            <Label htmlFor="settings-description">{tc("description")}</Label>
            <Textarea id="settings-description" value={description} onChange={(e) => setDescription(e.target.value)} rows={2} maxLength={500} />
          </div>
          <div className="grid gap-4 sm:grid-cols-2">
            <div className="space-y-2">
              <Label htmlFor="settings-classification">{t("classification")}</Label>
              <Select value={classification} onValueChange={(v) => setClassification(v as Classification)}>
                <SelectTrigger id="settings-classification" className="w-full">
                  <SelectValue />
                </SelectTrigger>
                <SelectContent>
                  {CLASSIFICATIONS.map((x) => (
                    <SelectItem key={x} value={x}>{t(`classifications.${x}`)}</SelectItem>
                  ))}
                </SelectContent>
              </Select>
            </div>
            <div className="space-y-2">
              <Label htmlFor="settings-model">{t("modelProfile")}</Label>
              <ProfileSelect kind="model_profile" id="settings-model" value={modelProfile} onChange={setModelProfile} />
            </div>
          </div>
          <div className="space-y-2">
            <Label htmlFor="settings-retrieval">{t("retrievalProfile")}</Label>
            <ProfileSelect kind="retrieval_profile" id="settings-retrieval" value={retrievalProfile} onChange={setRetrievalProfile} />
          </div>
          <div className="space-y-2">
            <Label htmlFor="settings-groups">{t("accessGroups")}</Label>
            <Input id="settings-groups" value={groups} onChange={(e) => setGroups(e.target.value)} aria-describedby="settings-groups-help" />
            <p id="settings-groups-help" className="text-xs text-muted-foreground">{t("accessGroupsHelp")}</p>
          </div>
          {reindexes ? (
            <Alert>
              <RefreshCcw className="size-4" aria-hidden="true" />
              <AlertTitle>{t("reindexWarningTitle")}</AlertTitle>
              <AlertDescription>{t("reindexWarningBody")}</AlertDescription>
            </Alert>
          ) : null}
          <DialogFooter>
            <Button type="button" variant="outline" onClick={() => onOpenChange(false)}>{tc("cancel")}</Button>
            <Button type="submit" disabled={save.isPending}>{tc("save")}</Button>
          </DialogFooter>
        </form>
      </DialogContent>
    </Dialog>
  );
}
