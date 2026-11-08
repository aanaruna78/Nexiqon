import { LogIn } from "lucide-react";
import Link from "next/link";
import { getTranslations } from "next-intl/server";

import { AuthFrame } from "@/components/auth-frame";
import { Button } from "@/components/ui/button";

export default async function SignedOut({ searchParams }: PageProps<"/signed-out">) {
  const t = await getTranslations("signedOut");
  const reason = (await searchParams).reason;
  return (
    <AuthFrame>
      <div className="space-y-6 text-center">
        <h1 className="text-2xl font-semibold">{t("title")}</h1>
        <p className="text-muted-foreground">{reason === "expired" ? t("expired") : reason === "failed" ? t("failed") : t("body")}</p>
        <Button asChild className="w-full">
          <Link href="/auth/login">
            <LogIn className="size-4" aria-hidden="true" />
            {t("signIn")}
          </Link>
        </Button>
      </div>
    </AuthFrame>
  );
}
