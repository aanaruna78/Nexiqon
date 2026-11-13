"use client";

import { useMutation, useQueries, useQueryClient } from "@tanstack/react-query";
import { Blocks, FileCode2, KeyRound, Play, Plus, Trash2, Wrench } from "lucide-react";
import { useRouter, useSearchParams } from "next/navigation";
import { useFormatter, useTranslations } from "next-intl";
import { type ChangeEvent, type FormEvent, useState } from "react";
import { toast } from "sonner";

import { EmptyState } from "@/components/empty-state";
import { PageHeader } from "@/components/page-header";
import { Alert, AlertDescription, AlertTitle } from "@/components/ui/alert";
import { Button } from "@/components/ui/button";
import { Checkbox } from "@/components/ui/checkbox";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import { Select, SelectContent, SelectItem, SelectTrigger, SelectValue } from "@/components/ui/select";
import { Sheet, SheetContent, SheetDescription, SheetHeader, SheetTitle } from "@/components/ui/sheet";
import { Skeleton } from "@/components/ui/skeleton";
import { Table, TableBody, TableCell, TableHead, TableHeader, TableRow } from "@/components/ui/table";
import { Tabs, TabsContent, TabsList, TabsTrigger } from "@/components/ui/tabs";
import { Textarea } from "@/components/ui/textarea";
import { IconTile } from "@/components/visual/icon-tile";
import { StatusBadge } from "@/components/visual/status-badge";
import { api, ApiError } from "@/lib/api";
import { useErrorToast } from "@/lib/hooks";
import { type AgentSpec, type ConfigObject, credentialName, riskTone, type ToolSpec, type VersionDetail } from "@/lib/studio";
import { useApprovals, useCalls, useCredentials, useObjects } from "@/lib/studio-hooks";

const TABS = ["tools", "connect", "credentials", "approvals", "calls"] as const;

/** Actions & integrations (ST-09, UX G6): tools, their risk and reach, a dry-run console and logs. */
export function ActionsPage() {
  const t = useTranslations("actions");
  const params = useSearchParams();
  const router = useRouter();
  const tab = (TABS as readonly string[]).includes(params.get("tab") ?? "") ? params.get("tab")! : "tools";
  return (
    <div className="space-y-6">
      <PageHeader title={t("title")} description={t("subtitle")} icon={Blocks} tone="rose" />
      <Tabs value={tab} onValueChange={(v) => router.replace(`/actions?tab=${v}`)}>
        <TabsList className="h-auto flex-wrap">
          {TABS.map((k) => <TabsTrigger key={k} value={k} data-testid={`actions-tab-${k}`}>{t(`tabs.${k}`)}</TabsTrigger>)}
        </TabsList>
        <TabsContent value="tools" className="pt-4"><Tools /></TabsContent>
        <TabsContent value="connect" className="pt-4"><Connect /></TabsContent>
        <TabsContent value="credentials" className="pt-4"><Credentials /></TabsContent>
        <TabsContent value="approvals" className="pt-4"><Approvals /></TabsContent>
        <TabsContent value="calls" className="pt-4"><Calls /></TabsContent>
      </Tabs>
    </div>
  );
}

function useSpecs(kind: string, objects: ConfigObject[] | undefined) {
  return useQueries({
    queries: (objects ?? []).map((o) => {
      const v = o.deployments.dev ?? o.versions.at(-1)?.version;
      return { queryKey: ["version", kind, o.name, v], queryFn: () => api<VersionDetail>(`config/v1/objects/${kind}/${o.name}/versions/${v}`), staleTime: Infinity };
    }),
  });
}

