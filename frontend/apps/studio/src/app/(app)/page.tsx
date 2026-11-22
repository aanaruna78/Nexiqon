import type { Metadata } from "next";
import { getTranslations } from "next-intl/server";

import { ChatScreen } from "@/components/chat/chat-screen";
import { requireMembership } from "@/lib/server/studio";

export async function generateMetadata(): Promise<Metadata> {
  const t = await getTranslations("chat");
  return { title: t("title") };
}

/** Home: the assistant. Pick an assistant and ask. */
export default async function Home() {
  const { canAdmin } = await requireMembership();
  return <ChatScreen canAdmin={canAdmin} />;
}
