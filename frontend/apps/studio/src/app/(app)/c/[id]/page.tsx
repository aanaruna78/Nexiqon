import type { Metadata } from "next";
import { notFound } from "next/navigation";
import { getTranslations } from "next-intl/server";

import { ChatScreen } from "@/components/chat/chat-screen";
import { requireMembership } from "@/lib/server/studio";

const UUID = /^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$/i;

export async function generateMetadata(): Promise<Metadata> {
  const t = await getTranslations("chat");
  return { title: t("title") };
}

/** One of your conversations, resumed. */
export default async function Conversation({ params }: PageProps<"/c/[id]">) {
  const { id } = await params;
  if (!UUID.test(id)) notFound();
  const { canAdmin } = await requireMembership();
  return <ChatScreen conversationId={id} canAdmin={canAdmin} />;
}
