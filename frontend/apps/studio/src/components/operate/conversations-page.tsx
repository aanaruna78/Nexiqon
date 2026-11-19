"use client";

import { ChevronDown, ChevronUp, Inbox, MessagesSquare, ScanSearch, Send, UserRoundCheck, Wrench } from "lucide-react";
import { useRouter, useSearchParams } from "next/navigation";
import { useFormatter, useTranslations } from "next-intl";
import { type FormEvent, useEffect, useState } from "react";
import { toast } from "sonner";

import { EmptyState } from "@/components/empty-state";
import { FixAnswer, type FixTarget } from "@/components/fix/fix-answer";
import { AnswerInspector } from "@/components/inspector/answer-inspector";
import { PageHeader } from "@/components/page-header";
import { Button } from "@/components/ui/button";
import { Label } from "@/components/ui/label";
import { Select, SelectContent, SelectItem, SelectTrigger, SelectValue } from "@/components/ui/select";
import { Sheet, SheetContent, SheetDescription, SheetHeader, SheetTitle } from "@/components/ui/sheet";
import { Skeleton } from "@/components/ui/skeleton";
import { Textarea } from "@/components/ui/textarea";
import { StatusBadge } from "@/components/visual/status-badge";
import { useErrorToast } from "@/lib/hooks";
import { type Conversation, type ConversationMessage, questionBefore, queueOrder } from "@/lib/operate";
import { useConversation, useConversations, useQueueActions } from "@/lib/operate-hooks";
import { useObjects } from "@/lib/studio-hooks";
import { cn } from "@/lib/utils";

const QUEUE_TONE = { open: "rose", claimed: "amber", resolved: "teal" } as const;

/** Conversations review and the escalation queue (ST-16): review 20 conversations quickly. */
export function ConversationsPage() {
  const t = useTranslations("conversations");
  const params = useSearchParams();
  const router = useRouter();
  const view = params.get("view") === "all" ? "all" : "queue";
  const agents = useObjects("agent");
  const [agent, setAgent] = useState<string>("__all");
  const list = useConversations({ queue: view === "queue" ? "waiting" : undefined, agent: agent === "__all" ? undefined : agent });
  const items = view === "queue" ? queueOrder(list.data ?? []) : (list.data ?? []);
  const open = params.get("c");
  const index = items.findIndex((c) => c.id === open);

  const go = (id: string | null, nextView = view) => {
    const q = new URLSearchParams();
    if (nextView === "all") q.set("view", "all");
    if (id) q.set("c", id);
    router.replace(`/conversations${q.size ? `?${q}` : ""}`);
  };

  return (
    <div className="space-y-6">
      <PageHeader title={t("title")} description={t("subtitle")} icon={MessagesSquare} tone="sky" />
      <div className="flex flex-wrap items-end justify-between gap-4">
        <div role="group" aria-label={t("show")} className="inline-flex rounded-lg border p-0.5">
          {(["queue", "all"] as const).map((v) => (
            <Button key={v} type="button" size="sm" variant={view === v ? "secondary" : "ghost"} aria-pressed={view === v} onClick={() => go(null, v)} data-testid={`view-${v}`}>
              {t(v)}
            </Button>
          ))}
        </div>
        <div className="space-y-1">
          <Label htmlFor="conv-agent" className="text-xs text-muted-foreground">{t("assistant")}</Label>
          <Select value={agent} onValueChange={setAgent}>
            <SelectTrigger id="conv-agent" className="w-52"><SelectValue /></SelectTrigger>
            <SelectContent>
              <SelectItem value="__all">{t("allAssistants")}</SelectItem>
              {(agents.data ?? []).map((a) => <SelectItem key={a.name} value={a.name}>{a.name}</SelectItem>)}
            </SelectContent>
          </Select>
        </div>
      </div>
      {list.isLoading ? (
        <Skeleton className="h-64" />
      ) : !items.length ? (
        <EmptyState icon={Inbox} tone="sky" title={view === "queue" ? t("queueEmpty") : t("noneYet")} body={view === "queue" ? t("queueEmptyBody") : t("noneYetBody")} />
      ) : (
        <ul className="nx-card divide-y" data-testid="conversation-list" aria-label={t(view)}>
          {items.map((c) => (
            <li key={c.id}>
              <Row conversation={c} onOpen={() => go(c.id)} />
            </li>
          ))}
        </ul>
      )}
      <Reader
        id={open}
        onClose={() => go(null)}
        onPrev={index > 0 ? () => go(items[index - 1].id) : undefined}
        onNext={index >= 0 && index < items.length - 1 ? () => go(items[index + 1].id) : undefined}
        position={index >= 0 ? t("position", { n: index + 1, total: items.length }) : ""}
      />
    </div>
  );
}

