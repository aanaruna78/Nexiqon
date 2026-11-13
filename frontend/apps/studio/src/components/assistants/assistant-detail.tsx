"use client";

import { ArrowLeft, Bot, Save } from "lucide-react";
import Link from "next/link";
import { useRouter, useSearchParams } from "next/navigation";
import { useTranslations } from "next-intl";
import { useState } from "react";
import { toast } from "sonner";

import { GraphView } from "@/components/graph/graph-view";
import { ProfileSelect } from "@/components/knowledge/profile-select";
import { PageHeader } from "@/components/page-header";
import { VersionsPanel } from "@/components/release/versions-panel";
import { Alert, AlertDescription, AlertTitle } from "@/components/ui/alert";
import { Button } from "@/components/ui/button";
import { Checkbox } from "@/components/ui/checkbox";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import { Select, SelectContent, SelectItem, SelectTrigger, SelectValue } from "@/components/ui/select";
import { Skeleton } from "@/components/ui/skeleton";
import { Switch } from "@/components/ui/switch";
import { Tabs, TabsContent, TabsList, TabsTrigger } from "@/components/ui/tabs";
import { Textarea } from "@/components/ui/textarea";
import { StatusBadge } from "@/components/visual/status-badge";
import { ApiError } from "@/lib/api";
import { useErrorToast } from "@/lib/hooks";
import { useCollections } from "@/lib/knowledge-hooks";
import { type AgentSpec, type ConfigObject, type Graph, releaseState, riskTone, type ToolSpec } from "@/lib/studio";
import { useObject, useObjects, useRelease, useResolvedAgent, useVersion } from "@/lib/studio-hooks";

import { TagInput } from "./tag-input";
import { TestChat } from "./test-chat";
import { ViewAs } from "./view-as";

const TABS = ["setup", "test", "access", "versions", "workflow"] as const;
const TONES = ["friendly", "formal", "concise"] as const;

export function AssistantDetail({ name }: { name: string }) {
  const t = useTranslations("assistants");
  const params = useSearchParams();
  const router = useRouter();
  const object = useObject("agent", name);
  const latest = object.data?.versions.at(-1)?.version;
  const version = useVersion("agent", name, latest);
  const tab = (TABS as readonly string[]).includes(params.get("tab") ?? "") ? (params.get("tab") as (typeof TABS)[number]) : "setup";

  if (object.isLoading || version.isLoading) return <Skeleton className="h-96" />;
  if (!object.data || !version.data) {
    return <Alert variant="destructive"><AlertTitle>{t("notFound")}</AlertTitle></Alert>;
  }
  const spec = version.data.spec as AgentSpec;
  const state = releaseState(object.data);
  return (
    <div className="space-y-6">
      <Button asChild variant="ghost" size="sm" className="-ms-2">
        <Link href="/assistants"><ArrowLeft className="size-4 rtl:rotate-180" aria-hidden="true" />{t("all")}</Link>
      </Button>
      <PageHeader
        title={spec.display_name}
        description={spec.description || t("detailSubtitle", { pack: spec.pack.name })}
        icon={Bot}
        tone="violet"
        actions={
          <div className="flex items-center gap-2">
            {state.live ? <StatusBadge tone="teal" live>{t("liveVersion", { version: state.live })}</StatusBadge> : <StatusBadge tone="amber">{t("notLive")}</StatusBadge>}
            {state.draft ? <StatusBadge tone="amber">{t("draftWaiting", { version: state.draft.version })}</StatusBadge> : null}
          </div>
        }
      />
      <Tabs value={tab} onValueChange={(v) => router.replace(`/assistants/${name}?tab=${v}`)}>
        <TabsList className="flex-wrap">
          {TABS.map((k) => (
            <TabsTrigger key={k} value={k} data-testid={`tab-${k}`}>{t(`tabs.${k}`)}</TabsTrigger>
          ))}
        </TabsList>
        <TabsContent value="setup" className="pt-4">
          <SetupForm key={`${latest}-${version.dataUpdatedAt}`} object={object.data} spec={spec} onSaved={() => router.replace(`/assistants/${name}?tab=versions`)} />
        </TabsContent>
        <TabsContent value="test" className="pt-4">
          <TestChat agent={name} liveVersion={state.live} />
        </TabsContent>
        <TabsContent value="access" className="pt-4">
          <ViewAs collections={spec.knowledge?.collections ?? []} retrievalProfile={spec.retrieval_profile} modelProfile={spec.model_profile} />
        </TabsContent>
        <TabsContent value="versions" className="pt-4">
          <VersionsPanel kind="agent" object={object.data} />
        </TabsContent>
        <TabsContent value="workflow" className="pt-4">
          <Workflow name={name} pack={spec.pack.name} />
        </TabsContent>
      </Tabs>
    </div>
  );
}

