export const locales = ["en", "ar", "en-XA"] as const;
export type Locale = (typeof locales)[number];
export const defaultLocale: Locale = "en";
export const LOCALE_COOKIE = "NEXT_LOCALE";

/** en-XA is a pseudo-locale: accented, ~40% longer strings to catch truncation and hard-coded text. */
export const localeNames: Record<Locale, string> = {
  en: "English",
  ar: "العربية",
  "en-XA": "Ƥşḗḗŭḓǿǿ (test)",
};

export function isLocale(value: string | undefined | null): value is Locale {
  return !!value && (locales as readonly string[]).includes(value);
}

export function direction(locale: string): "ltr" | "rtl" {
  return locale === "ar" ? "rtl" : "ltr";
}