function Row({ conversation: c, onOpen }: { conversation: Conversation; onOpen: () => void }) {
  const t = useTranslations("conversations");
  const format = useFormatter();
  return (
    <button type="button" onClick={onOpen} className="flex w-full flex-wrap items-center justify-between gap-3 p-3 text-start text-sm outline-none hover:bg-muted/40 focus-visible:ring-2 focus-visible:ring-ring" data-testid="conversation-row">
      <span className="flex min-w-0 flex-col">
        <span className="truncate font-medium">{c.title ?? t("untitled")}</span>
        <span className="truncate text-xs text-muted-foreground">
          {[c.agent, t(`channels.${c.channel}`), format.relativeTime(new Date(c.last_message_at ?? c.created_at))].join(" · ")}
        </span>
      </span>
      <span className="flex items-center gap-2">
        {c.queue_status ? <StatusBadge tone={QUEUE_TONE[c.queue_status]} live={c.queue_status === "open"}>{t(`queueStatus.${c.queue_status}`)}</StatusBadge> : null}
        {c.assignee ? <span className="text-xs text-muted-foreground">{c.assignee}</span> : null}
      </span>
    </button>
  );
}

function Reader({ id, onClose, onPrev, onNext, position }: { id: string | null; onClose: () => void; onPrev?: () => void; onNext?: () => void; position: string }) {
  const t = useTranslations("conversations");
  const detail = useConversation(id);

  // j/k (or arrows with Alt) move between conversations while reading.
  useEffect(() => {
    if (!id) return;
    const onKey = (e: KeyboardEvent) => {
      const target = e.target as HTMLElement;
      if (target.closest("textarea, input")) return;
      if ((e.key === "j" || (e.altKey && e.key === "ArrowDown")) && onNext) onNext();
      if ((e.key === "k" || (e.altKey && e.key === "ArrowUp")) && onPrev) onPrev();
    };
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  }, [id, onNext, onPrev]);

  const c = detail.data;
  return (
    <Sheet open={!!id} onOpenChange={(o) => !o && onClose()}>
      <SheetContent className="w-full overflow-y-auto sm:max-w-2xl" data-testid="conversation-reader">
        <SheetHeader>
          <SheetTitle>{c?.title ?? t("untitled")}</SheetTitle>
          <SheetDescription>{c ? `${c.agent} · ${t(`channels.${c.channel}`)} · ${position}` : position}</SheetDescription>
          <div className="flex gap-2 pt-1">
            <Button variant="outline" size="sm" onClick={onPrev} disabled={!onPrev} aria-keyshortcuts="k">
              <ChevronUp className="size-4" aria-hidden="true" />
              {t("previous")}
            </Button>
            <Button variant="outline" size="sm" onClick={onNext} disabled={!onNext} aria-keyshortcuts="j" data-testid="next-conversation">
              <ChevronDown className="size-4" aria-hidden="true" />
              {t("next")}
            </Button>
          </div>
        </SheetHeader>
        <div className="space-y-6 px-4 pb-8">
          {detail.isLoading ? <Skeleton className="h-64" /> : null}
          {c ? <ReaderBody key={c.id} id={c.id} /> : null}
        </div>
      </SheetContent>
    </Sheet>
  );
}

