"use client";

import * as React from "react";
import { Card } from "@/components/ui/Card";
import { getCountryRules, type CountryRulesResponse } from "@/lib/api";

interface CountryFormatCardProps {
  countryCode: string;
  sponsorsVisa?: "yes" | "no" | "unstated";
  visaSourceLine?: string | null;
}

const COUNTRY_FLAGS: Record<string, string> = {
  KH: "🇰🇭",
  SG: "🇸🇬",
  JP: "🇯🇵",
  US: "🇺🇸",
  AU: "🇦🇺",
};

const FALLBACK_RULES: Record<string, CountryRulesResponse> = {
  KH: {
    country_code: "KH",
    name: "Cambodia",
    max_pages: 2,
    photo_recommended: true,
    include_personal_details: true,
    date_format: "DD/MM/YYYY or Month YYYY",
    section_order: ["summary", "education", "experience", "projects", "skills", "languages"],
    tone_notes: "Formal, respectful, highlighting institution names, degrees, and language proficiencies.",
    visa_terms: ["citizen", "work permit", "khmer speaker", "local hire"]
  },
  SG: {
    country_code: "SG",
    name: "Singapore",
    max_pages: 2,
    photo_recommended: false,
    include_personal_details: false,
    date_format: "MMM YYYY (e.g., Jan 2023)",
    section_order: ["summary", "experience", "skills", "projects", "education"],
    tone_notes: "Direct, metrics-focused, concise, emphasizing specific tech stack and project outcomes.",
    visa_terms: ["employment pass", "ep", "s pass", "visa sponsorship", "relocation support", "local candidates only"]
  },
  JP: {
    country_code: "JP",
    name: "Japan",
    max_pages: 2,
    photo_recommended: true,
    include_personal_details: true,
    date_format: "YYYY/MM",
    section_order: ["education", "experience", "skills", "projects", "languages"],
    tone_notes: "Highly structured, detailed institutional and technical context, JLPT level where applicable.",
    visa_terms: ["visa sponsorship available", "work visa", "engineer visa", "japanese requirement", "jlpt"]
  },
  US: {
    country_code: "US",
    name: "United States (Remote)",
    max_pages: 1,
    photo_recommended: false,
    include_personal_details: false,
    date_format: "Month YYYY",
    section_order: ["experience", "projects", "skills", "education"],
    tone_notes: "Impact-driven, active action verbs, quantifiable achievements, strict 1-page format for entry level.",
    visa_terms: ["u.s. citizen", "green card", "h1b", "authorization to work in the u.s.", "w2", "1099", "remote us"]
  },
  AU: {
    country_code: "AU",
    name: "Australia",
    max_pages: 2,
    photo_recommended: false,
    include_personal_details: false,
    date_format: "MMM YYYY (e.g., Jan 2023)",
    section_order: ["summary", "experience", "skills", "education", "projects"],
    tone_notes: "Direct, achievement-oriented, highlighting clear outcomes and key responsibilities.",
    visa_terms: ["working holiday visa", "subclass 482", "tss visa", "visa sponsorship", "permanent residency", "pr", "full working rights"]
  }
};

export function CountryFormatCard({ countryCode, sponsorsVisa = "unstated", visaSourceLine }: CountryFormatCardProps) {
  const [rules, setRules] = React.useState<CountryRulesResponse | null>(null);

  React.useEffect(() => {
    let active = true;
    getCountryRules(countryCode)
      .then((res) => {
        if (active) setRules(res);
      })
      .catch((e) => {
        console.warn("Could not fetch country rules from backend, using static fallback:", e);
        if (active) {
          const fallback = FALLBACK_RULES[countryCode] ?? FALLBACK_RULES.KH;
          setRules(fallback);
        }
      });
    return () => {
      active = false;
    };
  }, [countryCode]);

  if (!rules) {
    return (
      <Card padding="md" className="animate-pulse">
        <div className="h-5 w-1/2 bg-neutral-200 dark:bg-neutral-800 rounded mb-2" />
        <div className="h-4 w-3/4 bg-neutral-200 dark:bg-neutral-800 rounded" />
      </Card>
    );
  }

  const flag = COUNTRY_FLAGS[rules.country_code] || "🌐";

  return (
    <Card padding="lg" className="border border-rule bg-paper">
      <div className="mb-4 flex items-center justify-between border-b border-rule pb-3">
        <div className="flex items-center gap-2">
          <span className="text-2xl">{flag}</span>
          <div>
            <h3 className="font-serif text-lg text-ink font-semibold">
              Format Guidelines for {rules.name}
            </h3>
            <p className="text-xs text-ink-3">Country-specific resume formatting checklist</p>
          </div>
        </div>
      </div>

      <div className="grid gap-3 text-xs leading-relaxed text-ink-2">
        <div className="flex items-center justify-between border-b border-neutral-100 py-1.5 dark:border-neutral-800">
          <span className="font-medium text-ink">Max Page Length:</span>
          <span className="rounded bg-neutral-100 px-2 py-0.5 font-mono text-ink dark:bg-neutral-800">
            {rules.max_pages} {rules.max_pages === 1 ? "page" : "pages"} max
          </span>
        </div>

        <div className="flex items-center justify-between border-b border-neutral-100 py-1.5 dark:border-neutral-800">
          <span className="font-medium text-ink">Photo Policy:</span>
          <span>{rules.photo_recommended ? "📸 Recommended" : "🚫 Omit photo"}</span>
        </div>

        <div className="flex items-center justify-between border-b border-neutral-100 py-1.5 dark:border-neutral-800">
          <span className="font-medium text-ink">Date Format:</span>
          <span className="font-mono text-ink-2">{rules.date_format}</span>
        </div>

        <div className="border-b border-neutral-100 py-1.5 dark:border-neutral-800">
          <span className="font-medium text-ink">Recommended Section Order:</span>
          <div className="mt-1.5 flex flex-wrap gap-1">
            {rules.section_order.map((sec, i) => (
              <span key={sec} className="rounded border border-rule px-1.5 py-0.5 text-[11px] text-ink-2">
                {i + 1}. {sec}
              </span>
            ))}
          </div>
        </div>

        <div className="py-1.5">
          <span className="font-medium text-ink">Tone Note:</span>
          <p className="mt-0.5 text-ink-3 italic">{rules.tone_notes}</p>
        </div>
      </div>

      {/* Visa Signal Line */}
      <div className="mt-4 rounded-md border border-sky-200 bg-sky-50/50 p-3 text-xs dark:border-sky-900/50 dark:bg-sky-950/20">
        <div className="flex items-center justify-between font-semibold text-sky-900 dark:text-sky-200">
          <span>🛂 Visa Sponsorship Signal:</span>
          <span className="uppercase tracking-wider font-mono text-[11px] px-2 py-0.5 rounded bg-sky-100 dark:bg-sky-900">
            {sponsorsVisa}
          </span>
        </div>
        {visaSourceLine ? (
          <p className="mt-1.5 text-sky-800 dark:text-sky-300 italic">
            &quot;{visaSourceLine}&quot;
          </p>
        ) : (
          <p className="mt-1 text-sky-700/80 dark:text-sky-400/80">
            {sponsorsVisa === "yes"
              ? "Job posting mentions visa sponsorship availability."
              : sponsorsVisa === "no"
              ? "Job posting specifies local candidates or work authorization required."
              : "No explicit visa sponsorship statement found in job text."}
          </p>
        )}
      </div>
    </Card>
  );
}
