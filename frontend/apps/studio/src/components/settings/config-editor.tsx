"use client";

import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { Rocket, Save, Send } from "lucide-react";
import { useRouter } from "next/navigation";
import { useTranslations } from "next-intl";
import { useMemo, useState } from "react";
import { toast } from "sonner";

import { PageHeader } from "@/components/page-header";
import { problemErrors, validate, type FieldErrors } from "@/components/schema-form/schema";
import { SchemaForm } from "@/components/schema-form/schema-form";
import { Alert, AlertDescription, AlertTitle } from "@/components/ui/alert";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import { Select, SelectContent, SelectItem, SelectTrigger, SelectValue } from "@/components/ui/select";
import { Skeleton } from "@/components/ui/skeleton";
import { api, ApiError } from "@/lib/api";
import { useErrorToast } from "@/lib/hooks";

import { type KindInfo, kindVisual, type ObjectSummary, useKinds } from "./configuration";
import { StatusBadge } from "@/components/visual/status-badge";
import { Hint } from "@/components/visual/hint";

const ENVIRONMENTS = ["dev", "staging", "prod"] as const;

interface VersionDetail {
  version: number;
  status: "draft" | "published";
  spec: Record<string, unknown>;
}

export function ConfigEditor({ kind, name }: { kind: string; name: string }) {
  const isNew = name === "new";
  const kinds = useKinds();
  const info = kinds.data?.find((k) => k.kind === kind);
  const object = useQuery({
    queryKey: ["object", kind, name],
    queryFn: () => api<ObjectSummary>(`config/v1/objects/${kind}/${name}`),
    enabled: !isNew,
  });
  const latest = object.data?.versions.at(-1);
  const detail = useQuery({
    queryKey: ["version", kind, name, latest?.version],
    queryFn: () => api<VersionDetail>(`config/v1/objects/${kind}/${name}/versions/${latest?.version}`),
    enabled: !!latest,
  });

  if (kinds.isLoading || (!isNew && (object.isLoading || detail.isLoading))) return <Skeleton className="h-96" />;
  if (!info) return null;
  return (
    <EditorBody
      key={`${latest?.version ?? "new"}-${detail.dataUpdatedAt}`}
      kind={kind}
      name={name}
      info={info}
      object={object.data}
      initialSpec={detail.data?.spec ?? {}}
    />
  );
}