function Tools() {
  const t = useTranslations("actions");
  const tools = useObjects("tool");
  const agents = useObjects("agent");
  const credentials = useCredentials();
  const toolSpecs = useSpecs("tool", tools.data);
  const agentSpecs = useSpecs("agent", agents.data);
  const [open, setOpen] = useState<{ name: string; spec: ToolSpec } | null>(null);
  if (tools.isLoading) return <Skeleton className="h-64" />;
  if (!tools.data?.length) {
    return <EmptyState icon={Wrench} tone="rose" title={t("empty")} body={t("emptyBody")} />;
  }
  const stored = new Set((credentials.data ?? []).map((c) => c.name));
  return (
    <>
      <ul className="grid gap-4 md:grid-cols-2" data-testid="tool-list">
        {tools.data.map((tool, i) => {
          const spec = toolSpecs[i]?.data?.spec as ToolSpec | undefined;
          const usedBy = (agentSpecs.map((q) => q.data?.spec) as (AgentSpec | undefined)[])
            .map((a, j) => (a?.tools?.includes(tool.name) ? (a.display_name ?? agents.data?.[j]?.name) : null))
            .filter(Boolean);
          const credential = credentialName(spec?.credential_ref);
          return (
            <li key={tool.name} className="nx-card flex flex-col gap-3 p-4">
              <div className="flex items-start gap-3">
                <IconTile icon={Wrench} tone={riskTone(spec?.risk_level)} />
                <div className="min-w-0 flex-1">
                  <h2 className="truncate font-semibold">{tool.name}</h2>
                  <p className="text-sm text-muted-foreground">{spec?.description}</p>
                </div>
                {spec?.risk_level ? <StatusBadge tone={riskTone(spec.risk_level)}>{t(`risk.${spec.risk_level}`)}</StatusBadge> : null}
              </div>
              <dl className="grid gap-1 text-xs">
                <div className="flex gap-2"><dt className="text-muted-foreground">{t("calls")}</dt><dd className="truncate font-mono" dir="ltr">{spec?.request?.method} {spec?.request?.url_template}</dd></div>
                <div className="flex gap-2"><dt className="text-muted-foreground">{t("hosts")}</dt><dd dir="ltr">{spec?.request?.host_allowlist?.join(", ") || "—"}</dd></div>
                <div className="flex items-center gap-2">
                  <dt className="text-muted-foreground">{t("credential")}</dt>
                  <dd>{credential ? <StatusBadge tone={stored.has(credential) ? "teal" : "rose"}>{stored.has(credential) ? credential : t("missing", { name: credential })}</StatusBadge> : t("none")}</dd>
                </div>
                <div className="flex gap-2"><dt className="text-muted-foreground">{t("confirmation")}</dt><dd>{spec?.risk_level !== "read" || spec?.confirmation === "always" ? t("asksUser") : t("noConfirmation")}</dd></div>
                <div className="flex gap-2"><dt className="text-muted-foreground">{t("usedBy")}</dt><dd>{usedBy.length ? usedBy.join(", ") : t("noAssistant")}</dd></div>
              </dl>
              <div className="mt-auto flex gap-2">
                <Button variant="outline" size="sm" onClick={() => spec && setOpen({ name: tool.name, spec })} data-testid={`try-${tool.name}`}>
                  <Play className="size-4" aria-hidden="true" />
                  {t("tryIt")}
                </Button>
              </div>
            </li>
          );
        })}
      </ul>
      <DryRun tool={open} onClose={() => setOpen(null)} />
    </>
  );
}

function exampleArguments(schema: Record<string, unknown> | undefined): string {
  const props = (schema?.properties ?? {}) as Record<string, { type?: string; example?: unknown }>;
  const out: Record<string, unknown> = {};
  for (const [k, v] of Object.entries(props)) out[k] = v.example ?? (v.type === "integer" || v.type === "number" ? 0 : v.type === "boolean" ? false : "");
  return JSON.stringify(out, null, 2);
}

