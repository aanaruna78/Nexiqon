"use client";

import { useQueryClient } from "@tanstack/react-query";
import { ArrowUp, Check, Copy, ExternalLink, ScanSearch, ThumbsDown, ThumbsUp, UserRound } from "lucide-react";
import Link from "next/link";
import { useLocale, useTranslations } from "next-intl";
import { type FormEvent, type KeyboardEvent, useEffect, useMemo, useRef, useState } from "react";
import { toast } from "sonner";

import { AnswerInspector } from "@/components/inspector/answer-inspector";
import { Button } from "@/components/ui/button";
import { Skeleton } from "@/components/ui/skeleton";
import { BrandMark } from "@/components/visual/brand-mark";
import { Hint } from "@/components/visual/hint";
import { api, apiStream, ApiError } from "@/lib/api";
import {
  type AssistantFace,
  assistantLabel,
  type ChatMessage,
  type ConversationDetail,
  lastAssistant,
  MY_CONVERSATIONS,
  rememberAssistant,
  type Turn,
  useLiveAssistants,
} from "@/lib/chat";
import { useErrorToast } from "@/lib/hooks";
import { readSSE } from "@/lib/studio";
import { cn } from "@/lib/utils";

import { AssistantPicker } from "./assistant-picker";

/** Links in answers open only over http(s); anything else is shown as text. */
function safeHref(uri: string | null | undefined): string | null {
  if (!uri) return null;
  try {
    const u = new URL(uri);
    return u.protocol === "https:" || u.protocol === "http:" ? u.href : null;
  } catch {
    return null;
  }
}

/**
 * The assistant chat: the home page. Pick an assistant, ask, and get an answer with its sources.
 * A new chat lives at "/" until its first message; then the address becomes /c/<id> so it can be
 * resumed from the history panel. Admins can open any answer in the Answer Inspector.
 */
