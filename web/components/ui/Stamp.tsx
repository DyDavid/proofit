import * as React from "react";

import { cn } from "@/lib/utils";

export type StampTone = "proven" | "partial" | "missing";

export interface StampProps extends React.HTMLAttributes<HTMLSpanElement> {
  tone: StampTone;
}

const TONE_CLASS: Record<StampTone, string> = {
  proven: "text-proven",
  partial: "text-partial-ink",
  missing: "text-missing",
};

/**
 * The realism-verdict "rubber stamp": a bordered, slightly rotated box with
 * an inset second border, in the current colour. Used once, for
 * `strong_fit` / `stretch` / `unrealistic` on the Results header.
 */
export const Stamp = React.forwardRef<HTMLSpanElement, StampProps>(
  function Stamp({ tone, className, children, ...rest }, ref) {
    return (
      <span
        ref={ref}
        className={cn(
          "relative inline-block -rotate-3 rounded-tag border-[1.5px] px-3 py-1.5 font-mono text-xs font-medium uppercase tracking-[0.18em]",
          "before:absolute before:inset-[2px] before:rounded-[2px] before:border before:border-current before:opacity-35",
          TONE_CLASS[tone],
          className,
        )}
        style={{ borderColor: "currentColor" }}
        {...rest}
      >
        {children}
      </span>
    );
  },
);
