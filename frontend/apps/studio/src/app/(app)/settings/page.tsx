import type { Metadata } from "next";
import { getTranslations } from "next-intl/server";

import { PersonalSettings } from "@/components/workspace/personal-settings";
import { requireMembership } from "@/lib/server/studio";

export async function generateMetadata(): Promise<Metadata> {
  const t = await getTranslations("personal");
  return { title: t("title") };
}

/** Your own settings: profile, appearance, language. Organization administration is in /admin. */
export default async function SettingsPage() {
  const { session, memberships, active } = await requireMembership();
  return <PersonalSettings user={session.user} memberships={memberships} active={active} />;
}
