import type { Metadata } from "next";
import { Archivo, Geist, Geist_Mono, Newsreader } from "next/font/google";
import type { ReactNode } from "react";
import Footer from "@/components/layout/Footer";
import Header from "@/components/layout/Header";
import { getTranslations } from "@/lib/copy";
import { getSiteUrl } from "@/lib/seo";
import "./globals.css";

/** Geist is the single UI font. */
const geist = Geist({
  subsets: ["latin"],
  weight: ["300", "400", "500", "600", "700"],
  variable: "--font-geist",
  display: "swap",
});

/** Display face for headlines and the big coverage numbers: a variable
 * grotesque, used uppercase and condensed (font-serif token — see
 * globals.css for why the token name stays "serif"). */
const archivo = Archivo({
  subsets: ["latin"],
  weight: ["400", "500", "600", "700", "800", "900"],
  variable: "--font-archivo",
  display: "swap",
});

/** Decorative italic accent face for a single emphasised word per section. */
const newsreader = Newsreader({
  subsets: ["latin"],
  weight: ["300", "400", "500"],
  style: ["italic"],
  variable: "--font-newsreader",
  display: "swap",
});

/** Label/data face: eyebrows, timestamps, verdict pills, stamps, confidence
 * figures. */
const geistMono = Geist_Mono({
  subsets: ["latin"],
  weight: ["400", "500"],
  variable: "--font-geist-mono",
  display: "swap",
});

export async function generateMetadata(): Promise<Metadata> {
  const t = await getTranslations("common");
  const tLanding = await getTranslations("landing");

  const appName = t("appName");
  const defaultTitle = `${appName} · ${t("tagline")}`;
  const description = tLanding("hero.subtitle");
  const siteUrl = getSiteUrl();

  return {
    metadataBase: new URL(siteUrl),
    title: {
      default: defaultTitle,
      template: `%s | ${appName}`,
    },
    description,
    applicationName: appName,
    alternates: {
      canonical: "/",
    },
    openGraph: {
      type: "website",
      locale: "en_US",
      url: "/",
      siteName: appName,
      title: defaultTitle,
      description,
    },
    twitter: {
      card: "summary_large_image",
      title: defaultTitle,
      description,
    },
  };
}

export default function RootLayout({ children }: { children: ReactNode }) {
  return (
    <html
      lang="en"
      className={`${geist.variable} ${archivo.variable} ${newsreader.variable} ${geistMono.variable}`}
      data-scroll-behavior="smooth"
    >
      <body
        className={`${geist.className} flex min-h-screen flex-col bg-paper leading-[1.7] text-ink antialiased`}
      >
        <Header />
        <main id="main" className="flex-1">
          {children}
        </main>
        <Footer />
      </body>
    </html>
  );
}