function DryRun({ tool, onClose }: { tool: { name: string; spec: ToolSpec } | null; onClose: () => void }) {
  const t = useTranslations("actions");
  const [args, setArgs] = useState<Record<string, string>>({});
  const text = tool ? (args[tool.name] ?? exampleArguments(tool.spec.input_schema)) : "";
  const run = useMutation({
    mutationFn: () => api<{ valid: boolean; problems: string[]; request: Record<string, unknown> | null }>(`tool-gateway/v1/tools/${tool!.name}/dry-run`, { method: "POST", json: { arguments: JSON.parse(text) } }),
  });
  let parseError = false;
  try {
    JSON.parse(text || "{}");
  } catch {
    parseError = true;
  }
  return (
    <Sheet open={!!tool} onOpenChange={(o) => { if (!o) { run.reset(); onClose(); } }}>
      <SheetContent className="w-full overflow-y-auto sm:max-w-xl" data-testid="dry-run">
        {tool ? (
          <>
            <SheetHeader>
              <SheetTitle>{t("consoleTitle", { name: tool.name })}</SheetTitle>
              <SheetDescription>{t("consoleBody")}</SheetDescription>
            </SheetHeader>
            <div className="space-y-4 px-4 pb-8">
              <div className="space-y-2">
                <Label htmlFor="dr-args">{t("arguments")}</Label>
                <Textarea id="dr-args" rows={8} className="font-mono text-xs" dir="ltr" value={text} onChange={(e) => setArgs({ ...args, [tool.name]: e.target.value })} aria-invalid={parseError} />
                {parseError ? <p className="text-xs text-destructive">{t("badJson")}</p> : null}
              </div>
              <Button onClick={() => run.mutate()} disabled={parseError || run.isPending} data-testid="dry-run-go">
                <Play className="size-4" aria-hidden="true" />
                {t("dryRun")}
              </Button>
              {run.data ? (
                run.data.valid && run.data.request ? (
                  <div className="space-y-2">
                    <StatusBadge tone="teal">{t("wouldSend")}</StatusBadge>
                    <pre tabIndex={0} aria-label={t("wouldSend")} className="overflow-auto rounded-xl border bg-muted/40 p-3 text-xs focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring" dir="ltr" data-testid="dry-run-request">{JSON.stringify(run.data.request, null, 2)}</pre>
                    <p className="text-xs text-muted-foreground">{t("nothingSent")}</p>
                  </div>
                ) : (
                  <Alert variant="destructive">
                    <AlertTitle>{t("invalidArguments")}</AlertTitle>
                    <AlertDescription><ul className="list-disc ps-4">{run.data.problems.map((p, i) => <li key={i}>{p}</li>)}</ul></AlertDescription>
                  </Alert>
                )
              ) : null}
              {run.error ? <Alert variant="destructive"><AlertTitle>{run.error instanceof ApiError ? run.error.problem.detail : t("failed")}</AlertTitle></Alert> : null}
            </div>
          </>
        ) : null}
      </SheetContent>
    </Sheet>
  );
}

interface Imported {
  name: string;
  operation_id: string;
  spec: ToolSpec;
}

