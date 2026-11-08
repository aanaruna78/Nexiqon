"use client";

import { Building2 } from "lucide-react";
import { useRouter } from "next/navigation";
import { useTranslations } from "next-intl";
import { useState, type FormEvent } from "react";

import { AuthFrame } from "@/components/auth-frame";
import { IconTile } from "@/components/visual/icon-tile";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import { api, ApiError, postJson } from "@/lib/api";

function slugify(name: string): string {
  return name.toLowerCase().normalize("NFKD").replace(/[^a-z0-9]+/g, "-").replace(/^-+|-+$/g, "").slice(0, 50);
}

export default function Onboarding() {
  const t = useTranslations();
  const router = useRouter();
  const [name, setName] = useState("");
  const [slug, setSlug] = useState("");
  const [slugTouched, setSlugTouched] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);

  async function submit(e: FormEvent) {
    e.preventDefault();
    setBusy(true);
    setError(null);
    try {
      await api("identity/v1/session/tenants", { method: "POST", json: { name, slug } });
      await postJson("/api/session/tenant", { tenant: slug });
      router.push("/");
      router.refresh();
    } catch (err) {
      setError(err instanceof ApiError ? (err.problem.detail ?? err.problem.title ?? t("errors.generic")) : t("errors.network"));
      setBusy(false);
    }
  }

  return (
    <AuthFrame>
      <form onSubmit={submit} className="space-y-6" noValidate>
        <div className="space-y-2">
          <IconTile icon={Building2} tone="teal" size="lg" />
          <h1 className="text-2xl font-semibold">{t("onboarding.title")}</h1>
          <p className="text-muted-foreground">{t("onboarding.subtitle")}</p>
        </div>
        <div className="space-y-2">
          <Label htmlFor="org-name">{t("onboarding.name")}</Label>
          <Input
            id="org-name"
            required
            minLength={2}
            autoFocus
            value={name}
            onChange={(e) => {
              setName(e.target.value);
              if (!slugTouched) setSlug(slugify(e.target.value));
            }}
          />
        </div>
        <div className="space-y-2">
          <Label htmlFor="org-slug">{t("onboarding.slug")}</Label>
          <Input
            id="org-slug"
            required
            dir="ltr"
            pattern="[a-z0-9][a-z0-9-]{1,61}[a-z0-9]"
            aria-describedby="org-slug-help"
            value={slug}
            onChange={(e) => {
              setSlugTouched(true);
              setSlug(e.target.value.toLowerCase());
            }}
          />
          <p id="org-slug-help" className="text-sm text-muted-foreground">{t("onboarding.slugHelp")}</p>
        </div>
        {error ? (
          <p role="alert" className="text-sm font-medium text-destructive">
            {error}
          </p>
        ) : null}
        <Button type="submit" className="w-full" disabled={busy || name.trim().length < 2 || slug.length < 3}>
          {busy ? t("onboarding.creating") : t("onboarding.create")}
        </Button>
      </form>
    </AuthFrame>
  );
}
