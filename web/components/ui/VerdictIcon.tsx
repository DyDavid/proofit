import * as React from "react";

import { cn } from "@/lib/utils";

/**
 * The three verdicts, mirroring `Verdict` in engine/normalize/schema.py.
 * Kept as a local literal union rather than imported from lib/types.ts so the
 * design system has no dependency on the generated schema types.
 */
export type Verdict = "proven" | "partial" | "missing";

export interface VerdictIconProps
  extends Omit<React.SVGProps<SVGSVGElement>, "children"> {
  verdict: Verdict;
  /** Any CSS length. Defaults to `1.25em` so the icon scales with its label. */
  size?: number | string;
}

/**
 * check-circle / half-fill-circle / dashed-circle, matching the source
 * design's own three verdict marks exactly: DISTINCT SHAPES, not just
 * distinct colours — PERSON_B_PLAN_v2.md Phase 0.5: a verdict is never
 * colour alone. `currentColor` drives the shape so a parent's `text-proven`
 * / `text-partial-ink` / `text-missing` still controls it (see Badge/Stamp);
 * the proven checkmark itself is drawn in the paper colour for contrast
 * against its own solid fill.
 */
function Mark({ verdict }: { verdict: Verdict }) {
  switch (verdict) {
    case "proven":
      return (
        <>
          <circle cx="12" cy="12" r="9" fill="currentColor" />
          <path
            d="m7.2 12.4 3.1 3.1 6.5-7.4"
            fill="none"
            stroke="var(--color-paper)"
            strokeWidth="2"
          />
        </>
      );
    case "partial":
      return (
        <>
          <circle cx="12" cy="12" r="8.5" fill="none" stroke="currentColor" strokeWidth="1.7" />
          <path d="M12 3.5a8.5 8.5 0 0 1 0 17z" fill="currentColor" />
        </>
      );
    case "missing":
      return (
        <circle
          cx="12"
          cy="12"
          r="8.5"
          fill="none"
          stroke="currentColor"
          strokeWidth="1.7"
          strokeDasharray="3 3"
        />
      );
  }
}

/**
 * Drawn inline so the app needs no icon library. Inherits `currentColor`,
 * and is `aria-hidden` because the verdict word always travels beside it
 * (see Badge).
 */
export const VerdictIcon = React.forwardRef<SVGSVGElement, VerdictIconProps>(
  function VerdictIcon({ verdict, size = "1.25em", className, ...rest }, ref) {
    return (
      <svg
        ref={ref}
        width={size}
        height={size}
        viewBox="0 0 24 24"
        aria-hidden="true"
        focusable="false"
        className={cn("shrink-0", className)}
        {...rest}
      >
        <Mark verdict={verdict} />
      </svg>
    );
  },
);
