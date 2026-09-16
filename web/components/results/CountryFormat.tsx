"use client";

import { useTranslations } from "next-intl";
import * as React from "react";

import { Badge } from "@/components/ui/Badge";
import { ApiError, getCountryRules, type CountryRules } from "@/lib/api";
import type { Match } from "@/lib/types";
import { cn } from "@/lib/utils";

export interface CountryFormatProps {
  match: Match;
}

/**
 * Canonical values `rules_for` (engine/country/rules.py) accepts directly —
 * the ISO-style codes `Job.country` already uses, plus the UI's sixth
 * option, "other", which is deliberately rule-less. Using these codes
 * (rather than `AnalyzeForm.tsx`'s browser-camelCase spellings) means the
 * selector's default can come straight from `match.job.country` with no
 * translation step, and "other" round-trips through the same real
 * `GET /api/countries/other` 404 path a hand-typed unknown string would.
 */
const DESTINATION_KEYS = ["KH", "SG", "JP", "AU", "REMOTE", "other"] as const;
type DestinationKey = (typeof DESTINATION_KEYS)[number];

function isDestinationKey(value: string | null | undefined): value is DestinationKey {
  return (DESTINATION_KEYS as readonly string[]).includes(value ?? "");
}

/**
 * `errors.*` codes this section renders through the generic catalogue.
 * `COUNTRY_RULES_NOT_FOUND` is deliberately absent: it is the *expected*
 * response for the "other" destination (and for any unrecognised string),
 * not a failure — it gets its own degrade state (`noRules` below, task 4
 * brief's self-review: "must degrade, not error"), never an error banner.
 */
const KNOWN_ERROR_CODES = ["INTERNAL"] as const;

function BulletList({ items }: { items: readonly string[] }) {
  return (
    <ul className="grid gap-1.5">
      {items.map((item) => (
        <li key={item} className="flex gap-2 text-[14px] leading-[1.6] text-ink-2">
          <span aria-hidden="true" className="text-ink-3">
            ·
          </span>
          <span>{item}</span>
        </li>
      ))}
    </ul>
  );
}

function ChecklistCard({
  label,
  children,
  className,
}: {
  label: React.ReactNode;
  children: React.ReactNode;
  className?: string;
}) {
  return (
    <div className={cn("border border-rule bg-surface-raised p-4", className)}>
      <p className="mb-1.5 flex flex-wrap items-center gap-2 font-mono text-[11px] uppercase tracking-wide text-ink-3">
        {label}
      </p>
      {children}
    </div>
  );
}

/** (a) The format checklist: page length, photo, dates, section order, and
 * include/omit personal-detail lists, rendered verbatim from the fetched
 * `CountryRules` — this config's own copy, never re-translated (same
 * convention as `Requirement.text` and `Evidence.source_line`: engine
 * content is English regardless of UI locale). */
function FormatChecklist({ rules }: { rules: CountryRules }) {
  const t = useTranslations("results.country");
  return (
    <div className="grid gap-4 sm:grid-cols-2">
      <ChecklistCard label={t("length")}>
        <p className="text-[14px] leading-[1.6] text-ink">{rules.page_length_note}</p>
      </ChecklistCard>

      <ChecklistCard
        label={
          <>
            {t("photo.label")}
            <Badge tone={rules.include_photo ? "proven" : "muted"}>
              {rules.include_photo ? t("photo.included") : t("photo.omitted")}
            </Badge>
          </>
        }
      >
        <p className="text-[14px] leading-[1.6] text-ink">{rules.photo_note}</p>
      </ChecklistCard>

      <ChecklistCard label={t("dateFormat")}>
        <p className="text-[14px] leading-[1.6] text-ink">
          {rules.date_format}{" "}
          <span className="text-ink-3">— e.g. {rules.date_format_example}</span>
        </p>
      </ChecklistCard>

      <ChecklistCard label={t("sectionOrder")}>
        <ol className="grid gap-1 text-[14px] leading-[1.6] text-ink">
          {rules.section_order.map((section, i) => (
            <li key={section} className="flex gap-2">
              <span className="font-mono text-[11px] text-ink-3">{i + 1}.</span>
              <span>{section}</span>
            </li>
          ))}
        </ol>
      </ChecklistCard>

      <ChecklistCard label={t("include")}>
        <BulletList items={rules.include_personal_details} />
      </ChecklistCard>

      <ChecklistCard label={t("omit")}>
        <BulletList items={rules.omit_personal_details} />
      </ChecklistCard>

      <ChecklistCard label={t("toneNotes")} className="sm:col-span-2">
        <BulletList items={rules.tone_notes} />
      </ChecklistCard>
    </div>
  );
}

/**
 * (b) The visa line — read `engine/country/__init__.py` before touching
 * this. Two rules, both load-bearing:
 *
 * 1. `unstated` is the honest default. Silence in a job post is not a "no",
 *    so an absent or non-yes/no `sponsors_visa` renders the plain unstated
 *    copy — never a negative-sounding badge.
 * 2. A verdict is never shown without the verbatim JD sentence that produced
 *    it. `sourceLine` gates the badge: even if `sponsors_visa` were
 *    somehow "yes" or "no" with no source line, no badge renders — only the
 *    unstated copy. A bare yes/no with no quoted source is not defensible
 *    on screen.
 *
 * `visaTerms` — the country's work-authorisation vocabulary — is shown
 * underneath regardless: it depends on the selected destination's rules,
 * not on whether this particular job post stated anything.
 */
