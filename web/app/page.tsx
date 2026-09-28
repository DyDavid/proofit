import Link from "next/link";
import { getTranslations } from "@/lib/copy";

import { Button } from "@/components/ui/Button";
import { EvidenceScene } from "@/components/landing/EvidenceScene";

const ROTATING_WORDS = [
  "coursework",
  "capstone",
  "part-time job",
  "club project",
  "hackathon",
];

const MARQUEE_WORDS = [
  "Coursework",
  "Capstones",
  "Part-time jobs",
  "Clubs",
  "Hackathons",
  "Volunteering",
];

/** Splits text into spans that each run the letter-morph reveal on their own
 * stagger — the source design's `.ch` treatment for "Experience." */
function LetterReveal({
  text,
  startDelay = 0.5,
  step = 0.04,
}: {
  text: string;
  startDelay?: number;
  step?: number;
}) {
  return (
    <>
      {text.split("").map((ch, i) => (
        <span
          key={i}
          className="motion-safe:animate-letter-morph inline-block"
          style={{ animationDelay: `${startDelay + i * step}s` }}
        >
          {ch === " " ? " " : ch}
        </span>
      ))}
    </>
  );
}

/** The hero's vertically-cycling word — one accessible copy, the rest
 * `aria-hidden`, matching the source design exactly. Pure CSS animation, no
 * client JS needed. */
function RotatingWord({ words }: { words: string[] }) {
  const loop = [...words, words[0]];
  return (
    <span className="block h-[1em] overflow-hidden">
      <span className="motion-safe:animate-word-carousel block" style={{ animationDelay: "0.3s" }}>
        {loop.map((word, i) => (
          <span
            key={i}
            aria-hidden={i === 0 ? undefined : true}
            className="font-accent block leading-[1] italic text-accent"
          >
            {word}
          </span>
        ))}
      </span>
    </span>
  );
}

/** Two duplicated tracks scrolling opposite directions, seamless via
 * `translateX(-50%)` on content rendered twice (second copy `aria-hidden`). */
function Marquee({
  children,
  reverse,
}: {
  children: React.ReactNode;
  reverse?: boolean;
}) {
  return (
    <div className="overflow-hidden">
      <div
        className={
          "flex w-max " +
          (reverse ? "motion-safe:animate-marquee-reverse" : "motion-safe:animate-marquee")
        }
      >
        <div className="flex shrink-0">{children}</div>
        <div className="flex shrink-0" aria-hidden="true">
          {children}
        </div>
      </div>
    </div>
  );
}

function ForwardArrow({ className }: { className?: string }) {
  return (
    <svg
      className={className}
      width="1em"
      height="1em"
      viewBox="0 0 40 40"
      fill="none"
      stroke="currentColor"
      strokeWidth="2"
      aria-hidden="true"
    >
      <path d="M6 20h28M24 10l10 10-10 10" />
    </svg>
  );
}

function UploadDiagram() {
  return (
    <svg width="140" height="120" viewBox="0 0 220 190" fill="none" aria-hidden="true">
      <path d="M78 18h48l16 16v100H78z" stroke="var(--color-ink)" strokeWidth="1.5" fill="var(--color-paper)" />
      <path d="M126 18v16h16" stroke="var(--color-ink)" strokeWidth="1.5" />
      <rect
        x="90"
        y="52"
        width="40"
        height="4"
        rx="2"
        fill="var(--color-faint)"
        className="motion-safe:animate-line-loop"
        style={{ transformOrigin: "0 50%" }}
      />
      <rect
        x="90"
        y="66"
        width="30"
        height="4"
        rx="2"
        fill="var(--color-accent)"
        className="motion-safe:animate-line-loop"
        style={{ transformOrigin: "0 50%", animationDelay: "0.15s" }}
      />
      <rect
        x="90"
        y="80"
        width="42"
        height="4"
        rx="2"
        fill="var(--color-faint)"
        className="motion-safe:animate-line-loop"
        style={{ transformOrigin: "0 50%", animationDelay: "0.3s" }}
      />
      <rect
        x="90"
        y="94"
        width="26"
        height="4"
        rx="2"
        fill="var(--color-accent)"
        className="motion-safe:animate-line-loop"
        style={{ transformOrigin: "0 50%", animationDelay: "0.45s" }}
      />
      <rect
        x="90"
        y="108"
        width="36"
        height="4"
        rx="2"
        fill="var(--color-faint)"
        className="motion-safe:animate-line-loop"
        style={{ transformOrigin: "0 50%", animationDelay: "0.6s" }}
      />
      <g className="motion-safe:animate-up-loop" style={{ transformOrigin: "center" }}>
        <path d="M110 178V152M99 163l11-11 11 11" stroke="var(--color-accent)" strokeWidth="2" />
      </g>
    </svg>
  );
}

