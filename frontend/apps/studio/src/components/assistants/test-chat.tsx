"use client";

import { MessageSquarePlus, ScanSearch, Send, UserRound } from "lucide-react";
import { useLocale, useTranslations } from "next-intl";
import { type FormEvent, type KeyboardEvent, useRef, useState } from "react";

import { AnswerInspector } from "@/components/inspector/answer-inspector";
import { Button } from "@/components/ui/button";
import { Textarea } from "@/components/ui/textarea";
import { StatusBadge } from "@/components/visual/status-badge";
import { api, ApiError } from "@/lib/api";
import { useErrorToast } from "@/lib/hooks";
import { readSSE } from "@/lib/studio";
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

/** Talk to the assistant as it is live in dev; every reply opens in the Answer Inspector. */
export function TestChat({ agent, liveVersion }: { agent: string; liveVersion: number | null }) {
  const t = useTranslations("testChat");
  const locale = useLocale();
  const onError = useErrorToast();
  const [conversation, setConversation] = useState<{ id: string; status: string } | null>(null);
  const [messages, setMessages] = useState<Message[]>([]);
  const [text, setText] = useState("");
  const [busy, setBusy] = useState(false);
  const [stage, setStage] = useState("");
  const [inspect, setInspect] = useState<string | null>(null);
  const log = useRef<HTMLOListElement>(null);

  const scroll = () => requestAnimationFrame(() => log.current?.lastElementChild?.scrollIntoView({ block: "nearest" }));

  async function ensure(): Promise<string> {
    if (conversation) return conversation.id;
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
      const id = await ensure();
      const response = await fetch(`/api/nx/conversation/v1/conversations/${id}/messages/stream`, {
        method: "POST",
        headers: { "content-type": "application/json", accept: "text/event-stream", "x-nexiqon-csrf": "1" },
        body: JSON.stringify({ content }),
        credentials: "same-origin",
      });
      if (!response.ok || !response.body) throw new ApiError(response.status, await response.json().catch(() => ({})));
      for await (const ev of readSSE(response.body)) {
        if (ev.event === "status") setStage(t(`stages.${String(ev.data.stage)}`));
        else if (ev.event === "tool" && ev.data.status === "running") setStage(t("stages.tool", { name: String(ev.data.name) }));
        else if (ev.event === "delta") {
          setMessages((m) => m.map((x) => (x.streaming ? { ...x, content: x.content + String(ev.data.text ?? "") } : x)));
        } else if (ev.event === "message") finish(ev.data as unknown as Turn);
        else if (ev.event === "error") throw new ApiError(502, { title: String(ev.data.detail ?? "") });
      }
    } catch (error) {
      setMessages((m) => m.filter((x) => !x.streaming));
      onError(error);
    } finally {
      setBusy(false);
      setStage("");
    }
  }

  async function decide(approved: boolean) {
    if (!conversation) return;
    setBusy(true);
    try {
      finish(await api<Turn>(`conversation/v1/conversations/${conversation.id}/approval`, { method: "POST", json: { approved } }));
    } catch (error) {
      onError(error);
    } finally {
      setBusy(false);
    }
  }

  async function handoff() {
    setBusy(true);
    try {
      const id = await ensure();
      setMessages((m) => [...m, { role: "user", content: t("askForPerson") }]);
      finish(await api<Turn>(`conversation/v1/conversations/${id}/handoff`, { method: "POST" }));
    } catch (error) {
      onError(error);
    } finally {
      setBusy(false);
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
  return (
    <div className="nx-card flex h-[34rem] flex-col">
      <div className="flex flex-wrap items-center justify-between gap-2 border-b p-3">
        <p className="text-sm text-muted-foreground">
          {liveVersion ? t("testing", { version: liveVersion }) : t("notLive")}
        </p>
        <div className="flex gap-2">
          <Button variant="outline" size="sm" onClick={handoff} disabled={busy || escalated || awaiting || !liveVersion}>
            <UserRound className="size-4" aria-hidden="true" />
            {t("askForPerson")}
          </Button>
          <Button variant="outline" size="sm" onClick={() => { setConversation(null); setMessages([]); }} disabled={busy}>
            <MessageSquarePlus className="size-4" aria-hidden="true" />
            {t("restart")}
          </Button>
        </div>
      </div>
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
          <Button onClick={() => decide(true)} disabled={busy}>{t("approve")}</Button>
          <Button variant="outline" onClick={() => decide(false)} disabled={busy}>{t("decline")}</Button>
        </div>
      ) : null}
      {escalated ? <p className="border-t p-3 text-sm text-muted-foreground">{t("escalated")}</p> : null}
      <form onSubmit={send} className="flex items-end gap-2 border-t p-3">
        <div className="flex-1 space-y-1">
          <label htmlFor="test-input" className="sr-only">{t("placeholder")}</label>
          <Textarea id="test-input" rows={2} value={text} onChange={(e) => setText(e.target.value)} onKeyDown={onKey} placeholder={t("placeholder")} disabled={awaiting || !liveVersion} data-testid="test-input" />
          <p className="min-h-4 text-xs text-muted-foreground" aria-live="polite">{stage}</p>
        </div>
        <Button type="submit" disabled={busy || !text.trim() || awaiting || !liveVersion} data-testid="test-send">
          <Send className="size-4" aria-hidden="true" />
          {t("send")}
        </Button>
      </form>
      <AnswerInspector runId={inspect} onClose={() => setInspect(null)} />
    </div>
  );
}