function Connect() {
  const t = useTranslations("actions");
  const client = useQueryClient();
  const onError = useErrorToast();
  const existing = useObjects("tool");
  const [specText, setSpecText] = useState("");
  const [baseUrl, setBaseUrl] = useState("");
  const [credential, setCredential] = useState("");
  const [scheme, setScheme] = useState("bearer");
  const [found, setFound] = useState<Imported[] | null>(null);
  const [chosen, setChosen] = useState<string[]>([]);
  const taken = new Set((existing.data ?? []).map((o) => o.name));

  const parse = useMutation({
    mutationFn: () =>
      api<Imported[]>("tool-gateway/v1/openapi/import", {
        method: "POST",
        json: { spec: specText, base_url: baseUrl || undefined, credential_ref: credential || undefined, auth_scheme: scheme },
      }),
    onSuccess: (tools) => {
      setFound(tools);
      setChosen(tools.filter((x) => !taken.has(x.name)).map((x) => x.name));
    },
    onError,
  });

  const add = useMutation({
    mutationFn: async () => {
      for (const tool of (found ?? []).filter((x) => chosen.includes(x.name))) {
        await api("config/v1/objects", { method: "POST", json: { kind: "tool", name: tool.name, description: tool.spec.description ?? "", spec: tool.spec } });
        await api(`config/v1/objects/tool/${tool.name}/versions/1/publish`, { method: "POST" });
        await api(`config/v1/objects/tool/${tool.name}/deployments/dev`, { method: "PUT", json: { version: 1, reason: "imported from OpenAPI" } });
      }
    },
    onSuccess: async () => {
      toast.success(t("added", { count: chosen.length }));
      setFound(null);
      await client.invalidateQueries({ queryKey: ["objects", "tool"] });
    },
    onError,
  });

  async function pick(e: ChangeEvent<HTMLInputElement>) {
    const file = e.target.files?.[0];
    if (file) setSpecText(await file.text());
  }

  return (
    <div className="grid gap-6 lg:grid-cols-2">
      <form
        className="nx-card space-y-4 p-4"
        onSubmit={(e: FormEvent) => {
          e.preventDefault();
          parse.mutate();
        }}
      >
        <h2 className="flex items-center gap-2 font-semibold"><FileCode2 className="size-4" aria-hidden="true" />{t("openapiTitle")}</h2>
        <p className="text-sm text-muted-foreground">{t("openapiBody")}</p>
        <div className="space-y-2">
          <Label htmlFor="oa-spec">{t("openapiSpec")}</Label>
          <Textarea id="oa-spec" rows={8} className="font-mono text-xs" dir="ltr" value={specText} onChange={(e) => setSpecText(e.target.value)} placeholder="openapi: 3.0.3" data-testid="openapi-spec" />
          <input type="file" accept=".yaml,.yml,.json" onChange={pick} aria-label={t("openapiFile")} className="text-sm" />
        </div>
        <div className="grid gap-4 sm:grid-cols-2">
          <div className="space-y-2">
            <Label htmlFor="oa-base">{t("baseUrl")}</Label>
            <Input id="oa-base" value={baseUrl} onChange={(e) => setBaseUrl(e.target.value)} placeholder="https://api.example.com" dir="ltr" />
          </div>
          <div className="space-y-2">
            <Label htmlFor="oa-cred">{t("credentialName")}</Label>
            <Input id="oa-cred" value={credential} onChange={(e) => setCredential(e.target.value)} placeholder="crm-api" dir="ltr" />
          </div>
          <div className="space-y-2">
            <Label htmlFor="oa-scheme">{t("authScheme")}</Label>
            <Select value={scheme} onValueChange={setScheme}>
              <SelectTrigger id="oa-scheme" className="w-full"><SelectValue /></SelectTrigger>
              <SelectContent>
                {["bearer", "header", "basic"].map((s) => <SelectItem key={s} value={s}>{t(`schemes.${s}`)}</SelectItem>)}
              </SelectContent>
            </Select>
          </div>
        </div>
        <Button type="submit" disabled={parse.isPending || specText.trim().length < 10} data-testid="openapi-read">{t("readOperations")}</Button>
      </form>
      <section className="nx-card space-y-3 p-4" aria-labelledby="oa-found" aria-live="polite">
        <h2 id="oa-found" className="font-semibold">{t("operations")}</h2>
        {!found ? <p className="text-sm text-muted-foreground">{t("operationsEmpty")}</p> : null}
        {found?.map((tool) => (
          <div key={tool.name} className="flex items-start gap-2">
            <Checkbox id={`op-${tool.name}`} checked={chosen.includes(tool.name)} disabled={taken.has(tool.name)} onCheckedChange={(on) => setChosen(on ? [...chosen, tool.name] : chosen.filter((x) => x !== tool.name))} className="mt-0.5" />
            <Label htmlFor={`op-${tool.name}`} className="flex flex-1 flex-col items-start gap-0.5 font-normal">
              <span className="flex flex-wrap items-center gap-2">
                <span className="font-medium">{tool.name}</span>
                <StatusBadge tone={riskTone(tool.spec.risk_level)}>{t(`risk.${tool.spec.risk_level ?? "high"}`)}</StatusBadge>
                {taken.has(tool.name) ? <StatusBadge tone="slate">{t("exists")}</StatusBadge> : null}
              </span>
              <span className="text-xs text-muted-foreground">{tool.spec.description}</span>
              <span className="font-mono text-xs text-muted-foreground" dir="ltr">{tool.spec.request?.method} {tool.spec.request?.url_template}</span>
            </Label>
          </div>
        ))}
        {found?.length ? (
          <Button onClick={() => add.mutate()} disabled={!chosen.length || add.isPending} data-testid="openapi-add">
            <Plus className="size-4" aria-hidden="true" />
            {t("addTools", { count: chosen.length })}
          </Button>
        ) : null}
      </section>
    </div>
  );
}

