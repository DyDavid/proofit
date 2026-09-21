import type { Metadata } from "next";
import { Fraunces, IBM_Plex_Mono, Kantumruy_Pro } from "next/font/google";
import type { ReactNode } from "react";
import Footer from "@/components/layout/Footer";
import Header from "@/components/layout/Header";
import { getTranslations } from "@/lib/copy";
import "./globals.css";

/** Kantumruy Pro is the single UI font (BRAND.md §4). */
const kantumruyPro = Kantumruy_Pro({
  subsets: ["latin"],
  weight: ["300", "400", "500", "600", "700"],
  variable: "--font-kantumruy",
  display: "swap",
});

/** Display face for headlines and the big coverage numbers (BRAND.md §4). */
const fraunces = Fraunces({
  subsets: ["latin"],
  weight: ["300", "400", "500", "600"],
  style: ["normal", "italic"],
  variable: "--font-fraunces",
  display: "swap",
});

/** Label/data face: eyebrows, timestamps, verdict pills, stamps, confidence
 * figures (BRAND.md §4). */
const ibmPlexMono = IBM_Plex_Mono({
  subsets: ["latin"],
  weight: ["400", "500"],
  variable: "--font-plex-mono",
  display: "swap",
});

export async function generateMetadata(): Promise<Metadata> {
  const t = await getTranslations("common");
  const tLanding = await getTranslations("landing");

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

export default function RootLayout({ children }: { children: ReactNode }) {
  return (
    <html
      lang="en"
      className={`${kantumruyPro.variable} ${fraunces.variable} ${ibmPlexMono.variable}`}
      data-scroll-behavior="smooth"
    >
      <body
        className={`${kantumruyPro.className} flex min-h-screen flex-col bg-paper leading-[1.75] text-ink antialiased`}
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
