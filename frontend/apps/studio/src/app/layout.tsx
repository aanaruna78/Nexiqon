import type { Metadata } from "next";
import { Geist, Geist_Mono } from "next/font/google";
import { NextIntlClientProvider } from "next-intl";
import { getLocale } from "next-intl/server";

import { Providers } from "@/components/providers";
import { direction } from "@/i18n/config";
import { DATA_ORIGIN_META } from "@/lib/split";

import "./globals.css";

const geistSans = Geist({ variable: "--font-sans", subsets: ["latin"] });
const geistMono = Geist_Mono({ variable: "--font-geist-mono", subsets: ["latin"] });

export function generateMetadata(): Metadata {
  // Split-origin (DV-08): tells the browser code where the data-plane Studio is (no secret).
  const dataOrigin = process.env.NEXIQON_DATA_ORIGIN ? new URL(process.env.NEXIQON_DATA_ORIGIN).origin : null;
  return {
    title: { default: "Nexiqon Studio", template: "%s · Nexiqon Studio" },
    description: "Configure, test and operate Nexiqon assistants",
    ...(dataOrigin ? { other: { [DATA_ORIGIN_META]: dataOrigin } } : {}),
  };
}

export default async function RootLayout({ children }: LayoutProps<"/">) {
  const locale = await getLocale();
  const dir = direction(locale);
  return (
    <html lang={locale === "en-XA" ? "en" : locale} dir={dir} suppressHydrationWarning>
      <body className={`${geistSans.variable} ${geistMono.variable} min-h-dvh bg-background font-sans text-foreground antialiased`}>
        <NextIntlClientProvider>
          <Providers dir={dir}>{children}</Providers>
        </NextIntlClientProvider>
      </body>
    </html>
  );
}
