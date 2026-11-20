import { FileText, Lock, ShieldCheck } from "lucide-react";
import { useTranslations } from "next-intl";
import type { ReactNode } from "react";

import { BrandMark } from "@/components/visual/brand-mark";

/**
 * Full-page frame for the pages around sign-in (signed out, first organization, choose an
 * organization): a brand panel beside the content on wide screens, matching the sign-in page
 * itself (the Keycloak theme), so moving between Keycloak and Studio feels like one product.
 */
export function AuthFrame({ children }: { children: ReactNode }) {
  const t = useTranslations("auth");
  const points = [
    { icon: FileText, title: t("point1Title"), body: t("point1Body") },
    { icon: Lock, title: t("point2Title"), body: t("point2Body") },
    { icon: ShieldCheck, title: t("point3Title"), body: t("point3Body") },
  ];
  return (
    <div className="grid min-h-dvh bg-surface lg:grid-cols-[minmax(380px,44%)_1fr]">
      <aside className="nx-auth-brand relative hidden flex-col justify-between gap-12 overflow-hidden px-14 py-12 lg:flex">
        <div className="relative flex items-center gap-3">
          <BrandMark className="size-10 drop-shadow-[0_6px_16px_rgba(11,111,102,0.45)]" />
          <span className="text-xl font-semibold tracking-tight text-white">Nexiqon</span>
        </div>
        <div className="relative max-w-[470px]">
          <p className="mb-3.5 text-[13px] font-semibold uppercase tracking-[0.08em] text-[#7fdccf]">{t("eyebrow")}</p>
          <p className="mb-9 text-balance text-[clamp(26px,2.4vw,34px)] font-semibold leading-tight tracking-tight text-white">{t("headline")}</p>
          <ul className="grid gap-5">
            {points.map(({ icon: Icon, title, body }) => (
              <li key={title} className="flex items-start gap-3.5">
                <span className="grid size-9 flex-none place-items-center rounded-[10px] border border-[#7fdccf]/25 bg-[#2bb3a3]/15">
                  <Icon className="size-[18px] text-[#7fdccf]" aria-hidden="true" />
                </span>
                <span>
                  <strong className="block text-[15px] font-semibold text-white">{title}</strong>
                  <span className="block text-sm leading-relaxed text-[#b9c8d8]">{body}</span>
                </span>
              </li>
            ))}
          </ul>
        </div>
        <p className="relative text-[13px] text-[#8ea3ba]">{t("foot")}</p>
      </aside>
      <main id="main" className="relative flex items-start justify-center px-4 py-14 sm:px-6 lg:items-center">
        <div className="nx-page w-full max-w-md space-y-6">
          <div className="flex items-center justify-center gap-2.5 lg:hidden">
            <BrandMark className="size-9" />
            <span className="text-lg font-semibold tracking-tight">
              Nexiqon <span className="font-normal text-muted-foreground">Studio</span>
            </span>
          </div>
          <div className="nx-card p-6 sm:p-8">{children}</div>
        </div>
      </main>
    </div>
  );
}
