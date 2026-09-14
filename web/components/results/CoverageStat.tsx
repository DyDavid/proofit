import * as React from "react";

import type { Verdict } from "@/components/ui/VerdictIcon";
import { cn } from "@/lib/utils";

export interface CoverageTile {
  verdict: Verdict;
  required: boolean;
}

export interface CoverageStatProps {
  label: string;
  helpLabel: string;
  value: number;
  /** Per-requirement tile row (the reference's `.tiles.lg`). Omit for the
   * required-only column, which shows `note` instead. */
  tiles?: CoverageTile[];
  underlineLabel?: string;
  note?: string;
}

const TILE_CLASS: Record<Verdict, string> = {
  proven: "bg-proven",
  partial: "bg-partial",
  missing: "bg-missing",
};

/**
 * Big serif percentage + optional colour-tile requirement bar, replacing a
 * circular gauge — the reference has no ring gauge at all, just this.
 */
export function CoverageStat({
  label,
  helpLabel,
  value,
  tiles,
  underlineLabel,
  note,
}: CoverageStatProps) {
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
      <p className="font-serif text-6xl leading-none tracking-tight text-ink">
        {rounded}
        <span className="ml-0.5 font-mono text-sm uppercase tracking-wide text-ink-3">
          %
        </span>
      </p>

      {tiles ? (
        <>
          <div className="mt-4 flex gap-1.5" aria-hidden="true">
            {tiles.map((tile, i) => (
              <span
                key={i}
                className={cn(
                  "relative h-[22px] flex-1 rounded-[3px]",
                  TILE_CLASS[tile.verdict],
                  tile.required &&
                    "after:absolute after:inset-x-0 after:-bottom-1.5 after:h-0.5 after:bg-ink-3 after:opacity-60",
                )}
              />
            ))}
          </div>
          {underlineLabel ? (
            <p className="mt-2 font-mono text-xs text-ink-3">{underlineLabel}</p>
          ) : null}
        </>
      ) : null}

      {note ? (
        <p className="mt-3.5 max-w-[42ch] text-sm text-ink-2">{note}</p>
      ) : null}
    </div>
  );
}
