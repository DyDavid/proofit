import type { Metadata } from "next";
import { Fraunces, IBM_Plex_Mono, Kantumruy_Pro } from "next/font/google";
import { notFound } from "next/navigation";
import { NextIntlClientProvider, hasLocale } from "next-intl";
import { getTranslations, setRequestLocale } from "next-intl/server";
import type { ReactNode } from "react";
import Footer from "@/components/layout/Footer";
import Header from "@/components/layout/Header";
import { routing } from "@/i18n/routing";
import "../globals.css";

/**
 * Kantumruy Pro is the single UI font for both scripts (PERSON_B_PLAN_v2.md
 * §7.4). The `khmer` subset is what keeps stacked consonants from falling back
 * to a system font mid-sentence.
 */
const kantumruyPro = Kantumruy_Pro({
  subsets: ["khmer", "latin"],
  weight: ["300", "400", "500", "600", "700"],
  variable: "--font-kantumruy",
  display: "swap",
});

/**
 * Display face for headlines and the big coverage numbers (BRAND.md §4). Latin
 * only — has no Khmer glyphs, which is why `globals.css` falls the `font-serif`
 * utility back to Kantumruy Pro whenever `<html lang="km">`.
 */
const fraunces = Fraunces({
  subsets: ["latin"],
  weight: ["300", "400", "500", "600"],
  style: ["normal", "italic"],
  variable: "--font-fraunces",
  display: "swap",
});

/**
 * Label/data face: eyebrows, timestamps, verdict pills, stamps, confidence
 * figures (BRAND.md §4). Also Latin-only, with the same Khmer fallback.
 */
const ibmPlexMono = IBM_Plex_Mono({
  subsets: ["latin"],
  weight: ["400", "500"],
  variable: "--font-plex-mono",
  display: "swap",
});

type Props = {
  children: ReactNode;
  params: Promise<{ locale: string }>;
};

export function generateStaticParams() {
  return routing.locales.map((locale) => ({ locale }));
}

export async function generateMetadata({
  params,
}: Omit<Props, "children">): Promise<Metadata> {
  const { locale } = await params;
  const activeLocale = hasLocale(routing.locales, locale)
    ? locale
    : routing.defaultLocale;

  const t = await getTranslations({ locale: activeLocale, namespace: "common" });
  const tLanding = await getTranslations({
    locale: activeLocale,
    namespace: "landing",
  });

  const appName = t("appName");

  return {
    title: {
      default: `${appName} · ${t("tagline")}`,
      template: `%s · ${appName}`,
    },
    description: tLanding("hero.subtitle"),
    applicationName: appName,
  };
}

export default async function LocaleLayout({ children, params }: Props) {
  const { locale } = await params;

  // The `[locale]` segment matches anything, so an unknown value is a 404.
  if (!hasLocale(routing.locales, locale)) {
    notFound();
  }

  // Opt the whole subtree into static rendering.
  setRequestLocale(locale);

  return (
    <html
      lang={locale}
      className={`${kantumruyPro.variable} ${fraunces.variable} ${ibmPlexMono.variable}`}
      data-scroll-behavior="smooth"
    >
      <body
        className={`${kantumruyPro.className} flex min-h-screen flex-col bg-paper leading-[1.75] text-ink antialiased`}
      >
        <NextIntlClientProvider>
          <Header />
          <main id="main" className="flex-1">
            {children}
          </main>
          <Footer />
        </NextIntlClientProvider>
      </body>
    </html>
  );
}
