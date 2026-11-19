"use client";

import { MessageSquarePlus, ScanSearch, Send, UserRound } from "lucide-react";
import { useLocale, useTranslations } from "next-intl";
import { type FormEvent, type KeyboardEvent, useRef, useState } from "react";

import { AnswerInspector } from "@/components/inspector/answer-inspector";
import { Button } from "@/components/ui/button";
import { Label } from "@/components/ui/label";
import { Select, SelectContent, SelectItem, SelectTrigger, SelectValue } from "@/components/ui/select";
import { Textarea } from "@/components/ui/textarea";
import { StatusBadge } from "@/components/visual/status-badge";
import { api, ApiError } from "@/lib/api";
import { useErrorToast } from "@/lib/hooks";
import { readSSE, type StreamEvent, type VersionInfo } from "@/lib/studio";
import { cn } from "@/lib/utils";

const KINDS = ["grounded", "smalltalk", "declined", "unavailable", "blocked", "withheld", "handoff", "clarify", "approval", "error"];

interface Message {
  role: "user" | "assistant";
  content: string;
  contract?: { kind?: string; citations?: { marker: string; citation: string }[]; interrupt?: { purpose?: string } };
  run_id?: string | null;
  streaming?: boolean;
}

interface Turn {
  conversation: { id: string; status: string };
  reply: (Message & { run_id: string | null }) | null;
}

/** agent-runtime's RunOut, for versions tried before release. */
interface RunResult {
  run_id: string;
  status: string;
  answer: { text?: string; kind?: string; citations?: { marker: string; citation: string }[] } | null;
  interrupt: { kind?: string; purpose?: string; prompt?: string } | null;
  handoff: Record<string, unknown> | null;
  error: string | null;
}

/** A RunOut as the stored turn the conversation service would have returned. */
export function turnFromRun(r: RunResult, thread: string): Turn {
  const status = r.status === "interrupted" ? (r.interrupt?.kind === "approval" ? "awaiting_approval" : "awaiting_input") : r.handoff ? "escalated" : "active";
  const content = r.status === "completed" ? (r.answer?.text ?? "") : r.status === "interrupted" ? (r.interrupt?.prompt ?? "") : (r.error ?? "");
  const kind = r.status === "completed" ? r.answer?.kind : r.status === "interrupted" ? r.interrupt?.kind : "error";
  return {
    conversation: { id: thread, status },
    reply: { role: "assistant", content, run_id: r.run_id, contract: { kind, citations: r.answer?.citations ?? [], interrupt: r.interrupt ?? undefined } },
  };
}

async function post(url: string, body: unknown): Promise<Response> {
  const response = await fetch(url, {
    method: "POST",
    headers: { "content-type": "application/json", accept: "text/event-stream", "x-nexiqon-csrf": "1" },
    body: JSON.stringify(body),
    credentials: "same-origin",
  });
  if (!response.ok || !response.body) throw new ApiError(response.status, await response.json().catch(() => ({})));
  return response;
}

/**
 * Talk to the assistant. The live version runs through conversations, as users would; any other
 * version (a draft, or an older one) runs directly and is not stored as a conversation.
 * Every reply opens in the Answer Inspector.
 */
