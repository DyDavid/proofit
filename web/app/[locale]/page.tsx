import { getTranslations } from "next-intl/server";

import { Button } from "@/components/ui/Button";

const DIFFERENTIATORS = ["evidence", "local", "crossborder"] as const;
const STEPS = ["step1", "step2", "step3"] as const;

/**
 * Landing — Phase 1 scope (PERSON_B_PLAN_v2.md §5 Phase 1 task 5): headline,
 * 3 differentiator cards, CTA, bilingual. The how-it-works strip is a small
 * addition reusing established copy so the page doesn't stop after one
 * screenful of content.
 */
export default async function LandingPage() {
  const t = await getTranslations("landing");

  return (
    <div>
      <section className="mx-auto w-full max-w-6xl px-4 pb-16 pt-16 sm:px-6 sm:pt-24">
        <p className="mb-4 font-mono text-xs uppercase tracking-[0.14em] text-ink-3">
          {t("hero.eyebrow")}
        </p>
        <h1 className="max-w-3xl font-serif text-5xl leading-[1.02] tracking-tight text-ink sm:text-7xl">
          {t.rich("hero.title", {
            em: (chunks) => <em className="italic text-lac">{chunks}</em>,
          })}
        </h1>
        <p className="mt-6 max-w-2xl text-lg leading-[1.7] text-ink-2">
          {t("hero.subtitle")}
        </p>
        <div className="mt-8 flex flex-wrap items-center gap-4">
          <Button as="a" href="/analyze" size="lg">
            {t("hero.cta")}
          </Button>
          <Button as="a" href="/results" variant="ghost" size="lg">
            {t("hero.ctaSecondary")}
          </Button>
        </div>
      </section>

      <section className="border-t border-rule py-16">
        <div className="mx-auto grid w-full max-w-6xl px-4 sm:grid-cols-3 sm:px-6">
          {DIFFERENTIATORS.map((key, i) => (
            <div
              key={key}
              className="border-rule py-6 sm:border-r sm:px-8 sm:py-0 sm:first:pl-0 sm:last:border-r-0 sm:[&:not(:first-child)]:pl-8"
            >
              <span className="mb-4 block font-serif text-5xl font-light text-lac">
                {String(i + 1).padStart(2, "0")}
              </span>
              <h3 className="mb-2 font-serif text-xl text-ink">
                {t(`diff.${key}.title`)}
              </h3>
              <p className="text-[15.5px] leading-[1.65] text-ink-2">
                {t(`diff.${key}.body`)}
              </p>
            </div>
          ))}
        </div>
      </section>

      <section className="mx-auto w-full max-w-6xl px-4 py-16 sm:px-6">
        <p className="mb-9 font-mono text-xs uppercase tracking-[0.14em] text-ink-3">
          {t("how.eyebrow")}
        </p>
        <div className="relative grid gap-10 pt-9 before:absolute before:inset-x-0 before:top-2 before:border-t before:border-ink sm:grid-cols-3 sm:gap-8">
          {STEPS.map((key, i) => (
            <div key={key} className="relative">
              <span className="absolute -top-9 left-0 h-2.5 w-2.5 rounded-pill bg-ink" />
              <p className="mb-2 font-mono text-xs tracking-wide text-ink-3">
                {`STEP ${i + 1}`}
              </p>
              <h4 className="mb-1.5 font-serif text-xl text-ink">
                {t(`how.${key}.title`)}
              </h4>
              <p className="text-[15px] leading-[1.65] text-ink-2">
                {t(`how.${key}.body`)}
              </p>
            </div>
          ))}
        </div>
      </section>
    </div>
  );
}
