import { useTranslations } from "@/lib/copy";
import Link from "next/link";

const WORDMARK = "PROOFIT".split("");

/**
 * Site footer: a breathing oversized wordmark (each letter's variable-font
 * weight/width drifts on a staggered loop, matching the source design's
 * footer), then the tagline row and the About link.
 */
export default function Footer() {
  const t = useTranslations("common");

  return (
    <footer className="border-t border-rule">
      <div className="mx-auto w-full max-w-6xl px-4 pb-8 pt-14 sm:px-8 sm:pt-20">
        <div
          aria-hidden="true"
          className="flex items-end justify-between font-serif text-[15vw] font-extrabold uppercase leading-[0.8] sm:text-[6.5vw]"
        >
          {WORDMARK.map((letter, i) => (
            <span
              key={i}
              className={
                "motion-safe:animate-breathe " +
                (i === WORDMARK.length - 1 ? "text-accent" : "")
              }
              style={{ animationDelay: `${i * 0.18}s` }}
            >
              {letter}
            </span>
          ))}
        </div>

        <div className="mt-8 flex flex-col gap-3 border-t border-rule pt-6 text-sm sm:flex-row sm:items-center sm:justify-between">
          <p className="flex flex-wrap items-baseline gap-x-2 gap-y-1 text-ink-3">
            <span className="font-semibold text-ink">{t("appName")}</span>
            <span>{t("tagline")}</span>
            <Link
              href="/about"
              className="font-medium text-ink-2 underline-offset-4 transition-colors hover:text-ink hover:underline"
            >
              {t("nav.about")}
            </Link>
          </p>
          <p className="font-mono text-xs uppercase tracking-wide text-ink-3">
            {t("footerMeta")}
          </p>
        </div>
      </div>
    </footer>
  );
}
