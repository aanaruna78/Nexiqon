"use client";

import { useMutation, useQueryClient } from "@tanstack/react-query";
import { MessageSquare, SquarePen, Trash2 } from "lucide-react";
import Link from "next/link";
import { usePathname, useRouter } from "next/navigation";
import { useNow, useTranslations } from "next-intl";
import { useState } from "react";
import { toast } from "sonner";

import { AlertDialog, AlertDialogAction, AlertDialogCancel, AlertDialogContent, AlertDialogDescription, AlertDialogFooter, AlertDialogHeader, AlertDialogTitle } from "@/components/ui/alert-dialog";
import { Button } from "@/components/ui/button";
import { Skeleton } from "@/components/ui/skeleton";
import { Hint } from "@/components/visual/hint";
import { api } from "@/lib/api";
import { type ConversationSummary, groupByAge, MY_CONVERSATIONS, useMyConversations } from "@/lib/chat";
import { useErrorToast } from "@/lib/hooks";
import { cn } from "@/lib/utils";

/** Your past chats, newest first, grouped by age. Private to you (the service filters by person). */
export function HistoryPanel({ onNew, onNavigate }: { onNew: () => void; onNavigate?: () => void }) {
  const t = useTranslations("chat");
  const pathname = usePathname();
  const router = useRouter();
  const now = useNow({ updateInterval: 60_000 });
  const conversations = useMyConversations();
  const queryClient = useQueryClient();
  const onError = useErrorToast();
  const [doomed, setDoomed] = useState<ConversationSummary | null>(null);
  const remove = useMutation({
    mutationFn: (id: string) => api(`conversation/v1/conversations/${id}`, { method: "DELETE" }),
    onSuccess: (_, id) => {
      void queryClient.invalidateQueries({ queryKey: MY_CONVERSATIONS });
      toast.success(t("deleted"));
      if (pathname === `/c/${id}`) {
        onNew();
        router.push("/");
      }
    },
    onError,
  });

  const groups = groupByAge(conversations.data ?? [], now);
  return (
    <nav className="flex h-full min-h-0 flex-col gap-3 p-3" aria-label={t("history")}>
      <Button
        variant="outline"
        className="h-10 justify-start gap-2 rounded-xl bg-card font-medium"
        onClick={() => {
          onNew();
          onNavigate?.();
          router.push("/");
        }}
        data-testid="new-chat"
      >
        <SquarePen className="size-4" aria-hidden="true" />
        {t("newChat")}
      </Button>
      <div className="min-h-0 flex-1 overflow-y-auto">
        {conversations.isLoading ? (
          <div className="space-y-2 px-1">
            {[0, 1, 2, 3].map((i) => <Skeleton key={i} className="h-8" />)}
          </div>
        ) : groups.length === 0 ? (
          <p className="px-2 py-6 text-center text-sm text-muted-foreground">{t("noHistory")}</p>
        ) : (
          groups.map((g) => (
            <section key={g.key} className="mb-4" aria-labelledby={`history-${g.key}`}>
              <h2 id={`history-${g.key}`} className="mb-1 px-2 text-xs font-medium text-muted-foreground">{t(`when.${g.key}`)}</h2>
              <ul className="space-y-0.5">
                {g.items.map((c) => {
                  const active = pathname === `/c/${c.id}`;
                  const title = c.title?.trim() || t("untitled");
                  return (
                    <li key={c.id} className="group relative">
                      <Link
                        href={`/c/${c.id}`}
                        onClick={onNavigate}
                        aria-current={active ? "page" : undefined}
                        className={cn(
                          "flex items-center gap-2 rounded-lg px-2 py-2 pe-9 text-sm outline-none transition-colors hover:bg-muted focus-visible:ring-2 focus-visible:ring-ring",
                          active && "bg-muted font-medium",
                        )}
                      >
                        <MessageSquare className="size-4 flex-none text-muted-foreground" aria-hidden="true" />
                        <span className="truncate">{title}</span>
                      </Link>
                      <Hint label={t("deleteChat")} side="right">
                        <Button
                          variant="ghost"
                          size="icon"
                          className="absolute inset-y-0 end-1 z-10 my-auto size-7 opacity-0 transition-opacity focus-visible:opacity-100 group-hover:opacity-100"
                          aria-label={t("deleteChatNamed", { title })}
                          onClick={() => setDoomed(c)}
                        >
                          <Trash2 className="size-3.5" aria-hidden="true" />
                        </Button>
                      </Hint>
                    </li>
                  );
                })}
              </ul>
            </section>
          ))
        )}
      </div>
      <AlertDialog open={doomed !== null} onOpenChange={(open) => !open && setDoomed(null)}>
        <AlertDialogContent>
          <AlertDialogHeader>
            <AlertDialogTitle>{t("deleteTitle")}</AlertDialogTitle>
            <AlertDialogDescription>{t("deleteBody")}</AlertDialogDescription>
          </AlertDialogHeader>
          <AlertDialogFooter>
            <AlertDialogCancel>{t("cancel")}</AlertDialogCancel>
            <AlertDialogAction
              className="bg-destructive text-white hover:bg-destructive/90"
              onClick={() => {
                if (doomed) remove.mutate(doomed.id);
                setDoomed(null);
              }}
            >
              {t("deleteChat")}
            </AlertDialogAction>
          </AlertDialogFooter>
        </AlertDialogContent>
      </AlertDialog>
    </nav>
  );
}