/** Keyed by the loaded version, so state initialises from fresh data without effects. */
function EditorBody({ kind, name, info, object, initialSpec }: { kind: string; name: string; info: KindInfo; object?: ObjectSummary; initialSpec: Record<string, unknown> }) {
  const t = useTranslations("config");
  const tc = useTranslations("common");
  const th = useTranslations("hints");
  const router = useRouter();
  const queryClient = useQueryClient();
  const onError = useErrorToast();
  const isNew = name === "new";
  const latest = object?.versions.at(-1);
  const [spec, setSpec] = useState<Record<string, unknown>>(initialSpec);
  const [newName, setNewName] = useState("");
  const [errors, setErrors] = useState<FieldErrors>({});
  const [blocked, setBlocked] = useState<string | null>(null);
  const [env, setEnv] = useState<(typeof ENVIRONMENTS)[number]>("dev");

  const refresh = () => Promise.all([
    queryClient.invalidateQueries({ queryKey: ["object", kind, name] }),
    queryClient.invalidateQueries({ queryKey: ["objects", kind] }),
  ]);

  const handle = (err: unknown) => {
    if (err instanceof ApiError && err.problem.code === "config_invalid") {
      setErrors(problemErrors(err.problem.errors as { path?: string; message?: string }[]));
      return;
    }
    if (err instanceof ApiError && err.problem.code === "security_floor_violation") {
      setBlocked(err.problem.detail ?? "");
      return;
    }
    onError(err);
  };

  const clientCheck = (): boolean => {
    if (!info) return false;
    const found = validate(info.schema, spec);
    setErrors(found);
    setBlocked(null);
    return Object.keys(found).length === 0;
  };

  const save = useMutation({
    mutationFn: async () => {
      if (isNew) {
        await api("config/v1/objects", { method: "POST", json: { kind, name: newName, spec } });
        return { version: 1 };
      }
      return api<{ version: number }>(`config/v1/objects/${kind}/${name}/draft`, { method: "PUT", json: { spec } });
    },
    onSuccess: async ({ version }) => {
      toast.success(isNew ? t("created", { name: newName }) : t("draftSaved", { version }));
      if (isNew) router.replace(`/settings/configuration/${kind}/${newName}`);
      else await refresh();
    },
    onError: handle,
  });
  const publish = useMutation({
    mutationFn: (version: number) => api(`config/v1/objects/${kind}/${name}/versions/${version}/publish`, { method: "POST" }),
    onSuccess: async (_, version) => {
      toast.success(t("published", { version }));
      await refresh();
    },
    onError: handle,
  });
  const deploy = useMutation({
    mutationFn: (version: number) => api(`config/v1/objects/${kind}/${name}/deployments/${env}`, { method: "PUT", json: { version } }),
    onSuccess: async (_, version) => {
      toast.success(t("deployed", { version, environment: env }));
      setBlocked(null);
      await refresh();
    },
    onError: handle,
  });

  const latestPublished = useMemo(() => object?.versions.filter((v) => v.status === "published").at(-1), [object]);


  return (
    <div className="space-y-8">
      <PageHeader
        title={isNew ? t("newObject", { kind: info.title }) : t("editing", { name })}
        description={info.description}
        icon={kindVisual(kind).icon}
        tone={kindVisual(kind).tone}
        actions={
          <div className="flex flex-wrap gap-2">
            <Button variant="outline" onClick={() => clientCheck() && save.mutate()} disabled={save.isPending || (isNew && !/^[a-z0-9][a-z0-9-]{1,62}$/.test(newName))} data-testid="save-draft">
              <Save className="size-4" aria-hidden="true" />
              {t("saveDraft")}
            </Button>
            {latest?.status === "draft" ? (
              <Button onClick={() => publish.mutate(latest.version)} disabled={publish.isPending} data-testid="publish">
                <Send className="size-4" aria-hidden="true" />
                {t("publish", { version: latest.version })}
              </Button>
            ) : null}
          </div>
        }
      />
      {blocked !== null ? (
        <Alert variant="destructive">
          <AlertTitle>{t("floorViolation")}</AlertTitle>
          <AlertDescription>{blocked}</AlertDescription>
        </Alert>
      ) : null}
      {!isNew && object ? (
        <section aria-label={t("versions")} className="nx-card flex flex-wrap items-end gap-4 p-4">
          <div className="space-y-1">
            <p className="text-sm font-medium">{t("versions")}</p>
            <div className="flex flex-wrap gap-1">
              {object.versions.map((v) => (
                <Hint key={v.version} label={th(v.status === "published" ? "publishedVersion" : "draftVersion")}>
                  <span className="inline-flex">
                    <StatusBadge tone={v.status === "published" ? "navy" : "amber"}>
                      v{v.version} · {t(`statuses.${v.status}`)}
                    </StatusBadge>
                  </span>
                </Hint>
              ))}
            </div>
          </div>
          <div className="space-y-1">
            <p className="text-sm font-medium">{t("deployments")}</p>
            <div className="flex gap-1">
              {Object.keys(object.deployments).length ? Object.entries(object.deployments).map(([e, v]) => (
                <Hint key={e} label={th("liveIn")}>
                  <span className="inline-flex">
                    <StatusBadge tone="teal" live>{e} v{v}</StatusBadge>
                  </span>
                </Hint>
              )) : <span className="text-sm text-muted-foreground">{t("notDeployed")}</span>}
            </div>
          </div>
          {latestPublished ? (
            <div className="ms-auto flex items-end gap-2">
              <div className="space-y-1">
                <Label htmlFor="deploy-env">{t("deployTo")}</Label>
                <Select value={env} onValueChange={(v) => setEnv(v as typeof env)}>
                  <SelectTrigger id="deploy-env" className="w-32"><SelectValue /></SelectTrigger>
                  <SelectContent>{ENVIRONMENTS.map((e) => <SelectItem key={e} value={e}>{e}</SelectItem>)}</SelectContent>
                </Select>
              </div>
              <Button variant="secondary" onClick={() => deploy.mutate(latestPublished.version)} disabled={deploy.isPending} data-testid="deploy">
                <Rocket className="size-4" aria-hidden="true" />
                {tc("deploy")} v{latestPublished.version}
              </Button>
            </div>
          ) : null}
        </section>
      ) : null}
      {isNew ? (
        <div className="max-w-sm space-y-2">
          <Label htmlFor="object-name">{t("name")}</Label>
          <Input id="object-name" dir="ltr" required value={newName} aria-describedby="object-name-help" onChange={(e) => setNewName(e.target.value.toLowerCase())} />
          <p id="object-name-help" className="text-sm text-muted-foreground">{t("nameHelp")}</p>
        </div>
      ) : null}
      <div className="nx-card nx-page p-4 sm:p-6">
        <SchemaForm schema={info.schema} value={spec} onChange={setSpec} errors={errors} />
      </div>
    </div>
  );
}
