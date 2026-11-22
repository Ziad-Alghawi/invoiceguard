import type { Metadata } from "next";
import { Geist, Geist_Mono } from "next/font/google";
import { NextIntlClientProvider } from "next-intl";
import { getLocale, getTranslations } from "next-intl/server";
import { Suspense } from "react";

import { HtmlLang } from "@/components/html-lang";
import { DEFAULT_LOCALE, HTML_LANG_SCRIPT } from "@/i18n/config";
import "./globals.css";

const geistSans = Geist({
  variable: "--font-sans",
  subsets: ["latin"],
});

const geistMono = Geist_Mono({
  variable: "--font-geist-mono",
  subsets: ["latin"],
});

export async function generateMetadata(): Promise<Metadata> {
  const t = await getTranslations("Metadata");
  return { title: "InvoiceGuard", description: t("description") };
}

/** Messages and the locale from the cookie, for server and client components below. */
async function IntlProvider({ children }: { children: React.ReactNode }) {
  const locale = await getLocale();
  return (
    <NextIntlClientProvider>
      <HtmlLang locale={locale} />
      {children}
    </NextIntlClientProvider>
  );
}

/**
 * The language comes from a cookie (ADR-027). Reading it here would make the static shell
 * request-bound (cacheComponents), so <html lang> starts as the default, the inline script sets
 * it before the first paint, and everything with text renders inside the Suspense boundary.
 */
export default function RootLayout({ children }: LayoutProps<"/">) {
  return (
    <html
      lang={DEFAULT_LOCALE}
      suppressHydrationWarning
      className={`${geistSans.variable} ${geistMono.variable} h-full antialiased`}
    >
      <head>
        <script dangerouslySetInnerHTML={{ __html: HTML_LANG_SCRIPT }} />
      </head>
      <body className="flex min-h-full flex-col">
        <Suspense fallback={null}>
          <IntlProvider>{children}</IntlProvider>
        </Suspense>
      </body>
    </html>
  );
}
