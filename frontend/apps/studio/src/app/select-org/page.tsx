import { redirect } from "next/navigation";
import { getTranslations } from "next-intl/server";

import { currentSession } from "@/lib/server/auth/current";
import { loadMemberships } from "@/lib/server/studio";

import { OrgChooser } from "./org-chooser";

export default async function SelectOrg() {
  const session = await currentSession();
  if (!session) redirect("/auth/login");
  const memberships = await loadMemberships(session.accessToken);
  if (memberships === null) redirect("/auth/login");
  if (memberships.length === 0) redirect("/onboarding");
  const t = await getTranslations("onboarding");
  return (
    <main id="main" className="flex min-h-dvh items-center justify-center p-6">
      <div className="w-full max-w-md space-y-6">
        <div className="space-y-2">
          <h1 className="text-2xl font-semibold">{t("selectTitle")}</h1>
          <p className="text-muted-foreground">{t("selectSubtitle")}</p>
        </div>
        <OrgChooser memberships={memberships} />
      </div>
    </main>
  );
}
