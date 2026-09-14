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
 * The mark drawn inside the shared circle. Distinct SHAPES, not just distinct
 * colours — PERSON_B_PLAN_v2.md Phase 0.5: a verdict is never colour alone.
 */
const MARK: Record<Verdict, React.ReactNode> = {
  proven: <path d="m8.25 12.25 2.5 2.5 5-5.5" />,
  partial: <path d="M12 3a9 9 0 0 1 0 18z" fill="currentColor" stroke="none" />,
  missing: <path d="m9 9 6 6m0-6-6 6" />,
};

/**
 * check-circle / minus-circle / x-circle, drawn inline so the app needs no icon
 * library. Inherits `currentColor`, and is `aria-hidden` because the verdict
 * word always travels beside it (see Badge).
 */
export const VerdictIcon = React.forwardRef<SVGSVGElement, VerdictIconProps>(
  function VerdictIcon({ verdict, size = "1.25em", className, ...rest }, ref) {
    return (
      <svg
        ref={ref}
        width={size}
        height={size}
        viewBox="0 0 24 24"
        fill="none"
        stroke="currentColor"
        strokeWidth={2}
        strokeLinecap="round"
        strokeLinejoin="round"
        aria-hidden="true"
        focusable="false"
        className={cn("shrink-0", className)}
        {...rest}
      >
        <circle cx="12" cy="12" r="9" />
        {MARK[verdict]}
      </svg>
    );
  },
);
