"use client";

import { Building2, ChevronRight } from "lucide-react";
import { useRouter } from "next/navigation";
import { useTranslations } from "next-intl";
import { useEffect } from "react";

import type { StudioMembership } from "@/app/api/session/route";
import { postJson } from "@/lib/api";

export function OrgChooser({ memberships }: { memberships: StudioMembership[] }) {
  const t = useTranslations("members.roles");
  const router = useRouter();
  const choose = async (slug: string) => {
    await postJson("/api/session/tenant", { tenant: slug });
    router.push("/");
    router.refresh();
  };
  useEffect(() => {
    // One organization: nothing to choose.
    if (memberships.length === 1) void choose(memberships[0].tenant_slug);
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);
  return (
    <ul className="divide-y rounded-lg border">
      {memberships.map((m) => (
        <li key={m.tenant_id}>
          <button type="button" onClick={() => choose(m.tenant_slug)} className="flex w-full items-center gap-3 px-4 py-3 text-start hover:bg-muted focus-visible:bg-muted focus-visible:outline-none">
            <Building2 className="size-5 text-muted-foreground" aria-hidden="true" />
            <span className="flex-1">
              <span className="block font-medium">{m.tenant_name}</span>
              <span className="block text-sm text-muted-foreground">{t(m.role)}</span>
            </span>
            <ChevronRight className="size-4 rtl:rotate-180" aria-hidden="true" />
          </button>
        </li>
      ))}
    </ul>
  );
}
