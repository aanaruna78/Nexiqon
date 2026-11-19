"use client";

import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { Bell } from "lucide-react";
import Link from "next/link";
import { useFormatter, useTranslations } from "next-intl";

import { Button } from "@/components/ui/button";
import { Popover, PopoverContent, PopoverTrigger } from "@/components/ui/popover";
import { api } from "@/lib/api";

interface InboxItem {
  id: string;
  kind: string;
  params: Record<string, string | number | null>;
  link: string | null;
  created_at: string;
  read: boolean;
}

interface Inbox {
  unread: number;
  items: InboxItem[];
}

/** In-app notifications (NT-01): what needs this person's attention. */
export function InboxBell() {
  const t = useTranslations("inbox");
  const format = useFormatter();
  const client = useQueryClient();
  const inbox = useQuery({
    queryKey: ["inbox"],
    queryFn: () => api<Inbox>("notification/v1/inbox"),
    refetchInterval: 60_000,
    retry: false,
  });
  const read = useMutation({
    mutationFn: (ids: string[]) => api<Inbox>("notification/v1/inbox/read", { method: "POST", json: { ids } }),
    onSuccess: (data) => client.setQueryData(["inbox"], data),
  });
  const unread = inbox.data?.unread ?? 0;
  const text = (i: InboxItem) => {
    const params = Object.fromEntries(Object.entries(i.params).map(([k, v]) => [k, v ?? ""]));
    if (typeof params.threshold === "number") params.threshold = Math.round(Number(params.threshold) * 100);
    if (typeof params.pass_rate === "number") params.pass_rate = Math.round(Number(params.pass_rate) * 100);
    return t.has(`kinds.${i.kind}`) ? t(`kinds.${i.kind}`, params) : i.kind;
  };
  return (
    <Popover>
      <PopoverTrigger asChild>
        <Button variant="ghost" size="icon" className="relative rounded-full" aria-label={unread ? t("labelUnread", { count: unread }) : t("label")} data-testid="inbox-bell">
          <Bell className="size-4" aria-hidden="true" />
          {unread ? (
            <span className="absolute -end-0.5 -top-0.5 grid min-w-4 place-items-center rounded-full bg-destructive px-1 text-[10px] font-semibold text-white tabular-nums" aria-hidden="true">
              {unread > 9 ? "9+" : unread}
            </span>
          ) : null}
        </Button>
      </PopoverTrigger>
      <PopoverContent align="end" className="w-80 p-0" data-testid="inbox">
        <div className="flex items-center justify-between border-b px-3 py-2">
          <p className="text-sm font-semibold">{t("title")}</p>
          {unread ? (
            <Button variant="ghost" size="sm" onClick={() => read.mutate([])}>{t("markAll")}</Button>
          ) : null}
        </div>
        {inbox.data?.items.length ? (
          <ul className="max-h-96 divide-y overflow-y-auto">
            {inbox.data.items.map((i) => (
              <li key={i.id}>
                <Link
                  href={i.link ?? "#"}
                  onClick={() => !i.read && read.mutate([i.id])}
                  className="flex gap-2 px-3 py-2 text-sm outline-none hover:bg-muted/50 focus-visible:bg-muted"
                >
                  <span className={i.read ? "mt-1.5 size-2 shrink-0" : "mt-1.5 size-2 shrink-0 rounded-full bg-primary"} aria-hidden="true" />
                  <span className="flex flex-col">
                    <span className={i.read ? "text-muted-foreground" : "font-medium"}>{text(i)}</span>
                    <span className="text-xs text-muted-foreground">{format.relativeTime(new Date(i.created_at))}</span>
                  </span>
                  {!i.read ? <span className="sr-only">{t("unread")}</span> : null}
                </Link>
              </li>
            ))}
          </ul>
        ) : (
          <p className="px-3 py-6 text-center text-sm text-muted-foreground">{t("empty")}</p>
        )}
      </PopoverContent>
    </Popover>
  );
}
