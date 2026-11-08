import { Construction } from "lucide-react";
import Link from "next/link";
import { getTranslations } from "next-intl/server";

import { EmptyState } from "@/components/empty-state";
import { PageHeader } from "@/components/page-header";
import { Button } from "@/components/ui/button";
import { ALL_ITEMS } from "@/components/shell/nav";

/** Designed placeholder for sections delivered in later phases (no dead ends in the IA). */
export async function ComingSoon({ section }: { section: string }) {
  const t = await getTranslations();
  const item = ALL_ITEMS.find((i) => i.key === section);
  const name = t(`nav.${section}`);
  return (
    <div className="space-y-8">
      <PageHeader title={name} icon={item?.icon} tone={item?.tone} />
      <EmptyState
        icon={item?.icon ?? Construction}
        tone={item?.tone}
        title={t("comingSoon.title", { section: name })}
        body={`${t("comingSoon.body", { what: t(`sections.${section}`) })} ${t("comingSoon.whatYouCanDo")}`}
        action={
          <div className="flex flex-col items-center gap-3">
            {item?.phase ? <span className="text-xs text-muted-foreground">{t("comingSoon.phase", { phase: item.phase })}</span> : null}
            <Button asChild variant="outline">
              <Link href="/settings/members">{t("nav.settings")}</Link>
            </Button>
          </div>
        }
      />
    </div>
  );
}
