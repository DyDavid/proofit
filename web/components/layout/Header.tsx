import { useTranslations } from "@/lib/copy";
import { HeaderAuth } from "@/components/auth/HeaderAuth";
import { Button } from "@/components/ui/Button";
import Link from "next/link";

const NAV_ITEMS = [
  { href: "/", key: "nav.home" },
  { href: "/analyze", key: "nav.analyze" },
  { href: "/pricing", key: "nav.pricing" },
  { href: "/about", key: "nav.about" },
] as const;

/**
 * Site header: Proofit wordmark, the three primary routes (each a
 * hover-swap `.link-roll`, matching the source design's nav links), and a
 * primary CTA. Server component.
 */
export default function Header() {
  const t = useTranslations("common");

  return (
    <header className="sticky top-0 z-40 border-b border-rule bg-paper/95 backdrop-blur">
      <div className="mx-auto flex w-full max-w-6xl flex-wrap items-center gap-x-7 gap-y-3 px-4 py-4 sm:px-8">
        <Link
          href="/"
          className="shrink-0 font-serif text-xl font-extrabold uppercase tracking-wide text-ink"
        >
          {t("appName")}
        </Link>

        <nav className="order-3 flex w-full flex-wrap items-center gap-x-8 gap-y-2 text-[15px] sm:order-none sm:w-auto">
          {NAV_ITEMS.map((item) => (
            <Link key={item.href} href={item.href} className="link-roll text-ink-2">
              <span className="link-roll-track">
                <span>{t(item.key)}</span>
                <span aria-hidden="true">{t(item.key)}</span>
              </span>
            </Link>
          ))}
        </nav>

        <div className="ml-auto flex shrink-0 items-center gap-3">
          <HeaderAuth />
          <Button
            as="a"
            href="/analyze"
            size="sm"
            icon="arrow"
            className="hidden sm:inline-flex"
          >
            {t("action.analyze")}
          </Button>
        </div>
      </div>
    </header>
  );
}
