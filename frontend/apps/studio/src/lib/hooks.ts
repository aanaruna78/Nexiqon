"use client";

import { useQuery } from "@tanstack/react-query";
import { useLocale, useTranslations } from "next-intl";
import { toast } from "sonner";

import { api, ApiError } from "./api";

/** Domain vocabulary from the tenant's deployed Domain Packs (UX-06): pack terms override defaults. */
export function useTerm(): (term: string, fallback: string) => string {
  const locale = useLocale();
  const { data } = useQuery({
    queryKey: ["vocabulary"],
    queryFn: () => api<Record<string, Record<string, string>>>("config/v1/vocabulary?environment=dev"),
    staleTime: 5 * 60_000,
  });
  return (term, fallback) => data?.[term]?.[locale] ?? data?.[term]?.en ?? fallback;
}

/** Toast an API failure with the server's explanation when there is one. */
export function useErrorToast(): (error: unknown) => void {
  const t = useTranslations("errors");
  return (error) => {
    if (error instanceof ApiError) {
      if (error.status === 403) return void toast.error(t("forbidden"), { description: error.problem.detail });
      return void toast.error(error.problem.title ?? t("generic"), { description: error.problem.detail });
    }
    toast.error(t("network"));
  };
}
