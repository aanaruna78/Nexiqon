"use client";

import { useMutation, useQueryClient } from "@tanstack/react-query";
import { Check, Copy, KeyRound, Save, Trash2 } from "lucide-react";
import { useTranslations } from "next-intl";
import { type FormEvent, useState } from "react";
import { toast } from "sonner";

import { Alert, AlertDescription, AlertTitle } from "@/components/ui/alert";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import { Textarea } from "@/components/ui/textarea";
import { StatusBadge } from "@/components/visual/status-badge";
import { api } from "@/lib/api";
import { useErrorToast } from "@/lib/hooks";
import { type AgentSpec, embedSnippet, keysFor, type Localised, validOrigin, type WidgetKey } from "@/lib/studio";
import { useApiKeys, usePublicConfig, useRelease } from "@/lib/studio-hooks";
import { accessibleAccent } from "@/lib/theme";

import { TagInput } from "./tag-input";

interface WidgetSpec {
  title?: Localised;
  greeting?: Localised;
  starter_questions?: Record<string, string[]>;
  accent_color?: string;
}

/** Widget settings (ST-15): this assistant's text and colour, keys for its websites, and the snippet. */
export function WidgetSettings({ name, spec, pack, onSaved }: { name: string; spec: AgentSpec; pack: WidgetSpec; onSaved: () => void }) {
  return (
    <div className="space-y-8">
      <Appearance name={name} spec={spec} pack={pack} onSaved={onSaved} />
      <WidgetKeys agent={name} />
    </div>
  );
}

function Appearance({ name, spec, pack, onSaved }: { name: string; spec: AgentSpec; pack: WidgetSpec; onSaved: () => void }) {
  const t = useTranslations("widgetSettings");
  const onError = useErrorToast();
  const { saveDraft } = useRelease("agent", name);
  const initial = (spec.widget ?? {}) as WidgetSpec;
  const [w, setW] = useState<WidgetSpec>(initial);
  const locale = "en";
  const text = (v?: Localised) => v?.[locale] ?? "";
  const title = text(w.title) || text(pack.title) || spec.display_name;
  const greeting = text(w.greeting) || text(pack.greeting);
  const starters = w.starter_questions?.[locale] ?? pack.starter_questions?.[locale] ?? [];
  const colour = w.accent_color ?? pack.accent_color ?? "#0E8A7E";
  const shown = accessibleAccent(colour) ?? colour;
  const dirty = JSON.stringify(w) !== JSON.stringify(initial);

  async function save(e: FormEvent) {
    e.preventDefault();
    const clean = Object.fromEntries(Object.entries(w).filter(([, v]) => v !== undefined && !(typeof v === "object" && !Object.keys(v).length)));
    try {
      const v = await saveDraft.mutateAsync({ ...spec, widget: Object.keys(clean).length ? clean : undefined });
      toast.success(t("saved", { version: v.version }));
      onSaved();
    } catch (error) {
      onError(error);
    }
  }

  const set = (key: "title" | "greeting", value: string) =>
    setW((cur) => ({ ...cur, [key]: value ? { ...(cur[key] ?? {}), [locale]: value } : undefined }));

  return (
    <section aria-labelledby="w-look" className="grid gap-6 lg:grid-cols-[1fr_20rem]">
      <form onSubmit={save} className="nx-card space-y-4 p-4">
        <h2 id="w-look" className="font-semibold">{t("appearance")}</h2>
        <p className="text-sm text-muted-foreground">{t("appearanceHelp")}</p>
        <div className="space-y-2">
          <Label htmlFor="ws-title">{t("title")}</Label>
          <Input id="ws-title" value={text(w.title)} placeholder={text(pack.title) || spec.display_name} onChange={(e) => set("title", e.target.value)} />
        </div>
        <div className="space-y-2">
          <Label htmlFor="ws-greeting">{t("greeting")}</Label>
          <Textarea id="ws-greeting" rows={2} value={text(w.greeting)} placeholder={text(pack.greeting)} onChange={(e) => set("greeting", e.target.value)} />
        </div>
        <div className="space-y-2">
          <Label htmlFor="ws-starters">{t("starters")}</Label>
          <TagInput id="ws-starters" values={w.starter_questions?.[locale] ?? []} onChange={(v) => setW((cur) => ({ ...cur, starter_questions: v.length ? { ...(cur.starter_questions ?? {}), [locale]: v.slice(0, 6) } : undefined }))} placeholder={(pack.starter_questions?.[locale] ?? []).join(" · ")} />
        </div>
        <div className="space-y-2">
          <Label htmlFor="ws-colour">{t("colour")}</Label>
          <div className="flex items-center gap-2">
            <input id="ws-colour" type="color" value={colour} onChange={(e) => setW((cur) => ({ ...cur, accent_color: e.target.value.toUpperCase() }))} className="h-9 w-14 cursor-pointer rounded-md border bg-transparent" />
            <span className="font-mono text-sm" dir="ltr">{colour}</span>
          </div>
        </div>
        <div className="flex justify-end gap-2">
          <Button type="button" variant="outline" disabled={!dirty} onClick={() => setW(initial)}>{t("discard")}</Button>
          <Button type="submit" disabled={!dirty || saveDraft.isPending} data-testid="save-widget">
            <Save className="size-4" aria-hidden="true" />
            {t("saveDraft")}
          </Button>
        </div>
      </form>
      <aside aria-label={t("preview")} className="space-y-2">
        <p className="text-sm font-medium">{t("preview")}</p>
        <div className="overflow-hidden rounded-2xl border shadow-sm" data-testid="widget-preview">
          <div className="px-4 py-3 font-semibold text-white" style={{ background: shown }}>{title}</div>
          <div className="space-y-2 bg-card p-4 text-sm">
            {greeting ? <p className="w-fit max-w-[85%] rounded-xl bg-muted px-3 py-2">{greeting}</p> : null}
            <div className="flex flex-wrap gap-1.5">
              {starters.map((q) => <span key={q} className="rounded-full border px-2.5 py-1 text-xs" style={{ borderColor: shown }}>{q}</span>)}
            </div>
          </div>
        </div>
      </aside>
    </section>
  );
}

