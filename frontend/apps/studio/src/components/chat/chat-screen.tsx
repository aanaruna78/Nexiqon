"use client";

import { PanelLeft } from "lucide-react";
import { useRouter } from "next/navigation";
import { useTranslations } from "next-intl";
import { useState } from "react";

import { Button } from "@/components/ui/button";
import { Sheet, SheetContent, SheetTitle } from "@/components/ui/sheet";
import { Skeleton } from "@/components/ui/skeleton";
import { Hint } from "@/components/visual/hint";
import { useConversationDetail } from "@/lib/chat";

import { ChatView } from "./chat-view";
import { HistoryPanel } from "./history-panel";

/** The home page: your chat history beside the conversation (a slide-over on small screens). */
export function ChatScreen({ conversationId, canAdmin }: { conversationId?: string; canAdmin: boolean }) {
  const t = useTranslations("chat");
  // "New chat" on the same page starts over without a reload.
  const [fresh, setFresh] = useState(0);
  const [open, setOpen] = useState(false);
  const startOver = () => setFresh((n) => n + 1);
  const router = useRouter();
  const detail = useConversationDetail(conversationId ?? null);
  return (
    <div className="flex min-h-0 flex-1">
      <aside className="hidden w-72 flex-none border-e bg-surface lg:block">
        <HistoryPanel onNew={startOver} />
      </aside>
      <Sheet open={open} onOpenChange={setOpen}>
        <SheetContent side="left" className="w-80 p-0">
          <SheetTitle className="sr-only">{t("history")}</SheetTitle>
          <HistoryPanel onNew={startOver} onNavigate={() => setOpen(false)} />
        </SheetContent>
      </Sheet>
      <main id="main" tabIndex={-1} className="relative flex min-h-0 min-w-0 flex-1 flex-col outline-none">
        <Hint label={t("history")}>
          <Button variant="ghost" size="icon" className="absolute start-3 top-3 z-10 lg:hidden" aria-label={t("history")} onClick={() => setOpen(true)}>
            <PanelLeft className="size-5" aria-hidden="true" />
          </Button>
        </Hint>
        <div className="flex min-h-0 flex-1 flex-col max-lg:ps-12">
          {conversationId && detail.isLoading ? (
            <div className="mx-auto flex w-full max-w-3xl flex-1 flex-col gap-4 px-4 py-10" aria-busy="true">
              <Skeleton className="h-8 w-48" />
              <Skeleton className="h-24 w-full" />
              <Skeleton className="h-24 w-3/4" />
            </div>
          ) : conversationId && detail.isError ? (
            <div className="mx-auto max-w-md flex-1 px-4 py-16 text-center">
              <p className="font-medium">{t("notFound")}</p>
              <Button className="mt-4" onClick={() => router.push("/")}>{t("newChat")}</Button>
            </div>
          ) : (
            <ChatView key={`${conversationId ?? "new"}-${fresh}`} initial={detail.data} canAdmin={canAdmin} />
          )}
        </div>
      </main>
    </div>
  );
}