function Workflow({ name, pack }: { name: string; pack: string }) {
  const t = useTranslations("assistants");
  const resolved = useResolvedAgent(name);
  if (resolved.isLoading) return <Skeleton className="h-64" />;
  if (!resolved.data) return <p className="text-sm text-muted-foreground">{t("workflowNotLive")}</p>;
  return (
    <div className="space-y-3">
      <p className="text-sm text-muted-foreground">{t("workflowHelp")}</p>
      <GraphView graph={resolved.data.graph as Graph} />
      <Button asChild variant="outline" size="sm">
        <Link href={`/domain-packs/${pack}?tab=workflow`}>{t("editInPack")}</Link>
      </Button>
    </div>
  );
}

function SetupForm({ object, spec: initial, onSaved }: { object: ConfigObject; spec: AgentSpec; onSaved: () => void }) {
  const t = useTranslations("assistants");
  const onError = useErrorToast();
  const collections = useCollections();
  const tools = useObjects("tool");
  const { saveDraft } = useRelease("agent", object.name);
  const [spec, setSpec] = useState<AgentSpec>(initial);
  const [problems, setProblems] = useState<string[]>([]);
  const set = (patch: Partial<AgentSpec>) => setSpec((s) => ({ ...s, ...patch }));
  const behaviour = spec.behaviour ?? {};
  const escalation = (spec.escalation ?? {}) as { after_failed_turns?: number; handoff_tool?: string; on_low_evidence?: boolean };
  const guardrails = (spec.guardrails ?? {}) as { blocked_topics?: string[]; min_evidence_score?: number };
  const chosen = spec.knowledge?.collections ?? [];
  const allowed = spec.tools ?? [];
  const dirty = JSON.stringify(spec) !== JSON.stringify(initial);

  async function save() {
    setProblems([]);
    try {
      const v = await saveDraft.mutateAsync(clean(spec));
      toast.success(t("draftSaved", { version: v.version }));
      onSaved();
    } catch (error) {
      if (error instanceof ApiError && error.problem.code === "config_invalid") {
        setProblems((error.problem.errors ?? []).map((e) => `${e.path ?? ""} ${e.message ?? ""}`.trim()));
      } else onError(error);
    }
  }

  return (
    <form
      className="grid gap-6 lg:grid-cols-2"
      onSubmit={(e) => {
        e.preventDefault();
        void save();
      }}
    >
      <section className="nx-card space-y-4 p-4" aria-labelledby="s-identity">
        <h2 id="s-identity" className="font-semibold">{t("sections.identity")}</h2>
        <div className="space-y-2">
          <Label htmlFor="a-display">{t("displayName")}</Label>
          <Input id="a-display" value={spec.display_name} onChange={(e) => set({ display_name: e.target.value })} minLength={2} maxLength={80} required />
        </div>
        <div className="space-y-2">
          <Label htmlFor="a-desc">{t("description")}</Label>
          <Textarea id="a-desc" rows={2} value={spec.description ?? ""} onChange={(e) => set({ description: e.target.value })} maxLength={500} />
        </div>
        <div className="grid gap-4 sm:grid-cols-2">
          <div className="space-y-2">
            <Label htmlFor="a-product">{t("productName")}</Label>
            <Input id="a-product" value={String(behaviour.product_name ?? "")} onChange={(e) => set({ behaviour: { ...behaviour, product_name: e.target.value } })} />
          </div>
          <div className="space-y-2">
            <Label htmlFor="a-tone">{t("tone")}</Label>
            <Select value={String(behaviour.tone ?? "friendly")} onValueChange={(v) => set({ behaviour: { ...behaviour, tone: v } })}>
              <SelectTrigger id="a-tone" className="w-full"><SelectValue /></SelectTrigger>
              <SelectContent>
                {TONES.map((x) => <SelectItem key={x} value={x}>{t(`tones.${x}`)}</SelectItem>)}
              </SelectContent>
            </Select>
          </div>
        </div>
      </section>

      <section className="nx-card space-y-4 p-4" aria-labelledby="s-knowledge">
        <h2 id="s-knowledge" className="font-semibold">{t("sections.knowledge")}</h2>
        <fieldset className="space-y-2">
          <legend className="text-sm font-medium">{t("knowledge")}</legend>
          {(collections.data ?? []).map((c) => (
            <div key={c.id} className="flex items-center gap-2">
              <Checkbox id={`k-${c.id}`} checked={chosen.includes(c.name)} onCheckedChange={(on) => set({ knowledge: { collections: on ? [...chosen, c.name] : chosen.filter((x) => x !== c.name) } })} />
              <Label htmlFor={`k-${c.id}`} className="font-normal">{c.name}</Label>
            </div>
          ))}
          {!collections.data?.length ? <p className="text-sm text-muted-foreground">{t("noCollections")}</p> : null}
        </fieldset>
        <div className="grid gap-4 sm:grid-cols-2">
          <div className="space-y-2">
            <Label htmlFor="a-model">{t("modelProfile")}</Label>
            <ProfileSelect kind="model_profile" id="a-model" value={spec.model_profile ?? "cloud-frontier"} onChange={(v) => set({ model_profile: v })} />
          </div>
          <div className="space-y-2">
            <Label htmlFor="a-retrieval">{t("retrievalProfile")}</Label>
            <ProfileSelect kind="retrieval_profile" id="a-retrieval" value={spec.retrieval_profile ?? "standard"} onChange={(v) => set({ retrieval_profile: v })} />
          </div>
        </div>
      </section>

      <section className="nx-card space-y-4 p-4" aria-labelledby="s-actions">
        <h2 id="s-actions" className="font-semibold">{t("sections.actions")}</h2>
        <p className="text-sm text-muted-foreground">{t("allowlistHelp")}</p>
        <ul className="space-y-2" data-testid="allowlist">
          {(tools.data ?? []).map((tool) => (
            <ToolChoice key={tool.name} tool={tool} checked={allowed.includes(tool.name)} onChange={(on) => set({ tools: on ? [...allowed, tool.name] : allowed.filter((x) => x !== tool.name) })} />
          ))}
          {!tools.data?.length ? <li className="text-sm text-muted-foreground">{t("noTools")} <Link className="underline" href="/actions">{t("goToActions")}</Link></li> : null}
        </ul>
      </section>

      <section className="nx-card space-y-4 p-4" aria-labelledby="s-safety">
        <h2 id="s-safety" className="font-semibold">{t("sections.safety")}</h2>
        <div className="space-y-2">
          <Label htmlFor="a-blocked">{t("blockedTopics")}</Label>
          <TagInput id="a-blocked" values={guardrails.blocked_topics ?? []} onChange={(v) => set({ guardrails: { ...guardrails, blocked_topics: v } })} placeholder={t("blockedPlaceholder")} />
          <p className="text-xs text-muted-foreground">{t("blockedHelp")}</p>
        </div>
        <div className="grid gap-4 sm:grid-cols-2">
          <div className="space-y-2">
            <Label htmlFor="a-turns">{t("afterFailedTurns")}</Label>
            <Input id="a-turns" type="number" min={1} max={10} value={escalation.after_failed_turns ?? ""} placeholder={t("fromPack")} onChange={(e) => set({ escalation: { ...escalation, after_failed_turns: e.target.value ? Number(e.target.value) : undefined } })} />
          </div>
          <div className="space-y-2">
            <Label htmlFor="a-evidence">{t("minEvidence")}</Label>
            <Input id="a-evidence" type="number" min={0} max={1} step={0.05} value={guardrails.min_evidence_score ?? ""} placeholder={t("fromPack")} onChange={(e) => set({ guardrails: { ...guardrails, min_evidence_score: e.target.value ? Number(e.target.value) : undefined } })} />
          </div>
        </div>
        <div className="flex items-center justify-between gap-3">
          <Label htmlFor="a-low" className="font-normal">{t("escalateLowEvidence")}</Label>
          <Switch id="a-low" checked={escalation.on_low_evidence !== false} onCheckedChange={(on) => set({ escalation: { ...escalation, on_low_evidence: on } })} />
        </div>
        <div className="space-y-2">
          <Label htmlFor="a-handoff">{t("handoffTool")}</Label>
          <Select value={escalation.handoff_tool ?? "__pack"} onValueChange={(v) => set({ escalation: { ...escalation, handoff_tool: v === "__pack" ? undefined : v } })}>
            <SelectTrigger id="a-handoff" className="w-full"><SelectValue /></SelectTrigger>
            <SelectContent>
              <SelectItem value="__pack">{t("fromPack")}</SelectItem>
              {(tools.data ?? []).map((tool) => <SelectItem key={tool.name} value={tool.name}>{tool.name}</SelectItem>)}
            </SelectContent>
          </Select>
        </div>
      </section>

      {problems.length ? (
        <Alert variant="destructive" className="lg:col-span-2">
          <AlertTitle>{t("invalid")}</AlertTitle>
          <AlertDescription><ul>{problems.map((p, i) => <li key={i}>{p}</li>)}</ul></AlertDescription>
        </Alert>
      ) : null}
      <div className="flex justify-end gap-2 lg:col-span-2">
        <Button type="button" variant="outline" disabled={!dirty} onClick={() => setSpec(initial)}>{t("discard")}</Button>
        <Button type="submit" disabled={!dirty || saveDraft.isPending} data-testid="save-assistant">
          <Save className="size-4" aria-hidden="true" />
          {t("saveDraft")}
        </Button>
      </div>
    </form>
  );
}