function ReaderBody({ id }: { id: string }) {
  const t = useTranslations("conversations");
  const onError = useErrorToast();
  const detail = useConversation(id);
  const { act, reply } = useQueueActions(id);
  const [inspect, setInspect] = useState<string | null>(null);
  const [fix, setFix] = useState<FixTarget | null>(null);
  const [text, setText] = useState("");
  const c = detail.data!;

  async function send(e: FormEvent) {
    e.preventDefault();
    if (!text.trim()) return;
    try {
      await reply.mutateAsync(text.trim());
      setText("");
      toast.success(t("replied"));
    } catch (error) {
      onError(error);
    }
  }

  const run = (action: "claim" | "release" | "resolve" | "reopen") => act.mutate(action, { onError, onSuccess: () => toast.success(t(`done.${action}`)) });
  return (
    <>
      {c.queue_status ? (
        <section className="nx-card space-y-3 p-4" aria-labelledby="handoff-title" data-testid="handoff-card">
          <div className="flex flex-wrap items-center justify-between gap-2">
            <h3 id="handoff-title" className="flex items-center gap-2 font-semibold">
              <UserRoundCheck className="size-4" aria-hidden="true" />
              {t("handedOver")}
            </h3>
            <StatusBadge tone={QUEUE_TONE[c.queue_status]}>{t(`queueStatus.${c.queue_status}`)}{c.assignee ? ` · ${c.assignee}` : ""}</StatusBadge>
          </div>
          {c.handoff_summary ? <p className="text-sm whitespace-pre-line">{c.handoff_summary}</p> : null}
          <div className="flex flex-wrap gap-2">
            {c.queue_status === "open" ? <Button size="sm" onClick={() => run("claim")} data-testid="claim">{t("claim")}</Button> : null}
            {c.queue_status === "claimed" ? <Button size="sm" variant="outline" onClick={() => run("release")}>{t("release")}</Button> : null}
            {c.queue_status !== "resolved" ? <Button size="sm" variant="outline" onClick={() => run("resolve")} data-testid="resolve">{t("resolve")}</Button> : <Button size="sm" variant="outline" onClick={() => run("reopen")}>{t("reopen")}</Button>}
          </div>
        </section>
      ) : null}
      <ol className="space-y-3" data-testid="transcript" aria-label={t("transcript")}>
        {c.messages.map((m, i) => (
          <MessageRow key={m.id} message={m} onInspect={() => m.run_id && setInspect(m.run_id)} onFix={() => setFix({ agent: c.agent, question: questionBefore(c.messages, i) ?? "", answer: m.content, runId: m.run_id, lang: c.locale })} />
        ))}
      </ol>
      {c.status === "escalated" && c.queue_status !== "resolved" ? (
        <form onSubmit={send} className="space-y-2">
          <Label htmlFor="staff-reply">{t("replyLabel")}</Label>
          <Textarea id="staff-reply" rows={3} value={text} onChange={(e) => setText(e.target.value)} data-testid="staff-reply" />
          <p className="text-xs text-muted-foreground">{t("replyHelp")}</p>
          <Button type="submit" disabled={!text.trim() || reply.isPending} data-testid="send-staff-reply">
            <Send className="size-4" aria-hidden="true" />
            {t("sendReply")}
          </Button>
        </form>
      ) : null}
      <AnswerInspector runId={inspect} onClose={() => setInspect(null)} />
      <FixAnswer target={fix} onClose={() => setFix(null)} />
    </>
  );
}

function MessageRow({ message: m, onInspect, onFix }: { message: ConversationMessage; onInspect: () => void; onFix: () => void }) {
  const t = useTranslations("conversations");
  const format = useFormatter();
  const kind = m.contract?.kind;
  const unsure = m.role === "assistant" && (m.contract?.abstained || (kind === "clarify" && m.contract?.route === "knowledge"));
  return (
    <li className={cn("flex flex-col gap-1", m.role === "user" ? "items-end" : "items-start")}>
      <span className="text-xs text-muted-foreground">
        {m.role === "user" ? t("visitor") : m.role === "staff" ? t("staff", { name: m.contract?.author ?? "" }) : t("assistantRole")} · {format.dateTime(new Date(m.created_at), { hour: "2-digit", minute: "2-digit" })}
      </span>
      <div className={cn("max-w-[85%] rounded-2xl px-3 py-2 text-sm whitespace-pre-line", m.role === "user" ? "bg-primary text-primary-foreground" : m.role === "staff" ? "border-2 border-sky-500 bg-sky-50 dark:bg-sky-950" : unsure ? "border border-amber-500 bg-amber-50 dark:bg-amber-950" : "bg-muted")} dir="auto">
        {m.content}
      </div>
      {m.role === "assistant" ? (
        <div className="flex flex-wrap items-center gap-2">
          {kind ? <StatusBadge tone={unsure ? "amber" : kind === "grounded" ? "teal" : "slate"}>{unsure ? t("unsure") : kind}</StatusBadge> : null}
          {m.contract?.citations?.map((c) => <span key={c.marker} className="rounded-md bg-primary/10 px-1.5 text-xs text-primary">[{c.marker}] {c.citation}</span>)}
          {m.run_id ? (
            <Button variant="ghost" size="sm" onClick={onInspect}>
              <ScanSearch className="size-4" aria-hidden="true" />
              {t("why")}
            </Button>
          ) : null}
          <Button variant="ghost" size="sm" onClick={onFix} data-testid="conversation-fix">
            <Wrench className="size-4" aria-hidden="true" />
            {t("fix")}
          </Button>
        </div>
      ) : null}
    </li>
  );
}