function VisaLine({
  job,
  visaTerms,
}: {
  job: Match["job"];
  visaTerms: readonly string[] | null;
}) {
  const t = useTranslations("results.country.visa");

  const sourceLine = job?.sponsors_visa_source_line ?? null;
  const verdict =
    sourceLine && (job?.sponsors_visa === "yes" || job?.sponsors_visa === "no")
      ? job.sponsors_visa
      : null;

  return (
    <div className="mt-6 border border-rule bg-surface-raised p-4">
      <p className="mb-2 font-mono text-[11px] uppercase tracking-wide text-ink-3">
        {t("title")}
      </p>

      {verdict ? (
        <>
          <Badge tone={verdict === "yes" ? "proven" : "missing"}>
            {verdict === "yes" ? t("badgeYes") : t("badgeNo")}
          </Badge>
          <p className="mb-1 mt-3 font-mono text-[11px] uppercase tracking-wide text-ink-3">
            {t("sourceLabel")}
          </p>
          <p className="text-[14.5px] leading-[1.6] text-ink">
            <mark className="proofit-mark">{sourceLine}</mark>
          </p>
        </>
      ) : (
        <p className="text-[14px] leading-[1.6] text-ink-2">{t("unstated")}</p>
      )}

      {visaTerms && visaTerms.length > 0 ? (
        <div className="mt-4 border-t border-dashed border-rule pt-3">
          <p className="mb-1.5 font-mono text-[11px] uppercase tracking-wide text-ink-3">
            {t("lookForTitle")}
          </p>
          <div className="flex flex-wrap gap-1.5">
            {visaTerms.map((term) => (
              <span
                key={term}
                className="inline-flex items-center rounded-tag border border-rule px-2 py-0.5 text-[12px] text-ink-2"
              >
                {term}
              </span>
            ))}
          </div>
        </div>
      ) : null}
    </div>
  );
}

/**
 * F6's Results-screen section (task 4 brief): "If you're applying
 * elsewhere" — a destination selector, driving (a) the market's format
 * checklist and (b) the visa line's "what to look for" vocabulary. Defaults
 * to the analysis's own destination (`match.job.country`) and re-fetches on
 * change without touching the analysis itself — this section is read-only
 * exploration, never a re-run.
 *
 * (c), the country-toned rewrite prompt, has no UI surface: it is wired
 * server-side through `create_rewrites` (api/routes/analyses.py), which
 * resolves `rules_for(record.country)` independently of whatever destination
 * is selected here.
 */
export function CountryFormat({ match }: CountryFormatProps) {
  const t = useTranslations("results.country");
  const tc = useTranslations("common");
  const te = useTranslations("errors");

  const jobCountry = match.job?.country;
  const [destination, setDestination] = React.useState<DestinationKey>(
    isDestinationKey(jobCountry) ? jobCountry : "KH",
  );
  const [rules, setRules] = React.useState<CountryRules | null>(null);
  const [loading, setLoading] = React.useState(true);
  const [errorCode, setErrorCode] = React.useState<string | null>(null);

  // Guards against a slower earlier fetch resolving after a faster later one
  // when the user switches the selector twice in quick succession.
  const requestIdRef = React.useRef(0);

  React.useEffect(() => {
    const requestId = ++requestIdRef.current;
    setLoading(true);
    setErrorCode(null);
    getCountryRules(destination)
      .then((result) => {
        if (requestIdRef.current !== requestId) return;
        setRules(result);
      })
      .catch((err) => {
        if (requestIdRef.current !== requestId) return;
        setRules(null);
        setErrorCode(err instanceof ApiError && err.code ? err.code : "INTERNAL");
      })
      .finally(() => {
        if (requestIdRef.current !== requestId) return;
        setLoading(false);
      });
  }, [destination]);

  const noRules = errorCode === "COUNTRY_RULES_NOT_FOUND";
  const otherErrorMessage =
    errorCode && !noRules
      ? (KNOWN_ERROR_CODES as readonly string[]).includes(errorCode)
        ? te(errorCode as (typeof KNOWN_ERROR_CODES)[number])
        : te("INTERNAL")
      : null;

  return (
    <section className="mt-12 border-t border-ink pt-10">
      <div className="mb-2 flex flex-wrap items-end justify-between gap-4">
        <h2 className="font-serif text-2xl text-ink">{t("title")}</h2>
        <div className="grid gap-1">
          <label
            htmlFor="country-format-destination"
            className="font-mono text-[11px] uppercase tracking-wide text-ink-3"
          >
            {t("selectLabel")}
          </label>
          <select
            id="country-format-destination"
            value={destination}
            onChange={(e) => setDestination(e.target.value as DestinationKey)}
            className="min-h-9 border border-rule bg-paper px-3 text-[14px] text-ink"
          >
            {DESTINATION_KEYS.map((key) => (
              <option key={key} value={key}>
                {t(`destinations.${key}`)}
              </option>
            ))}
          </select>
        </div>
      </div>
      <p className="mb-5 max-w-2xl text-[15px] leading-[1.6] text-ink-2">{t("intro")}</p>

      {otherErrorMessage ? (
        <p role="alert" className="mb-6 text-sm leading-[1.6] text-missing">
          {otherErrorMessage}
        </p>
      ) : null}

      {loading ? (
        <p className="text-sm text-ink-3">{tc("loading")}</p>
      ) : rules ? (
        <FormatChecklist rules={rules} />
      ) : noRules ? (
        <p className="text-sm leading-[1.6] text-ink-3">{t("noRules")}</p>
      ) : null}

      <VisaLine job={match.job} visaTerms={rules?.visa_terms ?? null} />
    </section>
  );
}
