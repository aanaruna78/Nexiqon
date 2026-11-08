"use client";

import { useMutation, useQuery } from "@tanstack/react-query";
import { useRouter } from "next/navigation";
import { useTranslations } from "next-intl";
import { useState, type FormEvent } from "react";
import { toast } from "sonner";

import { ShieldCheck } from "lucide-react";

import { PageHeader } from "@/components/page-header";
import { useStudio } from "@/components/shell/studio-context";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import { Select, SelectContent, SelectItem, SelectTrigger, SelectValue } from "@/components/ui/select";
import { localeNames } from "@/i18n/config";
import { api } from "@/lib/api";
import { useErrorToast } from "@/lib/hooks";

interface Tenant {
  name: string;
  slug: string;
  locale: string;
  region: string;
}

export function OrganizationPage() {
  const t = useTranslations("org");
  const tenant = useQuery({ queryKey: ["tenant"], queryFn: () => api<Tenant>("identity/v1/tenant") });
  return (
    <div className="space-y-8">
      <PageHeader title={t("title")} description={t("subtitle")} icon={ShieldCheck} tone="navy" />
      {tenant.data ? <OrganizationForm key={tenant.dataUpdatedAt} tenant={tenant.data} /> : null}
    </div>
  );
}

/** Keyed by the query's update time so it re-initialises from fresh data without effects. */
function OrganizationForm({ tenant }: { tenant: Tenant }) {
  const t = useTranslations("org");
  const tc = useTranslations("common");
  const router = useRouter();
  const { isAdmin } = useStudio();
  const onError = useErrorToast();
  const [name, setName] = useState(tenant.name);
  const [locale, setLocale] = useState(tenant.locale);
  const save = useMutation({
    mutationFn: () => api("identity/v1/tenant", { method: "PATCH", json: { name, locale } }),
    onSuccess: () => {
      toast.success(t("saved"));
      router.refresh();
    },
    onError,
  });
  const submit = (e: FormEvent) => {
    e.preventDefault();
    save.mutate();
  };
  return (
    <form onSubmit={submit} className="nx-card nx-page max-w-xl space-y-5 p-6">
      <div className="space-y-2">
        <Label htmlFor="org-name">{t("name")}</Label>
        <Input id="org-name" value={name} disabled={!isAdmin} required minLength={2} onChange={(e) => setName(e.target.value)} />
      </div>
      <div className="space-y-2">
        <Label htmlFor="org-locale">{t("locale")}</Label>
        <Select value={locale} onValueChange={setLocale} disabled={!isAdmin}>
          <SelectTrigger id="org-locale" className="w-full"><SelectValue /></SelectTrigger>
          <SelectContent>
            {(["en", "ar"] as const).map((l) => <SelectItem key={l} value={l}>{localeNames[l]}</SelectItem>)}
          </SelectContent>
        </Select>
      </div>
      <p className="text-sm text-muted-foreground" dir="ltr">{tenant.slug} · {tenant.region}</p>
      {isAdmin ? <Button type="submit" disabled={save.isPending}>{tc("save")}</Button> : null}
    </form>
  );
}