export function TestChat({ agent, liveVersion, versions }: { agent: string; liveVersion: number | null; versions: VersionInfo[] }) {
  const t = useTranslations("testChat");
  const locale = useLocale();
  const onError = useErrorToast();
  const newest = versions.at(-1)?.version ?? null;
  const [version, setVersion] = useState<number | null>(liveVersion ?? newest);
  const [conversation, setConversation] = useState<{ id: string; status: string } | null>(null);
  const [messages, setMessages] = useState<Message[]>([]);
  const [text, setText] = useState("");
  const [busy, setBusy] = useState(false);
  const [stage, setStage] = useState("");
  const [inspect, setInspect] = useState<string | null>(null);
  const log = useRef<HTMLOListElement>(null);
  const preview = version !== null && version !== liveVersion;

  const scroll = () => requestAnimationFrame(() => log.current?.lastElementChild?.scrollIntoView({ block: "nearest" }));
  const history = () => messages.filter((m) => !m.streaming && m.content).slice(-12).map((m) => ({ role: m.role, content: m.content }));

  async function ensure(): Promise<string> {
    if (conversation) return conversation.id;
    if (preview) {
      const c = { id: `preview-${crypto.randomUUID()}`, status: "active" };
      setConversation(c);
      return c.id;
    }
    const c = await api<{ id: string; status: string }>("conversation/v1/conversations", {
      method: "POST",
      json: { agent, channel: "studio", locale: locale.slice(0, 2) },
    });
    setConversation(c);
    return c.id;
  }

  function finish(turn: Turn) {
    setConversation(turn.conversation);
    setMessages((m) => [...m.filter((x) => !x.streaming), ...(turn.reply ? [turn.reply] : [])]);
    scroll();
  }

  function restart(next = version) {
    setVersion(next);
    setConversation(null);
    setMessages([]);
  }

  /** One turn on the version being tested; resolves with the stored (or equivalent) turn. */
  async function turn(id: string, payload: { input?: string; resume?: unknown; handoff?: boolean }): Promise<Turn> {
    if (!preview && payload.input !== undefined && !payload.handoff) {
      const response = await post(`/api/nx/conversation/v1/conversations/${id}/messages/stream`, { content: payload.input });
      return consume(response, "message", (data) => data as unknown as Turn);
    }
    if (!preview) {
      const path = payload.handoff ? "handoff" : "approval";
      return api<Turn>(`conversation/v1/conversations/${id}/${path}`, { method: "POST", json: payload.handoff ? undefined : payload.resume });
    }
    const response = await post(`/api/nx/agent-runtime/v1/agents/${agent}/runs/stream`, {
      thread_id: id,
      version,
      locale: locale.slice(0, 2),
      history: payload.resume === undefined ? history() : [],
      ...payload,
    });
    return consume(response, "result", (data) => turnFromRun(data as unknown as RunResult, id));
  }

  async function consume(response: Response, final: string, done: (data: StreamEvent["data"]) => Turn): Promise<Turn> {
    for await (const ev of readSSE(response.body!)) {
      if (ev.event === final) return done(ev.data);
      if (ev.event === "status") setStage(t(`stages.${String(ev.data.stage)}`));
      else if (ev.event === "tool" && ev.data.status === "running") setStage(t("stages.tool", { name: String(ev.data.name) }));
      else if (ev.event === "delta") setMessages((m) => m.map((x) => (x.streaming ? { ...x, content: x.content + String(ev.data.text ?? "") } : x)));
      else if (ev.event === "error") throw new ApiError(502, { title: String(ev.data.detail ?? "") });
    }
    throw new ApiError(502, { title: t("streamEnded") });
  }

  async function send(e?: FormEvent) {
    e?.preventDefault();
    const content = text.trim();
    if (!content || busy) return;
    setBusy(true);
    setText("");
    setStage(t("stages.understanding"));
    setMessages((m) => [...m, { role: "user", content }, { role: "assistant", content: "", streaming: true }]);
    scroll();
    try {
      finish(await turn(await ensure(), { input: content }));
    } catch (error) {
      setMessages((m) => m.filter((x) => !x.streaming));
      onError(error);
    } finally {
      setBusy(false);
      setStage("");
    }
  }

  async function act(payload: { resume?: unknown; handoff?: boolean; input?: string }, said?: string) {
    setBusy(true);
    try {
      const id = await ensure();
      if (said) setMessages((m) => [...m, { role: "user", content: said }]);
      finish(await turn(id, payload));
    } catch (error) {
      onError(error);
    } finally {
      setBusy(false);
      setStage("");
    }
  }

  function onKey(e: KeyboardEvent<HTMLTextAreaElement>) {
    if (e.key === "Enter" && !e.shiftKey) {
      e.preventDefault();
      void send();
    }
  }

  const awaiting = conversation?.status === "awaiting_approval";
  const escalated = conversation?.status === "escalated";
  const usable = version !== null;
  return (
    <div className="nx-card flex h-[34rem] flex-col">
      <div className="flex flex-wrap items-center justify-between gap-2 border-b p-3">
        <div className="flex flex-wrap items-center gap-2">
          <Label htmlFor="test-version" className="text-sm text-muted-foreground">{t("version")}</Label>
          <Select value={version ? String(version) : undefined} onValueChange={(v) => restart(Number(v))}>
            <SelectTrigger id="test-version" className="w-52" data-testid="test-version"><SelectValue placeholder={t("notLive")} /></SelectTrigger>
            <SelectContent>
              {[...versions].reverse().map((v) => (
                <SelectItem key={v.version} value={String(v.version)}>
                  {v.version === liveVersion ? t("liveOption", { version: v.version }) : v.status === "draft" ? t("draftOption", { version: v.version }) : t("olderOption", { version: v.version })}
                </SelectItem>
              ))}
            </SelectContent>
          </Select>
          {preview ? <StatusBadge tone="amber">{t("previewBadge")}</StatusBadge> : null}
        </div>
        <div className="flex gap-2">
          <Button variant="outline" size="sm" onClick={() => act({ handoff: true, input: t("askForPerson") }, t("askForPerson"))} disabled={busy || escalated || awaiting || !usable}>
            <UserRound className="size-4" aria-hidden="true" />
            {t("askForPerson")}
          </Button>
          <Button variant="outline" size="sm" onClick={() => restart()} disabled={busy}>
            <MessageSquarePlus className="size-4" aria-hidden="true" />
            {t("restart")}
          </Button>
        </div>
      </div>
      <p className="border-b px-3 py-2 text-xs text-muted-foreground">{preview ? t("previewHelp", { version: version ?? "" }) : liveVersion ? t("testing", { version: liveVersion }) : t("notLive")}</p>
      <ol ref={log} className="flex-1 space-y-3 overflow-y-auto p-4" aria-live="polite" aria-busy={busy} data-testid="test-chat-log">
        {!messages.length ? <li className="text-sm text-muted-foreground">{t("empty")}</li> : null}
        {messages.map((m, i) => (
          <li key={i} className={cn("flex flex-col gap-1", m.role === "user" ? "items-end" : "items-start")}>
            <div className={cn("max-w-[85%] rounded-2xl px-3 py-2 text-sm whitespace-pre-line", m.role === "user" ? "bg-primary text-primary-foreground" : "bg-muted", m.streaming && "after:content-['▍'] after:opacity-60")}>
              {m.content}
            </div>
            {m.role === "assistant" && !m.streaming ? (
              <div className="flex flex-wrap items-center gap-2">
                {m.contract?.kind ? <StatusBadge tone={m.contract.kind === "grounded" ? "teal" : m.contract.kind === "handoff" ? "sky" : "amber"}>{KINDS.includes(m.contract.kind) ? t(`kinds.${m.contract.kind}`) : m.contract.kind}</StatusBadge> : null}
                {m.contract?.citations?.map((c) => (
                  <span key={c.marker} className="rounded-md bg-primary/10 px-1.5 text-xs text-primary" title={c.citation}>[{c.marker}] {c.citation}</span>
                ))}
                {m.run_id ? (
                  <Button variant="ghost" size="sm" onClick={() => setInspect(m.run_id!)} data-testid="inspect">
                    <ScanSearch className="size-4" aria-hidden="true" />
                    {t("inspect")}
                  </Button>
                ) : null}
              </div>
            ) : null}
          </li>
        ))}
      </ol>
      {awaiting ? (
        <div className="flex flex-wrap gap-2 border-t p-3" role="group" aria-label={t("decision")}>
          <Button onClick={() => act({ resume: { approved: true } })} disabled={busy}>{t("approve")}</Button>
          <Button variant="outline" onClick={() => act({ resume: { approved: false } })} disabled={busy}>{t("decline")}</Button>
        </div>
      ) : null}
      {escalated ? <p className="border-t p-3 text-sm text-muted-foreground">{t("escalated")}</p> : null}
      <form onSubmit={send} className="flex items-end gap-2 border-t p-3">
        <div className="flex-1 space-y-1">
          <label htmlFor="test-input" className="sr-only">{t("placeholder")}</label>
          <Textarea id="test-input" rows={2} value={text} onChange={(e) => setText(e.target.value)} onKeyDown={onKey} placeholder={t("placeholder")} disabled={awaiting || !usable} data-testid="test-input" />
          <p className="min-h-4 text-xs text-muted-foreground" aria-live="polite">{stage}</p>
        </div>
        <Button type="submit" disabled={busy || !text.trim() || awaiting || !usable} data-testid="test-send">
          <Send className="size-4" aria-hidden="true" />
          {t("send")}
        </Button>
      </form>
      <AnswerInspector runId={inspect} onClose={() => setInspect(null)} />
    </div>
  );
}
