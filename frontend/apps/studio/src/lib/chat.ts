"use client";

import { useQueries, useQuery } from "@tanstack/react-query";

import { api } from "@/lib/api";
import { useObjects } from "@/lib/studio-hooks";

/** The assistant chat (home page): types and data hooks. */

export interface Citation {
  marker: string;
  citation: string;
  source_uri?: string | null;
}

export interface ChatMessage {
  id?: string;
  role: "user" | "assistant" | "staff";
  content: string;
  contract?: {
    kind?: string;
    citations?: Citation[];
    abstained?: boolean;
    interrupt?: { kind?: string; prompt?: string; purpose?: string };
  };
  run_id?: string | null;
  created_at?: string;
  streaming?: boolean;
  rating?: "up" | "down";
}

export interface ConversationSummary {
  id: string;
  agent: string;
  channel: string;
  status: string;
  title: string | null;
  created_at: string;
  last_message_at: string | null;
}

export interface ConversationDetail extends ConversationSummary {
  messages: ChatMessage[];
}

export interface Turn {
  conversation: { id: string; status: string; title?: string | null };
  reply: ChatMessage | null;
}

/** What the widget channel publishes for an assistant: its name, greeting and starter questions. */
export interface AssistantFace {
  agent: string;
  title?: string;
  assistant_name?: string;
  greeting?: string;
  starter_questions?: string[];
  accent_color?: string;
}

export const MY_CONVERSATIONS = ["conversations", "mine"] as const;

/** The signed-in person's own conversations, newest first. */
export function useMyConversations() {
  return useQuery({
    queryKey: MY_CONVERSATIONS,
    queryFn: () => api<ConversationSummary[]>("conversation/v1/conversations?mine=true&limit=100"),
  });
}

export function useConversationDetail(id: string | null) {
  return useQuery({
    queryKey: ["conversation", id],
    queryFn: () => api<ConversationDetail>(`conversation/v1/conversations/${id}`),
    enabled: Boolean(id),
  });
}

/** Assistants that are live (deployed), with the name and greeting people see. */
export function useLiveAssistants(locale: string) {
  const agents = useObjects("agent");
  const live = (agents.data ?? []).filter((a) => Object.keys(a.deployments ?? {}).length > 0);
  const faces = useQueries({
    queries: live.map((a) => ({
      queryKey: ["assistant-face", a.name, locale],
      queryFn: async (): Promise<AssistantFace> => {
        const face = await api<Omit<AssistantFace, "agent">>(`channel/v1/channels/widget/agents/${a.name}?locale=${locale}`).catch(() => ({}));
        return { agent: a.name, ...face };
      },
      staleTime: 60_000,
    })),
  });
  const assistants = live.map((a, i) => faces[i]?.data ?? { agent: a.name });
  return { assistants, isLoading: agents.isLoading };
}

/** A readable name for an assistant: its published name, else its identifier. */
export function assistantLabel(a: AssistantFace | undefined, fallback: string): string {
  return a?.assistant_name || a?.title || fallback.replace(/[-_]+/g, " ").replace(/^\w/, (c) => c.toUpperCase());
}

/** Group conversations for the history panel. */
export function groupByAge(list: ConversationSummary[], now: Date): { key: "today" | "week" | "older"; items: ConversationSummary[] }[] {
  const start = new Date(now);
  start.setHours(0, 0, 0, 0);
  const week = start.getTime() - 6 * 86_400_000;
  const groups = { today: [] as ConversationSummary[], week: [] as ConversationSummary[], older: [] as ConversationSummary[] };
  for (const c of list) {
    const at = new Date(c.last_message_at ?? c.created_at).getTime();
    (at >= start.getTime() ? groups.today : at >= week ? groups.week : groups.older).push(c);
  }
  return (["today", "week", "older"] as const).filter((k) => groups[k].length).map((key) => ({ key, items: groups[key] }));
}

const LAST_ASSISTANT = "nexiqon:last-assistant";

export function rememberAssistant(agent: string): void {
  try {
    localStorage.setItem(LAST_ASSISTANT, agent);
  } catch {
    /* private mode: nothing to remember */
  }
}

export function lastAssistant(): string | null {
  try {
    return localStorage.getItem(LAST_ASSISTANT);
  } catch {
    return null;
  }
}