function ToolChoice({ tool, checked, onChange }: { tool: ConfigObject; checked: boolean; onChange: (on: boolean) => void }) {
  const t = useTranslations("actions");
  const v = tool.deployments.dev ?? tool.versions.at(-1)?.version;
  const detail = useVersion("tool", tool.name, v);
  const spec = detail.data?.spec as ToolSpec | undefined;
  return (
    <li className="flex items-start gap-2">
      <Checkbox id={`tool-${tool.name}`} checked={checked} onCheckedChange={(on) => onChange(!!on)} className="mt-0.5" />
      <Label htmlFor={`tool-${tool.name}`} className="flex flex-1 flex-col items-start gap-0.5 font-normal">
        <span className="flex items-center gap-2">
          <span className="font-medium">{tool.name}</span>
          {spec?.risk_level ? <StatusBadge tone={riskTone(spec.risk_level)}>{t(`risk.${spec.risk_level}`)}</StatusBadge> : null}
        </span>
        {spec?.description ? <span className="text-xs text-muted-foreground">{spec.description}</span> : null}
      </Label>
    </li>
  );
}

/** Drop empty optional sections so the stored spec stays minimal (and inherits from the pack). */
function clean(spec: AgentSpec): AgentSpec {
  const out: AgentSpec = { ...spec };
  for (const key of ["escalation", "guardrails", "behaviour"] as const) {
    const section = Object.fromEntries(Object.entries((out[key] as Record<string, unknown>) ?? {}).filter(([, v]) => v !== undefined && v !== "" && !(Array.isArray(v) && !v.length)));
    if (Object.keys(section).length) (out as Record<string, unknown>)[key] = section;
    else delete (out as Record<string, unknown>)[key];
  }
  if (!out.description) delete out.description;
  return out;
}