export function ChatView({ initial, canAdmin }: { initial?: ConversationDetail; canAdmin: boolean }) {
  const t = useTranslations("chat");
  const locale = useLocale();
  const lang = locale.slice(0, 2);
  const onError = useErrorToast();
  const queryClient = useQueryClient();
  const { assistants, isLoading } = useLiveAssistants(lang);

  const [chosen, setChosen] = useState<string | null>(initial?.agent ?? null);
  const [conversation, setConversation] = useState<{ id: string; status: string } | null>(
    initial ? { id: initial.id, status: initial.status } : null,
  );
  const [messages, setMessages] = useState<ChatMessage[]>(initial?.messages ?? []);
  const [text, setText] = useState("");
  const [busy, setBusy] = useState(false);
  const [stage, setStage] = useState("");
  const [inspect, setInspect] = useState<string | null>(null);
  const [copied, setCopied] = useState<string | null>(null);
  const log = useRef<HTMLDivElement>(null);
  const input = useRef<HTMLTextAreaElement>(null);

  // The assistant: the conversation's, else the one chosen, else the last used, else the first live.
  const agent = useMemo(() => {
    if (chosen) return chosen;
    if (!assistants.length) return null;
    const remembered = lastAssistant();
    return assistants.some((a) => a.agent === remembered) ? remembered : assistants[0].agent;
  }, [chosen, assistants]);

  // Escalated: a person from the team answers here; look for their replies.
  const escalated = conversation?.status === "escalated";
  useEffect(() => {
    if (!escalated || !conversation) return;
    const timer = setInterval(async () => {
      const fresh = await api<{ messages: ChatMessage[] }>(`conversation/v1/conversations/${conversation.id}`).catch(() => null);
      if (fresh) setMessages((m) => (fresh.messages.length > m.filter((x) => !x.streaming).length ? fresh.messages : m));
    }, 8000);
    return () => clearInterval(timer);
  }, [escalated, conversation]);

  useEffect(() => {
    log.current?.scrollTo({ top: log.current.scrollHeight, behavior: "smooth" });
  }, [messages]);

  const face: AssistantFace | undefined = useMemo(() => assistants.find((a) => a.agent === agent), [assistants, agent]);
  const name = agent ? assistantLabel(face, agent) : "";
  const awaiting = conversation?.status === "awaiting_approval";

  async function ensureConversation(): Promise<string> {
    if (conversation) return conversation.id;
    const c = await api<{ id: string; status: string }>("conversation/v1/conversations", {
      method: "POST",
      json: { agent, channel: "studio", locale: lang },
    });
    setConversation(c);
    // The chat now has an address; the history panel can list and resume it.
    window.history.replaceState(null, "", `/c/${c.id}`);
    return c.id;
  }

  function settle(turn: Turn) {
    setConversation(turn.conversation);
    setMessages((m) => [...m.filter((x) => !x.streaming), ...(turn.reply ? [turn.reply] : [])]);
    void queryClient.invalidateQueries({ queryKey: MY_CONVERSATIONS });
  }

  async function send(content: string) {
    const question = content.trim();
    if (!question || busy || !agent) return;
    setBusy(true);
    setText("");
    setStage(t("stages.understanding"));
    setMessages((m) => [...m, { role: "user", content: question }, { role: "assistant", content: "", streaming: true }]);
    rememberAssistant(agent);
    try {
      const id = await ensureConversation();
      const body = await apiStream(`conversation/v1/conversations/${id}/messages/stream`, { content: question });
      let done = false;
      for await (const ev of readSSE(body)) {
        if (ev.event === "status") setStage(t.has(`stages.${String(ev.data.stage)}`) ? t(`stages.${String(ev.data.stage)}`) : t("stages.working"));
        else if (ev.event === "tool" && ev.data.status === "running") setStage(t("stages.tool", { name: String(ev.data.name ?? "") }));
        else if (ev.event === "delta") setMessages((m) => m.map((x) => (x.streaming ? { ...x, content: x.content + String(ev.data.text ?? "") } : x)));
        else if (ev.event === "message") {
          settle(ev.data as unknown as Turn);
          done = true;
        } else if (ev.event === "error") throw new ApiError(502, { title: String(ev.data.detail ?? t("failed")) });
      }
      if (!done) throw new ApiError(502, { title: t("streamEnded") });
    } catch (error) {
      setMessages((m) => m.filter((x) => !x.streaming));
      setText(question);
      onError(error);
    } finally {
      setBusy(false);
      setStage("");
      input.current?.focus();
    }
  }

  async function decide(approved: boolean) {
    if (!conversation) return;
    setBusy(true);
    try {
      settle(await api<Turn>(`conversation/v1/conversations/${conversation.id}/approval`, { method: "POST", json: { approved } }));
    } catch (error) {
      onError(error);
    } finally {
      setBusy(false);
    }
  }

  async function askPerson() {
    if (busy || !agent) return;
    setBusy(true);
    try {
      const id = await ensureConversation();
      settle(await api<Turn>(`conversation/v1/conversations/${id}/handoff`, { method: "POST" }));
    } catch (error) {
      onError(error);
    } finally {
      setBusy(false);
    }
  }

  async function rate(m: ChatMessage, rating: "up" | "down") {
    if (!m.id) return;
    setMessages((all) => all.map((x) => (x.id === m.id ? { ...x, rating } : x)));
    try {
      await api(`conversation/v1/messages/${m.id}/feedback`, { method: "POST", json: { rating } });
      toast.success(t("thanks"));
    } catch (error) {
      onError(error);
    }
  }

  async function copy(m: ChatMessage, key: string) {
    await navigator.clipboard.writeText(m.content);
    setCopied(key);
    setTimeout(() => setCopied(null), 1500);
  }

  function onKeyDown(e: KeyboardEvent<HTMLTextAreaElement>) {
    if (e.key === "Enter" && !e.shiftKey && !e.nativeEvent.isComposing) {
      e.preventDefault();
      void send(text);
    }
  }

  function onSubmit(e: FormEvent) {
    e.preventDefault();
    void send(text);
  }

  if (isLoading) {
    return (
      <div className="mx-auto flex w-full max-w-3xl flex-1 flex-col gap-4 px-4 py-10">
        <Skeleton className="h-8 w-48" />
        <Skeleton className="h-24 w-full" />
        <Skeleton className="h-24 w-3/4" />
      </div>
    );
  }

  if (!assistants.length && !initial) {
    return (
      <div className="mx-auto flex max-w-md flex-1 flex-col items-center justify-center gap-3 px-4 text-center">
        <BrandMark className="size-12" />
        <h1 className="text-xl font-semibold">{t("noAssistantsTitle")}</h1>
        <p className="text-muted-foreground">{canAdmin ? t("noAssistantsAdmin") : t("noAssistantsMember")}</p>
        {canAdmin ? (
          <Button asChild>
            <Link href="/admin/get-started">{t("setUp")}</Link>
          </Button>
        ) : null}
      </div>
    );
  }

  const empty = messages.length === 0;

  return (
    <div className="flex min-h-0 flex-1 flex-col">
      {/* Assistant choice: fixed once a conversation has started. */}
      <div className="flex items-center justify-between gap-3 px-4 pt-3 sm:px-6">
        <AssistantPicker assistants={assistants} value={agent} onChange={setChosen} locked={!empty || Boolean(initial)} />
      </div>

      <div ref={log} className="min-h-0 flex-1 overflow-y-auto" data-testid="chat-log">
        {empty ? (
          <div className="mx-auto flex h-full max-w-3xl flex-col items-center justify-center gap-6 px-4 pb-8 text-center">
            <div className="space-y-3">
              <BrandMark className="mx-auto size-12 drop-shadow-[0_8px_20px_rgba(11,111,102,0.35)]" />
              <h1 className="text-balance text-2xl font-semibold tracking-tight sm:text-3xl">{face?.greeting || t("greeting", { name })}</h1>
              <p className="text-muted-foreground">{t("intro")}</p>
            </div>
            {face?.starter_questions?.length ? (
              <ul className="grid w-full gap-2 sm:grid-cols-2" aria-label={t("starters")}>
                {face.starter_questions.slice(0, 4).map((q) => (
                  <li key={q}>
                    <button
                      type="button"
                      onClick={() => void send(q)}
                      disabled={busy}
                      className="nx-lift h-full w-full rounded-xl border bg-card px-4 py-3 text-start text-sm shadow-sm outline-none focus-visible:ring-2 focus-visible:ring-ring"
                    >
                      {q}
                    </button>
                  </li>
                ))}
              </ul>
            ) : null}
          </div>
        ) : (
          <ol className="mx-auto flex max-w-3xl flex-col gap-6 px-4 py-6 sm:px-6" aria-label={t("conversation")}>
            {messages.map((m, i) => {
              const key = m.id ?? `m-${i}`;
              if (m.role === "user") {
                return (
                  <li key={key} className="flex justify-end">
                    <div className="max-w-[85%] whitespace-pre-line rounded-2xl rounded-ee-md bg-primary px-4 py-2.5 text-[15px] text-primary-foreground">{m.content}</div>
                  </li>
                );
              }
              const citations = m.contract?.citations ?? [];
              return (
                <li key={key} className="flex gap-3">
                  {m.role === "staff" ? (
                    <span className="grid size-8 flex-none place-items-center rounded-full bg-violet-100 text-violet-700 dark:bg-violet-950 dark:text-violet-200" aria-hidden="true">
                      <UserRound className="size-4" />
                    </span>
                  ) : (
                    <BrandMark className="size-8 flex-none" />
                  )}
                  <div className="min-w-0 flex-1 space-y-2 pt-1">
                    <p className="text-xs font-medium text-muted-foreground">{m.role === "staff" ? t("team") : name}</p>
                    {m.streaming && !m.content ? (
                      <p className="flex items-center gap-2 text-sm text-muted-foreground" role="status">
                        <span className="nx-live-dot inline-block size-2 rounded-full bg-primary" aria-hidden="true" />
                        {stage || t("stages.working")}
                      </p>
                    ) : (
                      <div className={cn("whitespace-pre-line text-[15px] leading-relaxed", m.streaming && "after:ms-0.5 after:content-['▍'] after:opacity-60")}>
                        {m.content}
                      </div>
                    )}
                    {citations.length ? (
                      <div className="space-y-1.5" aria-label={t("sources")}>
                        <p className="text-xs font-medium text-muted-foreground">{t("sources")}</p>
                        <ul className="flex flex-wrap gap-2">
                          {citations.map((c) => {
                            const href = safeHref(c.source_uri);
                            const label = (
                              <>
                                <span className="font-semibold text-primary">{c.marker}</span>
                                <span className="truncate">{c.citation}</span>
                                {href ? <ExternalLink className="size-3 flex-none opacity-60" aria-hidden="true" /> : null}
                              </>
                            );
                            const cls = "inline-flex max-w-full items-center gap-1.5 rounded-full border bg-card px-2.5 py-1 text-xs";
                            return (
                              <li key={`${c.marker}-${c.citation}`} className="max-w-full">
                                {href ? (
                                  <a href={href} target="_blank" rel="noopener noreferrer" className={cn(cls, "hover:border-primary/50 hover:bg-muted")}>
                                    {label}
                                  </a>
                                ) : (
                                  <span className={cls}>{label}</span>
                                )}
                              </li>
                            );
                          })}
                        </ul>
                      </div>
                    ) : null}
                    {m.role === "assistant" && !m.streaming && m.content ? (
                      <div className="-ms-2 flex items-center gap-0.5 text-muted-foreground">
                        <Hint label={copied === key ? t("copied") : t("copy")}>
                          <Button variant="ghost" size="icon" className="size-8" aria-label={t("copy")} onClick={() => void copy(m, key)}>
                            {copied === key ? <Check className="size-4" aria-hidden="true" /> : <Copy className="size-4" aria-hidden="true" />}
                          </Button>
                        </Hint>
                        {m.id ? (
                          <>
                            <Hint label={t("helpful")}>
                              <Button variant="ghost" size="icon" className={cn("size-8", m.rating === "up" && "text-primary")} aria-label={t("helpful")} aria-pressed={m.rating === "up"} onClick={() => void rate(m, "up")}>
                                <ThumbsUp className="size-4" aria-hidden="true" />
                              </Button>
                            </Hint>
                            <Hint label={t("notHelpful")}>
                              <Button variant="ghost" size="icon" className={cn("size-8", m.rating === "down" && "text-destructive")} aria-label={t("notHelpful")} aria-pressed={m.rating === "down"} onClick={() => void rate(m, "down")}>
                                <ThumbsDown className="size-4" aria-hidden="true" />
                              </Button>
                            </Hint>
                          </>
                        ) : null}
                        {canAdmin && m.run_id ? (
                          <Hint label={t("inspectHint")}>
                            <Button variant="ghost" size="sm" className="h-8 gap-1.5 text-xs" onClick={() => setInspect(m.run_id!)} data-testid="inspect">
                              <ScanSearch className="size-4" aria-hidden="true" />
                              {t("inspect")}
                            </Button>
                          </Hint>
                        ) : null}
                      </div>
                    ) : null}
                  </div>
                </li>
              );
            })}
          </ol>
        )}
      </div>

      {/* Composer */}
      <div className="px-4 pb-4 pt-2 sm:px-6">
        <div className="mx-auto max-w-3xl space-y-2">
          {awaiting ? (
            <div className="flex flex-wrap items-center justify-between gap-3 rounded-xl border border-amber-300/60 bg-amber-50 px-4 py-3 text-sm dark:border-amber-800 dark:bg-amber-950/40" role="group" aria-label={t("confirmTitle")}>
              <span className="font-medium">{t("confirmTitle")}</span>
              <span className="flex gap-2">
                <Button size="sm" variant="outline" disabled={busy} onClick={() => void decide(false)}>{t("decline")}</Button>
                <Button size="sm" disabled={busy} onClick={() => void decide(true)}>{t("approve")}</Button>
              </span>
            </div>
          ) : null}
          {escalated ? (
            <p className="rounded-xl border bg-muted/60 px-4 py-2.5 text-sm text-muted-foreground" role="status">{t("withPerson")}</p>
          ) : null}
          <form onSubmit={onSubmit} className="relative rounded-2xl border bg-card shadow-sm transition-shadow focus-within:border-ring focus-within:shadow-md">
            <label htmlFor="chat-input" className="sr-only">{t("placeholder", { name })}</label>
            <textarea
              id="chat-input"
              ref={input}
              value={text}
              onChange={(e) => setText(e.target.value)}
              onKeyDown={onKeyDown}
              rows={1}
              maxLength={4000}
              disabled={!agent || awaiting || escalated}
              placeholder={escalated ? t("escalatedPlaceholder") : t("placeholder", { name })}
              className="field-sizing-content block max-h-48 min-h-14 w-full resize-none bg-transparent px-4 py-4 pe-14 text-[15px] outline-none placeholder:text-muted-foreground disabled:cursor-not-allowed"
              data-testid="chat-input"
            />
            <Hint label={t("send")}>
              <Button type="submit" size="icon" className="absolute bottom-2.5 end-2.5 size-9 rounded-xl" disabled={!text.trim() || busy || !agent || awaiting || escalated} aria-label={t("send")}>
                <ArrowUp className="size-4" aria-hidden="true" />
              </Button>
            </Hint>
          </form>
          <div className="flex flex-wrap items-center justify-between gap-2 px-1 text-xs text-muted-foreground">
            <span>{t("disclaimer")}</span>
            {!escalated && !awaiting ? (
              <button type="button" onClick={() => void askPerson()} disabled={busy || !agent} className="rounded font-medium text-primary underline-offset-4 hover:underline focus-visible:outline-2 focus-visible:outline-ring disabled:opacity-50">
                {t("askPerson")}
              </button>
            ) : null}
          </div>
        </div>
      </div>
      {canAdmin ? <AnswerInspector runId={inspect} onClose={() => setInspect(null)} /> : null}
    </div>
  );
}