function JobPostDiagram() {
  return (
    <svg width="140" height="120" viewBox="0 0 220 190" fill="none" aria-hidden="true">
      <rect x="60" y="20" width="100" height="150" rx="12" stroke="var(--color-ink)" strokeWidth="1.5" fill="var(--color-paper)" />
      <circle cx="78" cy="40" r="7" fill="var(--color-rule-2)" />
      <rect x="92" y="36" width="46" height="4" rx="2" fill="var(--color-rule-2)" />
      <rect x="74" y="62" width="72" height="4" rx="2" fill="var(--color-rule-2)" />
      <rect x="74" y="76" width="58" height="4" rx="2" fill="var(--color-rule-2)" />
      <rect x="74" y="90" width="66" height="4" rx="2" fill="var(--color-rule-2)" />
      <rect x="74" y="104" width="50" height="4" rx="2" fill="var(--color-rule-2)" />
      <rect x="74" y="118" width="62" height="4" rx="2" fill="var(--color-rule-2)" />
      <rect x="74" y="132" width="40" height="4" rx="2" fill="var(--color-rule-2)" />
      <g className="motion-safe:animate-scan">
        <rect x="54" y="38" width="112" height="22" fill="var(--color-accent)" fillOpacity=".08" />
        <rect x="54" y="58" width="112" height="2" fill="var(--color-accent)" />
      </g>
      <g className="motion-safe:animate-blink" stroke="var(--color-accent)" strokeWidth="2">
        <path d="M48 26V12h14" />
        <path d="M158 12h14v14" />
        <path d="M172 164v14h-14" />
        <path d="M62 178H48v-14" />
      </g>
    </svg>
  );
}

function VerdictDiagram() {
  return (
    <svg width="140" height="120" viewBox="0 0 220 190" fill="none" aria-hidden="true">
      <circle cx="62" cy="55" r="11" stroke="var(--color-ink)" strokeWidth="1.5" />
      <rect x="86" y="52" width="82" height="6" rx="3" fill="var(--color-rule)" />
      <circle
        cx="62"
        cy="55"
        r="11"
        fill="var(--color-accent)"
        className="motion-safe:animate-v-loop"
        style={{ transformOrigin: "center" }}
      />
      <rect
        x="86"
        y="52"
        width="82"
        height="6"
        rx="3"
        fill="var(--color-accent)"
        className="motion-safe:animate-line-loop"
        style={{ transformOrigin: "0 50%", animationDelay: "0.1s", animationDuration: "3.6s" }}
      />

      <circle cx="62" cy="95" r="11" stroke="var(--color-ink)" strokeWidth="1.5" />
      <rect x="86" y="92" width="82" height="6" rx="3" fill="var(--color-rule)" />
      <path
        d="M62 84a11 11 0 0 1 0 22z"
        fill="var(--color-ink)"
        className="motion-safe:animate-v-loop"
        style={{ transformOrigin: "center", animationDelay: "0.5s" }}
      />
      <rect
        x="86"
        y="92"
        width="44"
        height="6"
        rx="3"
        fill="var(--color-ink)"
        className="motion-safe:animate-line-loop"
        style={{ transformOrigin: "0 50%", animationDelay: "0.6s", animationDuration: "3.6s" }}
      />

      <circle
        cx="62"
        cy="135"
        r="11"
        stroke="var(--color-ink-3)"
        strokeWidth="1.5"
        strokeDasharray="3 3"
        className="motion-safe:animate-blink"
        style={{ animationDuration: "1.4s" }}
      />
      <rect x="86" y="132" width="82" height="6" rx="3" fill="none" stroke="var(--color-rule-2)" strokeDasharray="3 3" />
    </svg>
  );
}

/**
 * Landing — redesigned against the "Spean" design canvas (2026-09-28):
 * rotating-word hero, evidence marquee, a scroll-reveal proof scene, a
 * three-step "how it works", and a full-bleed "why Proofit" band. Copy is
 * carried through Proofit's own i18n system (`messages/en.json`
 * `landing.*`) so it stays a single source of truth, not hardcoded JSX.
 */