function Credentials() {
  const t = useTranslations("actions");
  const format = useFormatter();
  const client = useQueryClient();
  const onError = useErrorToast();
  const list = useCredentials();
  const [name, setName] = useState("");
  const [value, setValue] = useState("");
  const refresh = () => client.invalidateQueries({ queryKey: ["credentials"] });
  const save = useMutation({
    mutationFn: () => api(`tool-gateway/v1/credentials/${name}`, { method: "PUT", json: { value } }),
    onSuccess: async () => {
      toast.success(t("credentialSaved", { name }));
      setName("");
      setValue("");
      await refresh();
    },
    onError,
  });
  const remove = useMutation({
    mutationFn: (n: string) => api(`tool-gateway/v1/credentials/${n}`, { method: "DELETE" }),
    onSuccess: refresh,
    onError,
  });
  return (
    <div className="grid gap-6 lg:grid-cols-2">
      <form
        className="nx-card space-y-4 p-4"
        onSubmit={(e) => {
          e.preventDefault();
          save.mutate();
        }}
      >
        <h2 className="flex items-center gap-2 font-semibold"><KeyRound className="size-4" aria-hidden="true" />{t("addCredential")}</h2>
        <p className="text-sm text-muted-foreground">{t("credentialBody")}</p>
        <div className="space-y-2">
          <Label htmlFor="cr-name">{t("credentialName")}</Label>
          <Input id="cr-name" value={name} onChange={(e) => setName(e.target.value)} pattern="^[a-z0-9][a-z0-9-]{1,62}$" required dir="ltr" />
        </div>
        <div className="space-y-2">
          <Label htmlFor="cr-value">{t("credentialValue")}</Label>
          <Input id="cr-value" type="password" autoComplete="off" value={value} onChange={(e) => setValue(e.target.value)} required />
        </div>
        <Button type="submit" disabled={save.isPending || !name || !value}>{t("store")}</Button>
      </form>
      <section className="nx-card space-y-3 p-4" aria-labelledby="cr-list">
        <h2 id="cr-list" className="font-semibold">{t("stored")}</h2>
        {list.error ? <p className="text-sm text-muted-foreground">{t("credentialsUnavailable")}</p> : null}
        <ul className="divide-y" data-testid="credential-list">
          {(list.data ?? []).map((c) => (
            <li key={c.name} className="flex items-center justify-between gap-2 py-2">
              <span className="flex flex-col">
                <span className="font-medium" dir="ltr">{c.name}</span>
                <span className="text-xs text-muted-foreground">{c.updated_at ? t("updated", { when: format.relativeTime(new Date(c.updated_at)) }) : t("valueHidden")}</span>
              </span>
              <Button variant="ghost" size="icon" aria-label={t("deleteCredential", { name: c.name })} onClick={() => remove.mutate(c.name)}>
                <Trash2 className="size-4" aria-hidden="true" />
              </Button>
            </li>
          ))}
          {list.data && !list.data.length ? <li className="py-2 text-sm text-muted-foreground">{t("noCredentials")}</li> : null}
        </ul>
      </section>
    </div>
  );
}

function Approvals() {
  const t = useTranslations("actions");
  const format = useFormatter();
  const list = useApprovals();
  if (list.isLoading) return <Skeleton className="h-48" />;
  if (!list.data?.length) return <p className="text-sm text-muted-foreground">{t("noApprovals")}</p>;
  return (
    <Table data-testid="approvals">
      <TableHeader>
        <TableRow>
          <TableHead>{t("when")}</TableHead>
          <TableHead>{t("tool")}</TableHead>
          <TableHead>{t("what")}</TableHead>
          <TableHead>{t("who")}</TableHead>
          <TableHead>{t("status")}</TableHead>
        </TableRow>
      </TableHeader>
      <TableBody>
        {list.data.map((a) => (
          <TableRow key={a.id}>
            <TableCell className="whitespace-nowrap">{format.relativeTime(new Date(a.created_at))}</TableCell>
            <TableCell>{a.tool}</TableCell>
            <TableCell className="max-w-80 truncate" title={a.summary}>{a.summary}</TableCell>
            <TableCell className="max-w-40 truncate" title={a.actor_id}>{a.actor_id}</TableCell>
            <TableCell><StatusBadge tone={a.status === "used" || a.status === "approved" ? "teal" : a.status === "pending" ? "amber" : "slate"}>{t(`approvalStatus.${a.status}`)}</StatusBadge></TableCell>
          </TableRow>
        ))}
      </TableBody>
    </Table>
  );
}

function Calls() {
  const t = useTranslations("actions");
  const format = useFormatter();
  const list = useCalls();
  if (list.isLoading) return <Skeleton className="h-48" />;
  if (!list.data?.length) return <p className="text-sm text-muted-foreground">{t("noCalls")}</p>;
  return (
    <Table data-testid="calls">
      <TableHeader>
        <TableRow>
          <TableHead>{t("when")}</TableHead>
          <TableHead>{t("tool")}</TableHead>
          <TableHead>{t("assistant")}</TableHead>
          <TableHead>{t("status")}</TableHead>
          <TableHead className="text-end">{t("latency")}</TableHead>
        </TableRow>
      </TableHeader>
      <TableBody>
        {list.data.map((c) => (
          <TableRow key={c.id}>
            <TableCell className="whitespace-nowrap">{format.relativeTime(new Date(c.created_at))}</TableCell>
            <TableCell>{c.tool} <span className="text-xs text-muted-foreground">v{c.tool_version}</span></TableCell>
            <TableCell>{c.agent}</TableCell>
            <TableCell><StatusBadge tone={c.status === "ok" ? "teal" : "rose"}>{c.status === "ok" ? t("ok") : (c.error_code ?? c.status)}</StatusBadge></TableCell>
            <TableCell className="text-end tabular-nums">{t("ms", { value: c.latency_ms })}</TableCell>
          </TableRow>
        ))}
      </TableBody>
    </Table>
  );
}
