import * as React from "react";

import type { Verdict } from "@/components/ui/VerdictIcon";

/** Kept exported: `ResultsView.tsx` still builds this shape for
 * `CoverageRing`'s proven/partial arc-share calculation. */
export interface CoverageTile {
  verdict: Verdict;
  required: boolean;
}

export interface CoverageStatProps {
  label: string;
  helpLabel: string;
  value: number;
  note?: string;
}

/**
 * The secondary (required-only) coverage figure: a plain big number plus a
 * caption. The primary figure is `CoverageRing` — this one stays a number
 * because the source design shows only one ring, not two.
 */
export function CoverageStat({ label, helpLabel, value, note }: CoverageStatProps) {
  const rounded = Math.round(value);

  return (
    <div>
      <p className="mb-2 flex items-center gap-2 font-medium text-ink">
        {label}
        <span
          aria-label={helpLabel}
          title={helpLabel}
          className="flex h-5 w-5 shrink-0 items-center justify-center rounded-pill border border-rule font-mono text-[11px] text-ink-3"
        >
          ?
        </span>
      </p>
      <p className="font-serif text-6xl font-extrabold leading-none tracking-tight text-ink">
        {rounded}
        <span className="ml-0.5 text-[0.5em] text-accent">%</span>
      </p>

      {note ? <p className="mt-3.5 max-w-[42ch] text-sm text-ink-2">{note}</p> : null}
    </div>
  );
}
