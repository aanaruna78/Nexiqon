"use client";

import { useRouter } from "next/navigation";
import { useTranslations } from "next-intl";
import { toast } from "sonner";

import type { Locale } from "@/i18n/config";
import { postJson } from "@/lib/api";

/** Shell actions shared by the sidebar menus and the command palette. */
export function useShellActions() {
  const router = useRouter();
  const t = useTranslations("shell");
  return {
    async switchOrg(slug: string, name: string) {
      await postJson("/api/session/tenant", { tenant: slug });
      toast.success(t("orgSwitched", { name }));
      router.push("/");
      router.refresh();
    },
    async setLocale(locale: Locale) {
      await postJson("/api/locale", { locale });
      router.refresh();
    },
    async signOut() {
      const { redirect } = await postJson<{ redirect: string }>("/auth/logout", {});
      window.location.assign(redirect);
    },
  };
}