export default async function LandingPage() {
  const t = await getTranslations("landing");

  return (
    <div className="overflow-x-clip">
      {/* ---------------------------------------------------------------- Hero */}
      <section className="relative px-4 pb-8 pt-10 sm:px-8 sm:pt-16 lg:pt-24">
        <div
          aria-hidden="true"
          className="motion-safe:animate-drift pointer-events-none absolute -right-32 top-10 hidden select-none font-mono text-[22rem] font-bold leading-none text-transparent [-webkit-text-stroke:1px_var(--color-rule)] lg:block"
        >
          fit
        </div>

        <div className="relative">
          <div className="motion-safe:animate-rise flex flex-wrap gap-x-8 gap-y-2 font-mono text-xs uppercase tracking-[0.14em] text-ink-3">
            <span>{t("hero.eyebrowResume")}</span>
            <span>{t("hero.eyebrowPlace")}</span>
            <span className="text-accent">{t("hero.eyebrowAudience")}</span>
          </div>

          <h1 className="mt-8 font-serif text-[3rem] font-extrabold uppercase leading-[0.92] tracking-tight sm:text-[5.5rem] lg:text-[8rem]">
            <span className="motion-safe:animate-line-reveal block" style={{ animationDelay: "0.1s" }}>
              {t("hero.rotatingPrefix")}
            </span>
            <RotatingWord words={ROTATING_WORDS} />
            <span
              className="motion-safe:animate-line-reveal block whitespace-nowrap"
              style={{ animationDelay: "0.34s" }}
            >
              <LetterReveal text={`${t("hero.rotatingSuffix")} ${t("hero.experienceWord")}`} />
            </span>
          </h1>

          <p
            className="motion-safe:animate-rise mt-8 max-w-xl text-lg leading-relaxed text-ink-2"
            style={{ animationDelay: "0.9s" }}
          >
            {t("hero.subtitle")}
          </p>

          <div
            className="motion-safe:animate-rise mt-8 flex flex-wrap items-center gap-4"
            style={{ animationDelay: "1.05s" }}
          >
            <Button as="a" href="/analyze" size="lg" icon="arrow">
              {t("hero.cta")}
            </Button>
            <Button as="a" href="/results" variant="ghost" size="lg">
              {t("hero.ctaSecondary")}
            </Button>
          </div>

          <div
            className="motion-safe:animate-fade mt-14 hidden items-center gap-4 lg:flex"
            style={{ animationDelay: "1.3s" }}
          >
            <span className="relative h-11 w-px overflow-hidden bg-rule">
              <span className="motion-safe:animate-scroll-cue absolute inset-0 bg-accent" />
            </span>
            <span className="font-mono text-[11px] uppercase tracking-[0.16em] text-ink-3">
              {t("hero.scrollCue")}
            </span>
          </div>
        </div>
      </section>

      {/* ------------------------------------------------------------ Marquee */}
      <section
        aria-label="What counts as evidence"
        className="flex flex-col gap-2 border-y border-rule py-6"
      >
        <Marquee>
          {MARQUEE_WORDS.map((word, i) => (
            <span key={word} className="flex items-center gap-6 pr-6 sm:gap-10 sm:pr-10">
              <span
                className={
                  "font-serif text-4xl font-extrabold uppercase sm:text-6xl lg:text-7xl " +
                  (i % 2 === 1 ? "text-transparent [-webkit-text-stroke:1px_var(--color-ink)]" : "")
                }
              >
                {word}
              </span>
              <span className="h-3 w-3 shrink-0 rounded-full bg-accent" />
            </span>
          ))}
        </Marquee>
        <Marquee reverse>
          {Array.from({ length: 3 }).map((_, i) => (
            <span key={i} className="flex items-center gap-4 pr-4 sm:gap-6 sm:pr-6">
              <span className="font-accent text-xl italic text-ink-2 sm:text-3xl">
                {t("marquee.caption")}
              </span>
              <ForwardArrow className="text-accent" />
            </span>
          ))}
        </Marquee>
      </section>

      {/* ------------------------------------------------------- Evidence scene */}
      <section className="mx-auto w-full max-w-6xl px-4 pt-20 sm:px-8 sm:pt-32">
        <div className="grid gap-6 sm:grid-cols-12 sm:items-end">
          <div className="sm:col-span-7">
            <p className="font-mono text-xs uppercase tracking-[0.14em] text-ink-3">
              {t("scene.eyebrow")}
            </p>
            <h2 className="mt-6 font-serif text-4xl font-extrabold uppercase leading-[0.9] sm:text-6xl lg:text-7xl">
              {t("scene.title")}
              <br />
              <span className="font-accent normal-case italic text-accent">
                {t("scene.titleAccent")}
              </span>
            </h2>
          </div>
          <p className="text-ink-2 sm:col-span-4 sm:col-start-9">{t("scene.body")}</p>
        </div>

        <div className="mt-16">
          <EvidenceScene
            strings={{
              resumeLabel: t("scene.resumeLabel"),
              jobLabel: t("scene.jobLabel"),
              countLabel: t("scene.countLabel"),
              coverageLabel: t("scene.coverageLabel"),
              proven: t("scene.proven"),
              partial: t("scene.partial"),
              missing: t("scene.missing"),
              weightingNote: t("scene.weightingNote"),
            }}
          />
        </div>

        <div className="mt-14 flex justify-end">
          <Link href="/results" className="link-roll text-base">
            <span className="link-roll-track">
              <span>{t("scene.cta")} →</span>
              <span aria-hidden="true">{t("scene.cta")} →</span>
            </span>
          </Link>
        </div>
      </section>

      {/* --------------------------------------------------------- How it works */}
      <section id="how" className="mx-auto w-full max-w-6xl px-4 pt-24 sm:px-8 sm:pt-40">
        <div className="grid gap-6 sm:grid-cols-12 sm:items-end">
          <div className="sm:col-span-8">
            <p className="font-mono text-xs uppercase tracking-[0.14em] text-ink-3">
              {t("how.eyebrow")}
            </p>
            <h2 className="mt-6 font-serif text-4xl font-extrabold uppercase leading-[0.9] sm:text-6xl lg:text-7xl">
              {t("how.title")}
              <br />
              <span className="font-accent normal-case italic text-accent">
                {t("how.titleAccent")}
              </span>
            </h2>
          </div>
          <p className="text-ink-2 sm:col-span-4">{t("how.intro")}</p>
        </div>

        <div className="relative mt-14 h-0.5 overflow-hidden bg-rule">
          <span className="motion-safe:animate-progress-run absolute left-0 top-0 h-0.5 w-48 bg-gradient-to-r from-accent/0 to-accent" />
        </div>

        <div className="mt-10 grid gap-10 sm:grid-cols-3">
          {[
            { title: t("how.step1.title"), body: t("how.step1.body"), Diagram: UploadDiagram },
            { title: t("how.step2.title"), body: t("how.step2.body"), Diagram: JobPostDiagram },
            { title: t("how.step3.title"), body: t("how.step3.body"), Diagram: VerdictDiagram },
          ].map((step, i) => (
            <div key={step.title} className="flex flex-col">
              <div className="flex h-56 items-center justify-center rounded-card border border-rule bg-surface-raised">
                <step.Diagram />
              </div>
              <div className="mt-7 flex items-baseline gap-4">
                <span className="font-mono text-xs text-accent">
                  {String(i + 1).padStart(2, "0")}
                </span>
                <h3 className="font-serif text-3xl font-extrabold uppercase">{step.title}</h3>
              </div>
              <p className="mt-3 max-w-sm text-ink-2">{step.body}</p>
            </div>
          ))}
        </div>
      </section>

      {/* --------------------------------------------------------- Why Proofit */}
      <section className="relative mt-24 overflow-hidden bg-accent px-4 py-16 text-paper sm:mt-40 sm:px-8 sm:py-28 lg:py-36">
        <a
          href="/analyze"
          aria-label={t("why.cta")}
          className="group absolute right-4 top-10 hidden h-36 w-36 sm:right-8 sm:block"
        >
          <svg
            className="motion-safe:animate-badge-spin absolute inset-0"
            viewBox="0 0 184 184"
            aria-hidden="true"
          >
            <defs>
              <path id="why-badge-circle" d="M92 92 m-72 0 a72 72 0 1 1 144 0 a72 72 0 1 1 -144 0" />
            </defs>
            <text fill="currentColor" fontSize="12" letterSpacing="1">
              <textPath href="#why-badge-circle">
                UPLOAD · MATCH · IMPROVE · UPLOAD · MATCH · IMPROVE ·
              </textPath>
            </text>
          </svg>
          <span className="absolute left-1/2 top-1/2 flex h-16 w-16 -translate-x-1/2 -translate-y-1/2 items-center justify-center rounded-full bg-paper text-accent">
            <svg width="24" height="24" viewBox="0 0 28 28" fill="none" stroke="currentColor" strokeWidth="2" aria-hidden="true">
              <path d="M7 21L21 7M10 7h11v11" />
            </svg>
          </span>
        </a>

        <p className="font-mono text-xs uppercase tracking-[0.14em] text-accent-tint-2">
          {t("why.eyebrow")}
        </p>
        <h2 className="mt-8 max-w-4xl font-serif text-4xl font-extrabold uppercase leading-[0.92] sm:text-6xl lg:text-8xl">
          {t("why.title")}{" "}
          <span className="font-accent normal-case italic">{t("why.titleAccent")}</span>
        </h2>

        <div className="mt-16 grid gap-10 sm:grid-cols-2">
          <div className="border-t-[1.5px] border-paper pt-7">
            <h3 className="font-serif text-2xl font-bold">{t("why.point1.title")}</h3>
            <p className="mt-4 text-accent-tint-2">{t("why.point1.body")}</p>
          </div>
          <div className="border-t-[1.5px] border-paper pt-7">
            <h3 className="font-serif text-2xl font-bold">{t("why.point2.title")}</h3>
            <p className="mt-4 text-accent-tint-2">{t("why.point2.body")}</p>
          </div>
        </div>

        <div className="mt-16">
          <Button as="a" href="/analyze" size="lg" icon="arrow" variant="invert">
            {t("why.cta")}
          </Button>
        </div>
      </section>
    </div>
  );
}