/** Keys that let websites show this assistant, and the snippet to paste (also used by the setup guide). */
export function WidgetKeys({ agent }: { agent: string }) {
  const t = useTranslations("widgetSettings");
  const client = useQueryClient();
  const onError = useErrorToast();
  const keys = useApiKeys();
  const config = usePublicConfig();
  const [origins, setOrigins] = useState<string[]>([]);
  const [fresh, setFresh] = useState<{ key: WidgetKey; secret: string } | null>(null);
  const [copied, setCopied] = useState(false);
  const mine = keysFor(keys.data ?? [], agent);
  const badOrigin = origins.find((o) => !validOrigin(o));

  const create = useMutation({
    mutationFn: () =>
      api<WidgetKey & { secret: string }>("identity/v1/api-keys", {
        method: "POST",
        json: { name: `${agent} widget`, kind: "widget", allowed_origins: origins, agent_ids: [agent] },
      }),
    onSuccess: async (k) => {
      setFresh({ key: k, secret: k.secret });
      setOrigins([]);
      await client.invalidateQueries({ queryKey: ["api-keys"] });
    },
    onError,
  });
  const revoke = useMutation({
    mutationFn: (id: string) => api(`identity/v1/api-keys/${id}`, { method: "DELETE" }),
    onSuccess: () => client.invalidateQueries({ queryKey: ["api-keys"] }),
    onError,
  });

  const snippet = config.data
    ? embedSnippet({ widgetUrl: config.data.widgetUrl, gatewayUrl: config.data.gatewayUrl, agent, key: fresh?.secret ?? t("keyPlaceholder") })
    : "";

  async function copy() {
    await navigator.clipboard.writeText(snippet);
    setCopied(true);
    setTimeout(() => setCopied(false), 2000);
  }

  return (
    <section aria-labelledby="w-embed" className="grid gap-6 lg:grid-cols-2">
      <div className="nx-card space-y-4 p-4">
        <h2 id="w-embed" className="flex items-center gap-2 font-semibold">
          <KeyRound className="size-4" aria-hidden="true" />
          {t("websites")}
        </h2>
        <p className="text-sm text-muted-foreground">{t("websitesHelp")}</p>
        <form
          className="space-y-2"
          onSubmit={(e) => {
            e.preventDefault();
            if (origins.length && !badOrigin) create.mutate();
          }}
        >
          <Label htmlFor="ws-origins">{t("origins")}</Label>
          <TagInput id="ws-origins" values={origins} onChange={setOrigins} placeholder="https://docs.example.com" />
          {badOrigin ? <p className="text-xs text-destructive" role="alert">{t("badOrigin", { origin: badOrigin })}</p> : null}
          <Button type="submit" disabled={!origins.length || !!badOrigin || create.isPending} data-testid="create-widget-key">{t("createKey")}</Button>
        </form>
        <ul className="divide-y" data-testid="widget-keys">
          {mine.map((k) => (
            <li key={k.id} className="flex flex-wrap items-center justify-between gap-2 py-2 text-sm">
              <span className="flex flex-col">
                <span className="font-mono text-xs" dir="ltr">{k.prefix}…</span>
                <span className="text-xs text-muted-foreground" dir="ltr">{k.allowed_origins.join(", ")}</span>
              </span>
              <span className="flex items-center gap-2">
                {k.last_used_at ? <StatusBadge tone="teal">{t("inUse")}</StatusBadge> : <StatusBadge tone="slate">{t("unused")}</StatusBadge>}
                <Button variant="ghost" size="icon" aria-label={t("revoke", { prefix: k.prefix })} onClick={() => revoke.mutate(k.id)}>
                  <Trash2 className="size-4" aria-hidden="true" />
                </Button>
              </span>
            </li>
          ))}
          {!mine.length ? <li className="py-2 text-sm text-muted-foreground">{t("noKeys")}</li> : null}
        </ul>
      </div>
      <div className="nx-card space-y-3 p-4">
        <h2 className="font-semibold">{t("snippet")}</h2>
        {fresh ? (
          <Alert>
            <AlertTitle>{t("secretOnce")}</AlertTitle>
            <AlertDescription>{t("secretOnceBody")}</AlertDescription>
          </Alert>
        ) : (
          <p className="text-sm text-muted-foreground">{t("snippetHelp")}</p>
        )}
        <pre tabIndex={0} aria-label={t("snippet")} className="overflow-x-auto rounded-xl border bg-muted/40 p-3 text-xs focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring" dir="ltr" data-testid="embed-snippet">{snippet}</pre>
        <Button variant="outline" onClick={copy} disabled={!snippet} data-testid="copy-snippet">
          {copied ? <Check className="size-4" aria-hidden="true" /> : <Copy className="size-4" aria-hidden="true" />}
          {copied ? t("copied") : t("copy")}
        </Button>
      </div>
    </section>
  );
}
